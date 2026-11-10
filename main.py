"""battle-marker CLI.

  uv run main.py sessions
  uv run main.py scan [SESSION] [--from H:MM:SS] [--to H:MM:SS] [--cpu]
  uv run main.py mark [SESSION] [--write] [--force]
  uv run main.py dump [SESSION] --at H:MM:SS [--seconds 4]

SESSION is a bg_* folder name and defaults to the newest one.
All times given or printed are timeline times, the ones Steam shows.
"""

import argparse
import json
import sys
import time as clock
from dataclasses import asdict
from pathlib import Path

import cv2

import config
from decode.reader import read_frames
from detect import ocr
from detect.detector import BadgeDetector
from events.highlights import build_highlights
from events.rules import load_rules
from events.tracker import Appearance, AppearanceTracker, Sighting
from markers.writer import (
    PlannedMarker, apply_markers, backup, plan_markers, steam_running,
)
from recording.session import Session, find_session, find_sessions
from recording.timeline import load_timeline


def parse_time(value: str) -> float:
    seconds = 0.0
    for part in value.split(":"):
        seconds = seconds * 60 + float(part)
    return seconds


def fmt(seconds: float) -> str:
    sign = "-" if seconds < 0 else ""
    seconds = abs(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{sign}{int(h)}:{int(m):02d}:{s:04.1f}"


def pick_session(name: str | None) -> Session:
    if name:
        return find_session(config.RECORDINGS_ROOT, name)
    sessions = [s for s in find_sessions(config.RECORDINGS_ROOT) if s.chunk_numbers()]
    if not sessions:
        sys.exit(f"No recordings found under {config.RECORDINGS_ROOT}")
    return max(sessions, key=lambda s: s.name.split("_", 2)[2])


def check_resolution(session: Session) -> None:
    size = (session.track.width, session.track.height)
    if size != config.SOURCE_SIZE:
        sys.exit(f"{session.name} is {size[0]}x{size[1]}. Templates are cut for "
                 f"{config.SOURCE_SIZE[0]}x{config.SOURCE_SIZE[1]} recordings.")


def scan_path(session: Session) -> Path:
    return config.OUTPUT_DIR / f"{session.name}.json"


def frames_for(session: Session, args: argparse.Namespace, start: float | None, end: float | None):
    return read_frames(
        session,
        ffmpeg=config.FFMPEG,
        roi=config.ROI,
        source_size=config.SOURCE_SIZE,
        fps=config.SAMPLE_FPS,
        gpu=not args.cpu,
        start=start,
        end=end,
    )


def cmd_sessions(args: argparse.Namespace) -> None:
    for s in find_sessions(config.RECORDINGS_ROOT):
        chunks = s.chunk_numbers()
        markers = len(load_timeline(s.timeline_path).entries)
        span = "no chunks"
        if chunks:
            first = s.to_timeline(s.track.chunk_start(chunks[0]))
            last = s.to_timeline(s.track.chunk_start(chunks[-1]) + s.track.segment_seconds)
            span = f"{fmt(first)} to {fmt(last)}"
        print(f"{s.name}  offset {s.offset:+.0f}s  {span}  "
              f"{s.timeline_path.name} ({markers} entries)")


class Stopwatch:
    """Adds up where scan time goes, so the slow stage is measured, not guessed."""

    def __init__(self) -> None:
        self.seconds: dict[str, float] = {}
        self.calls: dict[str, int] = {}

    def add(self, name: str, seconds: float) -> None:
        self.seconds[name] = self.seconds.get(name, 0.0) + seconds
        self.calls[name] = self.calls.get(name, 0) + 1

    def wrap(self, name: str, fn):
        def timed(*args, **kwargs):
            began = clock.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                self.add(name, clock.perf_counter() - began)
        return timed

    def report(self, total: float) -> str:
        parts = [f"{name} {sec:.1f}s ({self.calls[name]} calls)" for name, sec in self.seconds.items()]
        other = total - sum(self.seconds.values())
        return ", ".join(parts + [f"other {other:.1f}s"])


def cmd_scan(args: argparse.Namespace) -> None:
    session = pick_session(args.session)
    check_resolution(session)
    ocr.configure(config.TESSERACT_CMD)
    start = session.to_video(parse_time(args.from_)) if args.from_ else None
    end = session.to_video(parse_time(args.to)) if args.to else None

    detector = BadgeDetector(
        config.TEMPLATES_DIR, config.REGIONS,
        config.PRESENCE_THRESHOLD, config.BANNER_THRESHOLD, config.HEADSHOT_THRESHOLD,
        config.READABLE_THRESHOLD,
    )
    watch = Stopwatch()
    tracker = AppearanceTracker(
        banner_box=config.BANNER_TEXT_BOX,
        tag_box=config.TAG_TEXT_BOX,
        confirm_samples=config.CONFIRM_SAMPLES,
        gap_tolerance=config.GAP_TOLERANCE,
        change_threshold=config.TEXT_CHANGE_THRESHOLD,
        confirm_reads=config.TEXT_CONFIRM_READS,
        banner_reader=watch.wrap("ocr", ocr.read_banner),
        tag_reader=watch.wrap("ocr", ocr.read_tag),
    )

    print(f"Scanning {session.name} (offset {session.offset:+.0f}s, "
          f"{'CPU' if args.cpu else 'GPU'} decode)")
    began = clock.perf_counter()
    frames = 0
    next_report = clock.perf_counter() + 30
    first_time = last_time = None
    stream = iter(frames_for(session, args, start, end))
    analyse = watch.wrap("templates", detector.analyse)
    while True:
        waited = clock.perf_counter()
        frame = next(stream, None)
        watch.add("waiting for frames", clock.perf_counter() - waited)
        if frame is None:
            break
        frames += 1
        if first_time is None:
            first_time = frame.time
        last_time = frame.time
        tracker.update(frame.time, analyse(frame.image), frame.image)
        if clock.perf_counter() >= next_report:
            speed = frames / config.SAMPLE_FPS / (clock.perf_counter() - began)
            print(f"  at {fmt(session.to_timeline(frame.time))}  "
                  f"{len(tracker.finished)} badges  {speed:.1f}x realtime", flush=True)
            next_report += 30
    appearances = tracker.finish()

    if frames == 0:
        sys.exit("No frames decoded. Check the time range and the ffmpeg setup.")

    # A partial scan only replaces the badges inside the range it covered.
    kept = [a for a in load_scan(session, required=False)
            if a.end < first_time or a.start > last_time]
    merged = sorted(kept + appearances, key=lambda a: a.start)

    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    result = {
        "session": session.name,
        "timeline": session.timeline_path.name,
        "offset": session.offset,
        "appearances": [asdict(a) for a in merged],
    }
    scan_path(session).write_text(json.dumps(result, indent=2), encoding="utf-8")

    elapsed = clock.perf_counter() - began
    print(f"Scanned {fmt(frames / config.SAMPLE_FPS)} of video in {fmt(elapsed)}. "
          f"{len(appearances)} badges, log in {scan_path(session)}")
    print(f"Time spent: {watch.report(elapsed)}")
    for a in appearances:
        labels = ", ".join(f"{s.kind}:{s.label}" for s in a.sightings) or "(no text read)"
        print(f"  {fmt(session.to_timeline(a.start))}  {labels}")


def load_scan(session: Session, required: bool = True) -> list[Appearance]:
    path = scan_path(session)
    if not path.exists():
        if not required:
            return []
        sys.exit(f"No scan for {session.name}. Run the scan command first.")
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        Appearance(start=a["start"], end=a["end"],
                   sightings=[Sighting(**s) for s in a["sightings"]])
        for a in data["appearances"]
    ]


