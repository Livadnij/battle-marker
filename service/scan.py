"""Scanning a recording for badges.

The recording is split into parts that are scanned at the same time, each
with its own ffmpeg, detector and tracker, because one ffmpeg leaves most of
the GPU's video decoders idle. Progress goes out through a callback and
stopping comes in through another, so the CLI and a UI worker thread can
both drive the same function.

A badge can be on screen where two parts meet. Each part therefore starts
LEAD_CHUNKS early and keeps going past its end until the badge it is
following has closed. It keeps only the badges that started inside its own
stretch, so every badge is found once and whole, as in a single pass.
"""

import math
import threading
import time as clock
from collections.abc import Callable
from dataclasses import dataclass, field

import config
from decode.reader import chunk_range, read_frames
from detect import ocr
from detect.detector import BadgeDetector
from events.tracker import Appearance, AppearanceTracker
from recording.session import Session
from service.errors import NoFramesError, ResolutionError
from service.scan_log import save_scan
from storage.settings import get_settings

# Chunks decoded before a part's own stretch, so a badge already on screen
# there is seen from its start and left to the part before.
LEAD_CHUNKS = 2
# Furthest a part reads past its own stretch to finish a badge it is following.
TAIL_CHUNKS = 20
# Shorter recordings get fewer parts, starting ffmpeg costs more than it saves.
MIN_PART_CHUNKS = 20
# How long the parts get to stop after a crash or Ctrl+C before giving up on them.
STOP_WAIT_SECONDS = 10


@dataclass(frozen=True)
class ScanProgress:
    video_done: float  # seconds of video analysed so far, all parts together
    video_total: float  # seconds of video in the requested range
    badges: int  # appearances finished so far
    speed: float  # video seconds per wall-clock second
    parts: int  # parts scanned at the same time

    @property
    def fraction(self) -> float:
        return min(1.0, self.video_done / self.video_total) if self.video_total else 0.0


@dataclass
class ScanResult:
    appearances: list[Appearance]  # only the ones found by this scan
    video_seconds: float
    elapsed: float
    cancelled: bool
    parts: int
    part_timings: list[dict[str, tuple[float, int]]] = field(default_factory=list)  # name -> (seconds, calls)


class Stopwatch:
    """Adds up where scan time goes, so the slow stage is measured, not guessed."""

    def __init__(self) -> None:
        self.timings: dict[str, tuple[float, int]] = {}

    def add(self, name: str, seconds: float) -> None:
        total, calls = self.timings.get(name, (0.0, 0))
        self.timings[name] = (total + seconds, calls + 1)

    def wrap(self, name: str, fn):
        def timed(*args, **kwargs):
            began = clock.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                self.add(name, clock.perf_counter() - began)
        return timed


@dataclass
class _Part:
    chunks: list[int]  # decoded, lead-in and tail included
    own_start: float  # badges that start before this belong to the part before
    own_end: float  # badges that start here or later belong to the part after
    watch: Stopwatch = field(default_factory=Stopwatch)
    frames: int = 0  # frames analysed inside the part's own stretch
    first: float | None = None  # first and last frame time inside the own stretch
    last: float | None = None
    badges: int = 0
    appearances: list[Appearance] = field(default_factory=list)
    error: BaseException | None = None


def check_resolution(session: Session) -> None:
    size = (session.track.width, session.track.height)
    if size != config.SOURCE_SIZE:
        raise ResolutionError(
            f"{session.name} is {size[0]}x{size[1]}. Templates are cut for "
            f"{config.SOURCE_SIZE[0]}x{config.SOURCE_SIZE[1]} recordings."
        )


def frames_for(session: Session, start: float | None, end: float | None, gpu: bool):
    return read_frames(
        session,
        ffmpeg=get_settings().ffmpeg,
        roi=config.ROI,
        source_size=config.SOURCE_SIZE,
        fps=config.SAMPLE_FPS,
        gpu=gpu,
        start=start,
        end=end,
    )


