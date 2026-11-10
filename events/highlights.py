"""One marker per badge appearance, from the sightings a marker rule picks."""

from dataclasses import dataclass, field

from events.rules import Rule, find_rule
from events.tracker import Appearance


@dataclass
class Highlight:
    time: float  # video seconds, when the first matching text appeared
    rules: list[Rule] = field(default_factory=list)

    @property
    def top(self) -> Rule:
        """The rule that decides the icon and Steam priority."""
        return max(self.rules, key=lambda r: r.priority)

    @property
    def title(self) -> str:
        return " + ".join(r.name for r in self.rules)


def build_highlights(appearances: list[Appearance], *, rules: list[Rule]) -> list[Highlight]:
    """Each appearance with at least one matching sighting becomes one highlight.

    An appearance already holds everything shown on one badge, like KILL
    turning into DOUBLE KILL with a HEADSHOT tag, so separate badges are
    never merged.
    """
    highlights = []
    for appearance in sorted(appearances, key=lambda a: a.start):
        highlight = None
        for s in sorted(appearance.sightings, key=lambda s: s.time):
            rule = find_rule(rules, s.kind, s.label)
            if rule is None:
                continue
            if highlight is None:
                highlight = Highlight(time=s.time)
            if rule not in highlight.rules:
                highlight.rules.append(rule)
        if highlight is not None:
            highlights.append(highlight)
    return highlights
