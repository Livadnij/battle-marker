"""Every badge a scan found, whether or not a marker rule picks it."""

from dataclasses import dataclass

from events.rules import Rule, find_rule
from recording.session import Session
from recording.timeline import load_timeline
from service.scan_log import load_scan
from storage.rules import list_rules
from storage.settings import get_settings


@dataclass(frozen=True)
class Badge:
    time: float  # timeline time the badge appeared
    labels: list[str]  # texts read from it, in the order they appeared
    rule: Rule | None  # the highest priority rule that matches, None when no rule does
    in_timeline: bool  # a timeline entry already sits this close

    @property
    def title(self) -> str:
        return " + ".join(self.labels) if self.labels else "Badge, no text read"

    @property
    def selected(self) -> bool:
        """True when a rule turns this badge into a marker."""
        return self.rule is not None


def list_badges(session: Session) -> list[Badge] | None:
    """All badges of the last scan, oldest first. None when the recording was never scanned."""
    appearances = load_scan(session)
    if appearances is None:
        return None
    rules = list_rules()
    dedup = get_settings().dedup_seconds
    entry_times = load_timeline(session.timeline_path).marker_times()

    badges = []
    for appearance in appearances:
        matched = [(s, find_rule(rules, s.kind, s.label)) for s in appearance.sightings]
        hits = [(s, r) for s, r in matched if r is not None]
        top = max((r for _, r in hits), key=lambda r: r.priority, default=None)
        # A marker goes where the first matching text appeared, as in build_highlights.
        video_time = hits[0][0].time if hits else appearance.start
        time = session.to_timeline(video_time)
        badges.append(Badge(
            time=time,
            labels=[s.label for s in appearance.sightings],
            rule=top,
            in_timeline=any(abs(time - t) <= dedup for t in entry_times),
        ))
    return badges


def next_badge_index(times: list[float], position: float) -> int:
    """Index of the first badge that has not been reached at this timeline position.

    The badge list follows the scan order, and a badge is placed where its first
    matching text appeared, so neighbours can be a little out of time order.
    Taking the first badge in list order that is still ahead keeps the playhead
    from jumping around when that happens. A badge exactly at the position counts
    as reached. The result is len(times) when every badge is behind.
    """
    return next((i for i, t in enumerate(times) if t > position), len(times))
