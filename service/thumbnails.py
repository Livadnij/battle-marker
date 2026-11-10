"""Small preview images of recordings, cached in output/thumbnails.

A preview is the first frame of the chunk in the middle of what is still on
disk. Only that one frame is decoded, on the CPU, so it takes about a second.
"""

import subprocess
import sys
from pathlib import Path

import config
from storage.settings import get_settings
from recording.session import Session

# Hides the console window ffmpeg would otherwise open when called from the UI.
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def thumbnail_path(session: Session) -> Path:
    return config.THUMBNAILS_DIR / f"{session.name}.jpg"


def make_thumbnail(session: Session) -> Path | None:
    """Returns the cached preview, creating it first if needed. None when there is no video."""
    path = thumbnail_path(session)
    if path.exists():
        return path
    chunks = session.chunk_numbers()
    if not chunks:
        return None
    middle = chunks[len(chunks) // 2]
    data = (session.video_dir / session.track.init_name).read_bytes()
    data += (session.video_dir / session.track.chunk_name(middle)).read_bytes()

    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        get_settings().ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "mp4", "-i", "pipe:0",
        "-frames:v", "1", "-vf", f"scale={config.THUMBNAIL_WIDTH}:-2",
        str(path),
    ]
    result = subprocess.run(cmd, input=data, capture_output=True, creationflags=_NO_WINDOW)
    if result.returncode != 0 or not path.exists():
        path.unlink(missing_ok=True)
        return None
    return path
