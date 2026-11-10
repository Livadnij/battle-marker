"""Picks the sightings that match a marker rule and merges close ones."""

from dataclasses import dataclass, field

from events.rules import Rule, find_rule
from events.tracker import Appearance


@dataclass
class Highlight:
    time: float  # video seconds, when the first matching badge appeared
    rules: list[Rule] = field(default_factory=list)

    @property
    def top(self) -> Rule:
        """The rule that decides the icon and Steam priority."""
        return max(self.rules, key=lambda r: r.priority)

    @property
    def title(self) -> str:
        return " + ".join(r.name for r in self.rules)


def build_highlights(
    appearances: list[Appearance],
    *,
    rules: list[Rule],
    merge_seconds: float,
) -> list[Highlight]:
    hits = []
    for appearance in appearances:
        for s in appearance.sightings:
            rule = find_rule(rules, s.kind, s.label)
            if rule is not None:
                hits.append((s.time, rule))
    hits.sort(key=lambda h: h[0])

    highlights: list[Highlight] = []
    last_time = None
    for time, rule in hits:
        if highlights and time - last_time <= merge_seconds:
            if rule not in highlights[-1].rules:
                highlights[-1].rules.append(rule)
        else:
            highlights.append(Highlight(time=time, rules=[rule]))
        last_time = time
    return highlights
