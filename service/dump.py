"""Saving badge-area frames around a moment, for templates and debugging."""

from pathlib import Path

import cv2

import config
from recording.session import Session
from service.scan import frames_for
from service.timefmt import fmt


def dump_frames(session: Session, at: float, seconds: float, gpu: bool = True) -> tuple[Path, int]:
    """Saves ROI frames from timeline time `at` for `seconds`. Returns (folder, count)."""
    start = session.to_video(at)
    target = config.OUTPUT_DIR / "dump" / session.name
    target.mkdir(parents=True, exist_ok=True)
    count = 0
    for frame in frames_for(session, start, start + seconds, gpu):
        if start <= frame.time <= start + seconds:
            name = fmt(session.to_timeline(frame.time)).replace(":", "-")
            cv2.imwrite(str(target / f"{name}.png"), frame.image)
            count += 1
    return target, count
