"""Small still images for the timeline hover preview.

One image per chunk, taken from the keyframe each chunk starts with. That is
the only frame that can be decoded without the frames before it, so it is
fast, and with 3 second chunks it is as fine-grained as Steam's own preview.
"""

import math
import subprocess
import sys

from storage.settings import get_settings
from recording.session import Session

PREVIEW_WIDTH = 320
PREVIEW_HEIGHT = 180

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def chunk_at(session: Session, timeline_seconds: float) -> int | None:
    """The chunk on disk that holds a timeline time, or None when it was deleted."""
    video_seconds = session.to_video(timeline_seconds)
    number = math.floor(video_seconds / session.track.segment_seconds) + 1
    path = session.video_dir / session.track.chunk_name(number)
    return number if path.exists() else None


def keyframe_rgb(session: Session, chunk: int) -> bytes | None:
    """The chunk's first frame as RGB24 bytes, PREVIEW_WIDTH x PREVIEW_HEIGHT. None on failure."""
    try:
        data = (session.video_dir / session.track.init_name).read_bytes()
        data += (session.video_dir / session.track.chunk_name(chunk)).read_bytes()
    except OSError:
        return None  # Steam deleted the chunk in the meantime
    cmd = [
        get_settings().ffmpeg, "-hide_banner", "-loglevel", "error",
        "-skip_frame", "nokey", "-f", "mp4", "-i", "pipe:0",
        "-frames:v", "1", "-vf", f"scale={PREVIEW_WIDTH}:{PREVIEW_HEIGHT}",
        "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1",
    ]
    result = subprocess.run(cmd, input=data, capture_output=True, creationflags=_NO_WINDOW)
    expected = PREVIEW_WIDTH * PREVIEW_HEIGHT * 3
    if result.returncode != 0 or len(result.stdout) < expected:
        return None
    return result.stdout[:expected]
