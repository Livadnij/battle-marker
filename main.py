"""battle-marker CLI.

  uv run main.py sessions
  uv run main.py scan [SESSION] [--from H:MM:SS] [--to H:MM:SS] [--cpu]
  uv run main.py mark [SESSION] [--write] [--force]
  uv run main.py dump [SESSION] --at H:MM:SS [--seconds 4]

SESSION is a bg_* folder name and defaults to the newest one.
All times given or printed are timeline times, the ones Steam shows.
The work itself lives in service/, which the UI uses too.
"""

import argparse
import sys

from child_processes import contain_children
from service.dump import dump_frames
from service.errors import ServiceError
from service.mark import plan_marks, write_marks
from service.scan import ScanProgress, scan_session
from service.sessions import get_session, list_sessions
from storage.settings import get_settings
from service.timefmt import fmt, parse_time


def cmd_sessions(args: argparse.Namespace) -> None:
    for info in list_sessions():
        s = info.session
        span = "no chunks"
        if info.covers_from is not None:
            span = f"{fmt(info.covers_from)} to {fmt(info.covers_to)}"
        scanned = "scanned" if info.scanned else "not scanned"
        print(f"{s.name}  offset {s.offset:+.0f}s  {span}  {scanned}  "
              f"{s.timeline_path.name} ({info.timeline_entries} entries)")


def cmd_scan(args: argparse.Namespace) -> None:
    session = get_session(args.session)
    start = session.to_video(parse_time(args.from_)) if args.from_ else None
    end = session.to_video(parse_time(args.to)) if args.to else None

    def report(p: ScanProgress) -> None:
        print(f"  {p.fraction:4.0%}  {p.badges} badges  {p.speed:.1f}x realtime", flush=True)

    print(f"Scanning {session.name} (offset {session.offset:+.0f}s, "
          f"{'CPU' if args.cpu else 'GPU'} decode, up to {get_settings().scan_parts} parts at once)")
    result = scan_session(session, start=start, end=end, gpu=not args.cpu,
                          on_progress=report, progress_interval=30)

    print(f"Scanned {fmt(result.video_seconds)} of video in {fmt(result.elapsed)} "
          f"as {result.parts} parts. {len(result.appearances)} badges, saved to the database.")
    for index, timings in enumerate(result.part_timings, 1):
        spent = [f"{name} {sec:.1f}s ({calls} calls)" for name, (sec, calls) in timings.items()]
        print(f"  part {index} time spent: {', '.join(spent)}")
    for a in result.appearances:
        labels = ", ".join(f"{s.kind}:{s.label}" for s in a.sightings) or "(no text read)"
        print(f"  {fmt(session.to_timeline(a.start))}  {labels}")


def cmd_mark(args: argparse.Namespace) -> None:
    plan = plan_marks(get_session(args.session))
    print(f"{plan.session.name} -> {plan.timeline.path.name}")
    for m in plan.new:
        print(f"  add   {fmt(m.timeline_seconds)}  {m.icon:<16} {m.title}")
    for m in plan.skipped:
        print(f"  skip  {fmt(m.timeline_seconds)}  {m.icon:<16} {m.title}  (marker already close or out of range)")
    if not plan.new:
        print("Nothing to add.")
        return
    if not args.write:
        print("Dry run. Add --write to save these markers.")
        return
    written, saved = write_marks(plan, force=args.force)
    print(f"Wrote {written} markers. Backup in {saved}")


def cmd_dump(args: argparse.Namespace) -> None:
    session = get_session(args.session)
    target, count = dump_frames(session, parse_time(args.at), args.seconds, gpu=not args.cpu)
    print(f"Saved {count} ROI frames to {target}")


def main() -> None:
    contain_children()  # ffmpeg and Tesseract end with the CLI, even on Ctrl+C or a crash
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
    commands = {"sessions": cmd_sessions, "scan": cmd_scan, "mark": cmd_mark, "dump": cmd_dump}
    try:
        commands[args.command](args)
    except ServiceError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
