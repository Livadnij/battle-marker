"""Steam timeline JSON files. Times inside are milliseconds stored as strings."""

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Timeline:
    path: Path
    raw: dict = field(repr=False)

    @property
    def entries(self) -> list[dict]:
        entries = self.raw.setdefault("entries", [])
        # Steam writes an empty entry list as an empty object, "entries": {}.
        if isinstance(entries, dict):
            entries = list(entries.values())
            self.raw["entries"] = entries
        return entries

    @property
    def end_seconds(self) -> float | None:
        end = self.raw.get("endtime")
        return int(end) / 1000 if end is not None else None

    def marker_times(self) -> list[float]:
        return [int(e["time"]) / 1000 for e in self.entries if "time" in e]


def load_timeline(path: Path) -> Timeline:
    return Timeline(path=path, raw=json.loads(path.read_text(encoding="utf-8")))


def save_timeline(timeline: Timeline) -> None:
    text = json.dumps(timeline.raw, indent="\t", ensure_ascii=False)
    timeline.path.write_text(text + "\n", encoding="utf-8")
