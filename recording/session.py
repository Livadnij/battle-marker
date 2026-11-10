"""Pairs a Steam background-recording folder with its timeline file.

Steam names both after their start time, so the gap between the two names
is the offset between video time and timeline time. Timeline time is what
the Steam UI shows and what markers are stored in.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from recording.mpd import VideoTrack, read_video_track

VIDEO_DIR_RE = re.compile(r"bg_(\d+)_(\d{8})_(\d{6})")
TIMELINE_RE = re.compile(r"timeline_(\d+)(\d{8})_(\d{6})\.json")


@dataclass(frozen=True)
class Session:
    app_id: str
    video_dir: Path
    timeline_path: Path
    track: VideoTrack
    offset: float

    @property
    def name(self) -> str:
        return self.video_dir.name

    def chunk_numbers(self) -> list[int]:
        prefix = f"chunk-stream{self.track.representation_id}-"
        numbers = [
            int(p.stem.removeprefix(prefix))
            for p in self.video_dir.glob(f"{prefix}*.m4s")
        ]
        return sorted(numbers)

    def to_timeline(self, video_seconds: float) -> float:
        return video_seconds + self.offset

    def to_video(self, timeline_seconds: float) -> float:
        return timeline_seconds - self.offset


def _stamp(date: str, time: str) -> datetime:
    return datetime.strptime(date + time, "%Y%m%d%H%M%S")


def _timelines_by_app(timelines_dir: Path) -> dict[str, list[tuple[datetime, Path]]]:
    found: dict[str, list[tuple[datetime, Path]]] = {}
    for path in timelines_dir.glob("timeline_*.json"):
        match = TIMELINE_RE.fullmatch(path.name)
        if match:
            app_id, date, time = match.groups()
            found.setdefault(app_id, []).append((_stamp(date, time), path))
    for items in found.values():
        items.sort()
    return found


def find_sessions(recordings_root: Path) -> list[Session]:
    timelines = _timelines_by_app(recordings_root / "timelines")
    sessions = []
    for video_dir in sorted((recordings_root / "video").iterdir()):
        match = VIDEO_DIR_RE.fullmatch(video_dir.name)
        mpd = video_dir / "session.mpd"
        if not match or not mpd.exists():
            continue
        app_id, date, time = match.groups()
        video_start = _stamp(date, time)

        # The timeline that started last before this video folder owns it.
        owners = [(s, p) for s, p in timelines.get(app_id, []) if s <= video_start]
        if not owners:
            continue
        timeline_start, timeline_path = owners[-1]

        sessions.append(
            Session(
                app_id=app_id,
                video_dir=video_dir,
                timeline_path=timeline_path,
                track=read_video_track(mpd),
                offset=(video_start - timeline_start).total_seconds(),
            )
        )
    return sessions


def find_session(recordings_root: Path, name: str) -> Session:
    for session in find_sessions(recordings_root):
        if session.name == name:
            return session
    raise LookupError(f"No session folder named {name}")
