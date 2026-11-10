"""Adds highlight markers to a Steam timeline file.

Steam keeps the timeline in memory while it runs and rewrites the file
when markers change, so writing while Steam is open can be lost or undone.
"""

import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from recording.timeline import Timeline, save_timeline

MARKER_DESCRIPTION = "battle-marker"
# Steam only draws a custom icon for "event" entries. A "usermarker" always
# shows the default marker icon, whatever its icon field says.
MARKER_TYPE = "event"


@dataclass
class PlannedMarker:
    timeline_seconds: float
    title: str
    icon: str
    priority: int


def steam_running() -> bool:
    if sys.platform != "win32":
        return False
    out = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq steam.exe", "/NH"],
        capture_output=True, text=True, check=False,
    ).stdout
    return "steam.exe" in out.lower()


def plan_markers(
    timeline: Timeline,
    candidates: list[PlannedMarker],
    dedup_seconds: float,
) -> tuple[list[PlannedMarker], list[PlannedMarker]]:
    """Splits candidates into (new, skipped because a marker is already close)."""
    existing = timeline.marker_times()
    end = timeline.end_seconds
    new, skipped = [], []
    for marker in candidates:
        if end is not None and not 0 <= marker.timeline_seconds <= end:
            skipped.append(marker)
        elif any(abs(marker.timeline_seconds - t) <= dedup_seconds for t in existing):
            skipped.append(marker)
        else:
            new.append(marker)
            existing.append(marker.timeline_seconds)
    return new, skipped


def backup(timeline: Timeline, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backup_dir / f"{timeline.path.stem}.{stamp}.json"
    shutil.copy2(timeline.path, target)
    return target


def apply_markers(timeline: Timeline, markers: list[PlannedMarker]) -> None:
    ids = [int(e["id"]) for e in timeline.entries if str(e.get("id", "")).isdigit()]
    next_id = max(ids, default=0) + 1
    for marker in markers:
        timeline.entries.append({
            "id": str(next_id),
            "time": str(round(marker.timeline_seconds * 1000)),
            "type": MARKER_TYPE,
            "icon": marker.icon,
            "priority": marker.priority,
            "title": marker.title,
            "description": MARKER_DESCRIPTION,
        })
        next_id += 1
    save_timeline(timeline)