def cmd_mark(args: argparse.Namespace) -> None:
    session = pick_session(args.session)
    highlights = build_highlights(
        load_scan(session),
        rules=load_rules(config.MARKERS_FILE),
        merge_seconds=config.HIGHLIGHT_MERGE_SECONDS,
    )
    timeline = load_timeline(session.timeline_path)
    candidates = [
        PlannedMarker(
            session.to_timeline(h.time) - config.MARKER_LEAD_SECONDS,
            h.title, h.top.icon, h.top.priority,
        )
        for h in highlights
    ]
    new, skipped = plan_markers(timeline, candidates, config.MARKER_DEDUP_SECONDS)

    print(f"{session.name} -> {timeline.path.name}")
    for m in new:
        print(f"  add   {fmt(m.timeline_seconds)}  {m.icon:<16} {m.title}")
    for m in skipped:
        print(f"  skip  {fmt(m.timeline_seconds)}  {m.icon:<16} {m.title}  (marker already close or out of range)")
    if not new:
        print("Nothing to add.")
        return
    if not args.write:
        print("Dry run. Add --write to save these markers.")
        return
    if steam_running() and not args.force:
        sys.exit("Steam is running and may overwrite the timeline. Close Steam or pass --force.")
    saved = backup(timeline, config.BACKUP_DIR)
    apply_markers(timeline, new)
    print(f"Wrote {len(new)} markers. Backup in {saved}")


def cmd_dump(args: argparse.Namespace) -> None:
    session = pick_session(args.session)
    at = session.to_video(parse_time(args.at))
    target = config.OUTPUT_DIR / "dump" / session.name
    target.mkdir(parents=True, exist_ok=True)
    count = 0
    for frame in frames_for(session, args, at, at + args.seconds):
        if at <= frame.time <= at + args.seconds:
            name = fmt(session.to_timeline(frame.time)).replace(":", "-")
            cv2.imwrite(str(target / f"{name}.png"), frame.image)
            count += 1
    print(f"Saved {count} ROI frames to {target}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Marks Battlefield badges on Steam recordings.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("sessions", help="list recordings and their timelines")

    scan = sub.add_parser("scan", help="find badges in a recording")
    scan.add_argument("session", nargs="?")
    scan.add_argument("--from", dest="from_", metavar="H:MM:SS")
    scan.add_argument("--to", metavar="H:MM:SS")
    scan.add_argument("--cpu", action="store_true", help="decode on the CPU instead of NVDEC")

    mark = sub.add_parser("mark", help="add highlight markers from the last scan")
    mark.add_argument("session", nargs="?")
    mark.add_argument("--write", action="store_true", help="actually change the timeline file")
    mark.add_argument("--force", action="store_true", help="write even while Steam is running")

    dump = sub.add_parser("dump", help="save ROI frames around a time, for templates")
    dump.add_argument("session", nargs="?")
    dump.add_argument("--at", required=True, metavar="H:MM:SS")
    dump.add_argument("--seconds", type=float, default=4.0)
    dump.add_argument("--cpu", action="store_true")

    args = parser.parse_args()
    {"sessions": cmd_sessions, "scan": cmd_scan, "mark": cmd_mark, "dump": cmd_dump}[args.command](args)


if __name__ == "__main__":
    main()
