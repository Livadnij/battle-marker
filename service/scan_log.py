"""Scan results of a recording. Stored in the database, see storage/scans.py."""

from events.tracker import Appearance
from recording.session import Session
from storage import scans


def is_scanned(session: Session) -> bool:
    return scans.is_scanned(session.name)


def load_scan(session: Session) -> list[Appearance] | None:
    """Appearances from the last scan, or None when the recording was never scanned."""
    return scans.load_appearances(session.name)


def save_scan(session: Session, appearances: list[Appearance], ranges: list[tuple[float, float]]) -> None:
    """Stores a scan of the given video second ranges, replacing only badges inside them."""
    scans.save_appearances(session.name, session.timeline_path.name, session.offset,
                           appearances, ranges)