def split_parts(session: Session, chunks: list[int], wanted: int) -> list[_Part]:
    """Splits the chunks into up to `wanted` stretches of about equal length."""
    count = max(1, min(wanted, len(chunks) // MIN_PART_CHUNKS))
    bounds = [round(i * len(chunks) / count) for i in range(count + 1)]
    parts = []
    for i in range(count):
        lo, hi = bounds[i], bounds[i + 1]
        first_part, last_part = i == 0, i == count - 1
        decode_from = lo if first_part else max(0, lo - LEAD_CHUNKS)
        decode_to = hi if last_part else hi + TAIL_CHUNKS
        parts.append(_Part(
            chunks=chunks[decode_from:decode_to],
            own_start=-math.inf if first_part else session.track.chunk_start(chunks[lo]),
            own_end=math.inf if last_part else session.track.chunk_start(chunks[hi]),
        ))
    return parts


def _new_tracker(watch: Stopwatch) -> AppearanceTracker:
    return AppearanceTracker(
        banner_box=config.BANNER_TEXT_BOX,
        tag_box=config.TAG_TEXT_BOX,
        confirm_samples=config.CONFIRM_SAMPLES,
        gap_tolerance=config.GAP_TOLERANCE,
        change_threshold=config.TEXT_CHANGE_THRESHOLD,
        confirm_reads=config.TEXT_CONFIRM_READS,
        banner_reader=watch.wrap("ocr", ocr.read_banner),
        tag_reader=watch.wrap("ocr", ocr.read_tag),
    )


def _new_detector() -> BadgeDetector:
    return BadgeDetector(
        config.TEMPLATES_DIR, config.REGIONS,
        config.PRESENCE_THRESHOLD, config.BANNER_THRESHOLD, config.HEADSHOT_THRESHOLD,
        config.READABLE_THRESHOLD,
    )


def _scan_part(session: Session, part: _Part, gpu: bool, stop: threading.Event) -> None:
    """Runs in its own thread. An error is kept on the part and stops the other parts."""
    try:
        watch = part.watch
        tracker = _new_tracker(watch)
        analyse = watch.wrap("templates", _new_detector().analyse)
        track = session.track
        stream = frames_for(session, track.chunk_start(part.chunks[0]),
                            track.chunk_start(part.chunks[-1]) + track.segment_seconds / 2, gpu)
        try:
            while not stop.is_set():
                waited = clock.perf_counter()
                frame = next(stream, None)
                watch.add("waiting for frames", clock.perf_counter() - waited)
                if frame is None:
                    break
                if frame.time >= part.own_end and tracker.settled_before(part.own_end):
                    break  # the tail only finishes badges that started inside
                tracker.update(frame.time, analyse(frame.image), frame.image)
                if part.own_start <= frame.time < part.own_end:
                    part.frames += 1
                    if part.first is None:
                        part.first = frame.time
                    part.last = frame.time
                part.badges = sum(1 for a in tracker.finished if part.own_start <= a.start < part.own_end)
        finally:
            stream.close()  # stops ffmpeg when the loop ended early
        part.appearances = [a for a in tracker.finish() if part.own_start <= a.start < part.own_end]
    except BaseException as e:
        part.error = e
        stop.set()


def scan_session(
    session: Session,
    *,
    start: float | None = None,
    end: float | None = None,
    gpu: bool = True,
    on_progress: Callable[[ScanProgress], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    progress_interval: float = 1.0,
) -> ScanResult:
    """Scans video seconds [start, end] of a recording and saves the scan log.

    A cancelled scan still saves what it found, which then covers only the
    stretches that were actually analysed.
    """
    check_resolution(session)
    ocr.configure(get_settings().tesseract_cmd)
    chunks = chunk_range(session, start, end)
    if not chunks:
        raise NoFramesError("No video in that range. Check the time range.")
    video_total = len(chunks) * session.track.segment_seconds

    parts = split_parts(session, chunks, get_settings().scan_parts)
    stop = threading.Event()
    threads = [
        threading.Thread(target=_scan_part, args=(session, p, gpu, stop), name=f"scan-part-{i}", daemon=True)
        for i, p in enumerate(parts)
    ]
    began = clock.perf_counter()
    cancelled = False
    next_report = began + progress_interval
    try:
        for t in threads:
            t.start()
        while alive := [t for t in threads if t.is_alive()]:
            alive[0].join(timeout=0.1)
            if should_stop is not None and not stop.is_set() and should_stop():
                cancelled = True
                stop.set()
            now = clock.perf_counter()
            if on_progress is not None and now >= next_report:
                done = sum(p.frames for p in parts) / config.SAMPLE_FPS
                on_progress(ScanProgress(
                    video_done=done,
                    video_total=video_total,
                    badges=sum(p.badges for p in parts),
                    speed=done / (now - began),
                    parts=len(parts),
                ))
                next_report = now + progress_interval
    finally:
        # Ctrl+C or an error in the progress callback lands here with parts
        # still running. Each part kills its ffmpeg once it sees the flag.
        stop.set()
        for t in threads:
            t.join(timeout=STOP_WAIT_SECONDS)

    failed = next((p.error for p in parts if p.error is not None), None)
    if failed is not None:
        raise failed

    frames = sum(p.frames for p in parts)
    timings = [p.watch.timings for p in parts]
    if frames == 0:
        if cancelled:
            return ScanResult([], 0.0, clock.perf_counter() - began, True, len(parts), timings)
        raise NoFramesError("No frames decoded. Check the time range and the ffmpeg setup.")

    appearances = sorted((a for p in parts for a in p.appearances), key=lambda a: a.start)
    save_scan(session, appearances, [(p.first, p.last) for p in parts if p.first is not None])
    return ScanResult(
        appearances=appearances,
        video_seconds=frames / config.SAMPLE_FPS,
        elapsed=clock.perf_counter() - began,
        cancelled=cancelled,
        parts=len(parts),
        part_timings=timings,
    )
