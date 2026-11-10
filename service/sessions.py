"""Which recordings exist and what state each one is in."""

from dataclasses import dataclass
from datetime import datetime

import config
from recording.apps import lookup_app_name
from recording.session import VIDEO_DIR_RE, Session, find_session, find_sessions
from recording.timeline import load_timeline
from service.errors import NoRecordingsError
from service.scan_log import is_scanned
from storage.app_names import get_app_name, put_app_name
from storage.settings import get_settings


@dataclass(frozen=True)
class SessionInfo:
    session: Session
    game: str
    supported: bool  # its badges can be recognised, see config.SUPPORTED_APPS
    started: datetime | None  # when the video folder was created
    covers_from: float | None  # timeline seconds of the first chunk still on disk
    covers_to: float | None  # timeline seconds where the last chunk ends
    timeline_entries: int
    scanned: bool

    @property
    def name(self) -> str:
        return self.session.name

    @property
    def length(self) -> float | None:
        """Seconds of video still on disk."""
        if self.covers_from is None:
            return None
        return self.covers_to - self.covers_from


_not_found: set[str] = set()  # app ids no lookup could name in this run


def game_name(app_id: str) -> str:
    if app_id in config.SUPPORTED_APPS:
        return config.SUPPORTED_APPS[app_id]
    name = get_app_name(app_id)
    if name is None and app_id not in _not_found:
        name = lookup_app_name(app_id, [get_settings().recordings_root.parent])
        if name:
            put_app_name(app_id, name)
        else:
            _not_found.add(app_id)
    return name or f"App {app_id}"


def describe(session: Session) -> SessionInfo:
    chunks = session.chunk_numbers()
    covers_from = covers_to = None
    if chunks:
        track = session.track
        covers_from = session.to_timeline(track.chunk_start(chunks[0]))
        covers_to = session.to_timeline(track.chunk_start(chunks[-1]) + track.segment_seconds)
    match = VIDEO_DIR_RE.fullmatch(session.name)
    started = datetime.strptime(match[2] + match[3], "%Y%m%d%H%M%S") if match else None
    return SessionInfo(
        session=session,
        game=game_name(session.app_id),
        supported=session.app_id in config.SUPPORTED_APPS,
        started=started,
        covers_from=covers_from,
        covers_to=covers_to,
        timeline_entries=len(load_timeline(session.timeline_path).entries),
        scanned=is_scanned(session),
    )


def list_sessions() -> list[SessionInfo]:
    return [describe(s) for s in find_sessions(get_settings().recordings_root)]


def get_session(name: str | None) -> Session:
    """The named recording, or the newest one that still has video when name is None."""
    if name:
        return find_session(get_settings().recordings_root, name)
    root = get_settings().recordings_root
    sessions = [s for s in find_sessions(root) if s.chunk_numbers()]
    if not sessions:
        raise NoRecordingsError(f"No recordings found under {root}")
    return max(sessions, key=lambda s: s.name.split("_", 2)[2])
