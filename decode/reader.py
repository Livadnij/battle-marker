"""Streams cropped, down-sampled frames out of a Steam recording.

The init segment and the chunks are fed into ffmpeg's stdin as one
fragmented MP4, so no merged file is ever written to disk. With the GPU
path the crop happens inside NVDEC and only the badge region is copied
back to system memory.
"""

import math
import queue
import subprocess
import tempfile
import threading
from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np

import child_processes
from recording.session import Session

# Decoded frames buffered ahead of the caller. One ROI frame is about 2 MB.
QUEUE_FRAMES = 64
_DONE = object()

CUVID_DECODERS = {"hev1": "hevc_cuvid", "hvc1": "hevc_cuvid", "avc1": "h264_cuvid", "av01": "av1_cuvid"}


@dataclass(frozen=True)
class Frame:
    time: float  # video seconds, same clock as the chunk numbers
    image: np.ndarray  # BGR, ROI only


def _crop_size(roi: tuple[int, int, int, int]) -> tuple[int, int]:
    left, top, right, bottom = roi
    return right - left, bottom - top


def build_command(
    ffmpeg: str,
    codec: str,
    roi: tuple[int, int, int, int],
    source_size: tuple[int, int],
    fps: float,
    gpu: bool,
) -> list[str]:
    left, top, right, bottom = roi
    width, height = _crop_size(roi)
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "mp4"]
    if gpu:
        decoder = CUVID_DECODERS.get(codec.split(".")[0])
        if decoder is None:
            raise ValueError(f"No NVDEC decoder known for codec {codec}")
        crop = f"{top}x{source_size[1] - bottom}x{left}x{source_size[0] - right}"
        cmd += ["-c:v", decoder, "-crop", crop, "-i", "pipe:0", "-vf", f"fps={fps}"]
    else:
        cmd += ["-i", "pipe:0", "-vf", f"fps={fps},crop={width}:{height}:{left}:{top}"]
    cmd += ["-an", "-pix_fmt", "bgr24", "-f", "rawvideo", "pipe:1"]
    return cmd


def chunk_range(session: Session, start: float | None, end: float | None) -> list[int]:
    """Chunk numbers covering video seconds [start, end]."""
    available = session.chunk_numbers()
    if not available:
        return []
    seg = session.track.segment_seconds
    first = available[0] if start is None else max(available[0], math.floor(start / seg) + 1)
    last = available[-1] if end is None else min(available[-1], math.floor(end / seg) + 1)
    return [n for n in available if first <= n <= last]


def _pump(stdout, frame_bytes: int, frames: queue.Queue) -> None:
    try:
        while True:
            buf = stdout.read(frame_bytes)
            if len(buf) < frame_bytes:
                break
            frames.put(buf)
    except (OSError, ValueError):
        pass  # pipe closed while shutting down
    finally:
        frames.put(_DONE)


def _feed(session: Session, chunks: list[int], stdin) -> None:
    try:
        stdin.write((session.video_dir / session.track.init_name).read_bytes())
        for number in chunks:
            stdin.write((session.video_dir / session.track.chunk_name(number)).read_bytes())
    except (BrokenPipeError, OSError):
        pass  # ffmpeg stopped early, the reader reports why
    finally:
        try:
            stdin.close()
        except OSError:
            pass


def contiguous_runs(numbers: list[int]) -> list[list[int]]:
    runs: list[list[int]] = []
    for n in numbers:
        if runs and n == runs[-1][-1] + 1:
            runs[-1].append(n)
        else:
            runs.append([n])
    return runs


def read_frames(
    session: Session,
    *,
    ffmpeg: str,
    roi: tuple[int, int, int, int],
    source_size: tuple[int, int],
    fps: float,
    gpu: bool,
    start: float | None = None,
    end: float | None = None,
) -> Iterator[Frame]:
    # Frame times are counted from the first chunk of a run, so a missing
    # chunk starts a new ffmpeg run instead of shifting every later time.
    for run in contiguous_runs(chunk_range(session, start, end)):
        yield from _read_run(session, run, ffmpeg, roi, source_size, fps, gpu)


def _read_run(
    session: Session,
    chunks: list[int],
    ffmpeg: str,
    roi: tuple[int, int, int, int],
    source_size: tuple[int, int],
    fps: float,
    gpu: bool,
) -> Iterator[Frame]:
    width, height = _crop_size(roi)
    frame_bytes = width * height * 3
    t0 = session.track.chunk_start(chunks[0])
    cmd = build_command(ffmpeg, session.track.codec, roi, source_size, fps, gpu)

    with tempfile.TemporaryFile() as errors:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors,
                                creationflags=child_processes.NO_WINDOW)
        child_processes.track(proc)
        feeder = threading.Thread(target=_feed, args=(session, chunks, proc.stdin), daemon=True)
        feeder.start()
        # The pump keeps ffmpeg's output drained while the caller is busy
        # with OCR, so the decoder never stalls on a full pipe.
        frames: queue.Queue = queue.Queue(maxsize=QUEUE_FRAMES)
        pump = threading.Thread(target=_pump, args=(proc.stdout, frame_bytes, frames), daemon=True)
        pump.start()
        index = 0
        buf = None
        try:
            while (buf := frames.get()) is not _DONE:
                image = np.frombuffer(buf, np.uint8).reshape(height, width, 3)
                yield Frame(time=t0 + index / fps, image=image)
                index += 1
        finally:
            if proc.poll() is None:
                proc.kill()
            # Unblock the pump if the caller stopped early with a full queue.
            if buf is not _DONE:
                while frames.get() is not _DONE:
                    pass
            pump.join(timeout=5)
            proc.stdout.close()
            proc.wait()
            child_processes.untrack(proc)
            feeder.join(timeout=5)
        if proc.returncode not in (0, None) and index == 0:
            errors.seek(0)
            message = errors.read().decode(errors="replace").strip()
            raise RuntimeError(f"ffmpeg failed ({proc.returncode}): {message}")
