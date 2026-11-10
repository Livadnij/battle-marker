"""Marker rules from markers.json: which badge text becomes a marker, and how it looks."""

import json
from dataclasses import dataclass
from pathlib import Path

from markers.icons import is_valid_icon

SOURCES = ("banner", "tag", "any")


@dataclass(frozen=True)
class Rule:
    name: str
    match: str
    source: str
    icon: str
    priority: int

    def matches(self, kind: str, label: str) -> bool:
        if self.source != "any" and self.source != kind:
            return False
        return _normalise(self.match) in _normalise(label)


def _normalise(text: str) -> str:
    return " ".join(text.upper().split())


def load_rules(path: Path) -> list[Rule]:
    if not path.exists():
        raise SystemExit(f"Missing {path}. It lists which badges become markers.")
    data = json.loads(path.read_text(encoding="utf-8"))
    rules, problems = [], []
    for i, item in enumerate(data.get("markers", []), start=1):
        if not item.get("enabled", True):
            continue
        name = item.get("name") or item.get("match") or f"rule {i}"
        source = item.get("source", "any")
        icon = item.get("icon", "steam_marker")
        priority = item.get("priority", 0)
        if not item.get("match"):
            problems.append(f"{name} has no match text")
        if source not in SOURCES:
            problems.append(f"{name} has source {source!r}, expected one of {', '.join(SOURCES)}")
        if not is_valid_icon(icon):
            problems.append(f"{name} has unknown icon {icon!r}, see the README for the list")
        if not isinstance(priority, int) or priority < 0:
            problems.append(f"{name} needs a priority of 0 or more")
        rules.append(Rule(name, item.get("match", ""), source, icon, priority))
    if problems:
        raise SystemExit("Problems in " + path.name + "\n  " + "\n  ".join(problems))
    return rules


def find_rule(rules: list[Rule], kind: str, label: str) -> Rule | None:
    """The highest priority rule that matches, or None."""
    hits = [r for r in rules if r.matches(kind, label)]
    return max(hits, key=lambda r: r.priority, default=None)
