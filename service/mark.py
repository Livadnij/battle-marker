"""Turning a scan log into Steam timeline markers."""

from dataclasses import dataclass
from pathlib import Path

import config
from events.highlights import build_highlights
from markers.writer import (
    PlannedMarker, apply_markers, backup, plan_markers, steam_running,
)
from recording.session import Session
from recording.timeline import Timeline, load_timeline
from service.errors import NoScanError, SteamRunningError
from service.scan_log import load_scan
from storage.rules import list_rules
from storage.settings import get_settings


@dataclass
class MarkPlan:
    session: Session
    timeline: Timeline
    new: list[PlannedMarker]  # would be added
    skipped: list[PlannedMarker]  # an entry is already close, or outside the timeline


def plan_marks(session: Session) -> MarkPlan:
    appearances = load_scan(session)
    if appearances is None:
        raise NoScanError(f"No scan for {session.name}. Scan it first.")
    settings = get_settings()
    highlights = build_highlights(appearances, rules=list_rules())
    timeline = load_timeline(session.timeline_path)
    candidates = [
        PlannedMarker(
            session.to_timeline(h.time) - settings.lead_seconds,
            h.title, h.top.icon, h.top.priority,
        )
        for h in highlights
    ]
    new, skipped = plan_markers(timeline, candidates, settings.dedup_seconds)
    return MarkPlan(session, timeline, new, skipped)


def write_marks(
    plan: MarkPlan,
    markers: list[PlannedMarker] | None = None,
    force: bool = False,
) -> tuple[int, Path]:
    """Writes the plan's new markers, or the given subset of them.

    The timeline is read again right before writing, because Steam may have
    changed it since the plan was made. Returns (markers written, backup path).
    """
    if steam_running() and not force:
        raise SteamRunningError("Steam is running and may overwrite the timeline. Close Steam first.")
    timeline = load_timeline(plan.session.timeline_path)
    chosen = plan.new if markers is None else markers
    new, _ = plan_markers(timeline, chosen, get_settings().dedup_seconds)
    saved = backup(timeline, config.BACKUP_DIR)
    if new:
        apply_markers(timeline, new)
    return len(new), saved
