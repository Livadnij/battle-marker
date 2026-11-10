"""Marker rules: which badge text becomes a marker, and how it looks.

Rules are stored in the database (storage/rules.py). This module only knows
what a rule is, how it matches and what makes one invalid.
"""

from dataclasses import dataclass

from markers.icons import is_valid_icon

# "life" is a death, a down or a revive, see events/life.py. "any" means banner or tag.
SOURCES = ("banner", "tag", "life", "any")


@dataclass(frozen=True)
class Rule:
    name: str
    match: str
    source: str
    icon: str
    priority: int
    enabled: bool = True

    def matches(self, kind: str, label: str) -> bool:
        if not self.enabled:
            return False
        if self.source == "any" and kind not in ("banner", "tag"):
            return False
        if self.source != "any" and self.source != kind:
            return False
        return _normalise(self.match) in _normalise(label)


def _normalise(text: str) -> str:
    return " ".join(text.upper().split())


def rule_problems(rule: Rule) -> list[str]:
    """Readable reasons a rule can't be used. Empty when it is fine."""
    name = rule.name or rule.match or "A rule"
    problems = []
    if not rule.match.strip():
        problems.append(f"{name} has no match text.")
    if rule.source not in SOURCES:
        problems.append(f"{name} has source {rule.source!r}, expected one of {', '.join(SOURCES)}.")
    if not is_valid_icon(rule.icon):
        problems.append(f"{name} has the unknown icon {rule.icon!r}.")
    if rule.priority < 0:
        problems.append(f"{name} needs a priority of 0 or more.")
    return problems


def rules_from_json(data: dict) -> list[Rule]:
    """Rules from the old markers.json layout, used once when it is imported."""
    rules = []
    for item in data.get("markers", []):
        rules.append(Rule(
            name=item.get("name") or item.get("match", ""),
            match=item.get("match", ""),
            source=item.get("source", "any"),
            icon=item.get("icon", "steam_marker"),
            priority=int(item.get("priority", 0)),
            enabled=bool(item.get("enabled", True)),
        ))
    return rules


def find_rule(rules: list[Rule], kind: str, label: str) -> Rule | None:
    """The highest priority enabled rule that matches, or None."""
    hits = [r for r in rules if r.matches(kind, label)]
    return max(hits, key=lambda r: r.priority, default=None)
