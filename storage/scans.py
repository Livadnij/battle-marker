"""Scan results in the database. One scans row per recording, its badges and their texts."""

from datetime import datetime

from events.tracker import Appearance, Sighting
from storage.db import connect


def is_scanned(session_name: str) -> bool:
    with connect() as con:
        return con.execute("SELECT 1 FROM scans WHERE session = ?", (session_name,)).fetchone() is not None


def load_appearances(session_name: str) -> list[Appearance] | None:
    """Badges of the last scan, oldest first. None when the recording was never scanned."""
    with connect() as con:
        if con.execute("SELECT 1 FROM scans WHERE session = ?", (session_name,)).fetchone() is None:
            return None
        badges = con.execute(
            "SELECT id, video_start, video_end FROM badges WHERE session = ? ORDER BY video_start", (session_name,)
        ).fetchall()
        sightings = con.execute(
            "SELECT s.badge_id, s.time, s.kind, s.label FROM sightings s "
            "JOIN badges b ON b.id = s.badge_id WHERE b.session = ? ORDER BY s.time, s.id",
            (session_name,),
        ).fetchall()
    by_badge: dict[int, list[Sighting]] = {}
    for row in sightings:
        by_badge.setdefault(row["badge_id"], []).append(Sighting(row["time"], row["kind"], row["label"]))
    return [Appearance(b["video_start"], b["video_end"], by_badge.get(b["id"], [])) for b in badges]


def save_appearances(
    session_name: str,
    timeline_name: str,
    offset: float,
    appearances: list[Appearance],
    ranges: list[tuple[float, float]],
) -> None:
    """Stores a scan that covered the given (first, last) video second ranges.

    Only badges inside those ranges are replaced, so rescanning one stretch
    keeps the rest of an earlier full scan. All ranges are cleared before
    anything is inserted, so a badge on the seam of two ranges is kept.
    """
    with connect() as con:
        con.execute(
            "INSERT INTO scans (session, timeline, time_offset, updated) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(session) DO UPDATE SET timeline = excluded.timeline, "
            "time_offset = excluded.time_offset, updated = excluded.updated",
            (session_name, timeline_name, offset, datetime.now().isoformat(timespec="seconds")),
        )
        con.executemany(
            "DELETE FROM badges WHERE session = ? AND NOT (video_end < ? OR video_start > ?)",
            [(session_name, first, last) for first, last in ranges],
        )
        for a in appearances:
            badge_id = con.execute(
                "INSERT INTO badges (session, video_start, video_end) VALUES (?, ?, ?)",
                (session_name, a.start, a.end),
            ).lastrowid
            con.executemany(
                "INSERT INTO sightings (badge_id, time, kind, label) VALUES (?, ?, ?, ?)",
                [(badge_id, s.time, s.kind, s.label) for s in a.sightings],
            )
