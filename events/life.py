"""Turns downed and deploy screen cues into deaths, downs and revives.

A revive keeps the same life going, so a death is a down that ends on the
deploy screen. Whether a down ended in a revive is only known once the
deploy screen did not follow, so events come out with a delay but carry
the time they happened.

  DEATH    a down that ended on the deploy screen, at the moment you went
           down. Without a down first, like after an explosion, at the
           moment the deploy screen showed.
  DOWNED   a down that ended in a revive, at the moment you went down.
  REVIVED  the moment that down ended.

The deploy screen at the start of a match is no death. It only counts when
something showed you were alive since the last spawn, a badge or a down.

Each event is stored like a badge, an Appearance with one sighting of kind
"life", so rules, markers and the badge list treat it like any other.
"""

from dataclasses import dataclass

from detect.life import LifeCues
from events.tracker import Appearance, Sighting

KIND = "life"
DEATH = "DEATH"
DOWNED = "DOWNED"
REVIVED = "REVIVED"

_ALIVE, _DOWNED, _WAITING, _DEPLOY = "alive", "downed", "waiting", "deploy"


@dataclass
class LifeEvent:
    episode: float  # start of the down or deploy screen it belongs to, decides which scan part owns it
    appearance: Appearance


class LifeTracker:
    def __init__(
        self,
        *,
        confirm_samples: int,
        gap_seconds: float,
        death_wait_seconds: float,
        alive_known: bool,
    ) -> None:
        """alive_known says whether you count as alive before the first sample.

        False at the start of a scan, so an opening deploy screen is no death.
        True for a scan part that starts in the middle of a recording.
        """
        self.confirm_samples = confirm_samples
        self.gap_seconds = gap_seconds
        self.death_wait_seconds = death_wait_seconds
        self.events: list[LifeEvent] = []
        self._state = _ALIVE
        self._alive_seen = alive_known
        self._down_start: float | None = None
        self._down_last: float | None = None  # last sample that still showed the button
        self._deploy_last: float | None = None
        self._down_run: tuple[float, int] | None = None  # (first time, samples) of the current downed run
        self._deploy_run: tuple[float, int] | None = None

    def update(self, time: float, cues: LifeCues, badge_present: bool) -> None:
        self._down_run = self._extend(self._down_run, time, cues.downed)
        self._deploy_run = self._extend(self._deploy_run, time, cues.deploy)
        down_confirmed = self._confirmed(self._down_run)
        deploy_confirmed = self._confirmed(self._deploy_run)
        if badge_present:
            self._alive_seen = True

        if self._state == _DEPLOY:
            if cues.deploy:
                self._deploy_last = time
            elif time - self._deploy_last > self.gap_seconds:
                # Spawned. Nothing shows this life is a real one until a badge or a down.
                self._state = _ALIVE
                self._alive_seen = badge_present
            return

        if deploy_confirmed:
            if self._state in (_DOWNED, _WAITING):
                self._emit(self._down_start, DEATH, self._down_start, self._down_last)
            elif self._alive_seen:
                start = self._deploy_run[0]
                self._emit(start, DEATH, start, start)
            self._state = _DEPLOY
            self._deploy_last = time
            self._down_start = self._down_last = None
            return

        if self._state == _ALIVE:
            if down_confirmed:
                self._start_down(time)
        elif self._state == _DOWNED:
            if cues.downed:
                self._down_last = time
            elif time - self._down_last > self.gap_seconds:
                self._state = _WAITING
        elif self._state == _WAITING:
            if down_confirmed:
                # Going down again means the last down ended in a revive.
                self._emit_revive()
                self._start_down(time)
            elif time - self._down_last > self.death_wait_seconds:
                self._emit_revive()
                self._state = _ALIVE

    def settled_before(self, time: float) -> bool:
        """True when nothing that started before this time is still undecided."""
        if self._state in (_DOWNED, _WAITING) and self._down_start < time:
            return False
        for run in (self._down_run, self._deploy_run):
            if run is not None and run[0] < time and not self._confirmed(run):
                return False
        return True

    def finish(self) -> list[LifeEvent]:
        """Events so far. A down still undecided at the end is kept as a plain down."""
        if self._state in (_DOWNED, _WAITING):
            self._emit(self._down_start, DOWNED, self._down_start, self._down_last)
            self._state = _ALIVE
        return self.events

    # ---- helpers --------------------------------------------------------

    def _extend(self, run: tuple[float, int] | None, time: float, hit: bool) -> tuple[float, int] | None:
        if not hit:
            return None
        return (time, 1) if run is None else (run[0], run[1] + 1)

    def _confirmed(self, run: tuple[float, int] | None) -> bool:
        return run is not None and run[1] >= self.confirm_samples

    def _start_down(self, time: float) -> None:
        self._state = _DOWNED
        self._down_start = self._down_run[0]
        self._down_last = time
        self._alive_seen = True

    def _emit_revive(self) -> None:
        self._emit(self._down_start, DOWNED, self._down_start, self._down_last)
        self._emit(self._down_start, REVIVED, self._down_last, self._down_last)

    def _emit(self, episode: float, label: str, start: float, end: float) -> None:
        self.events.append(LifeEvent(episode, Appearance(start, end, [Sighting(start, KIND, label)])))
