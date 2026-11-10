"""Turns per-frame cues into badge appearances and sightings.

An appearance is one continuous stretch of the badge stack being on screen.
A sighting is a confirmed piece of text inside it, like DOUBLE KILL or
HEADSHOT. One appearance can hold several sightings, because the game swaps
the banner while the stack stays visible.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from detect import ocr
from detect.detector import Box, Cues

Reader = Callable[[np.ndarray, Box], str]


@dataclass
class Sighting:
    time: float  # video seconds, first time the text was read
    kind: str  # "banner" or "tag"
    label: str


@dataclass
class Appearance:
    start: float
    end: float
    sightings: list[Sighting] = field(default_factory=list)

    def has(self, kind: str, label: str) -> bool:
        return any(s.kind == kind and s.label == label for s in self.sightings)


@dataclass
class _TextSlot:
    kind: str
    box: Box
    reader: Reader
    last_signature: np.ndarray | None = None
    settled: bool = False
    reads: dict[str, tuple[int, float]] = field(default_factory=dict)

    def reset(self) -> None:
        self.last_signature = None
        self.settled = False
        self.reads.clear()


class AppearanceTracker:
    def __init__(
        self,
        *,
        banner_box: Box,
        tag_box: Box,
        confirm_samples: int,
        gap_tolerance: int,
        change_threshold: float,
        confirm_reads: int,
        banner_reader: Reader = ocr.read_banner,
        tag_reader: Reader = ocr.read_tag,
        tag_rows: tuple[int, ...] = (),
    ) -> None:
        """tag_rows are the rows where the tag's right end matches, the first one for tag_box.

        Badges without an icon draw their tag higher, and the box moves to the
        row nearest the detector's match. Empty keeps the box where it is.
        """
        self.confirm_samples = confirm_samples
        self.gap_tolerance = gap_tolerance
        self.change_threshold = change_threshold
        self.confirm_reads = confirm_reads
        self.banner = _TextSlot("banner", banner_box, banner_reader)
        self.tag = _TextSlot("tag", tag_box, tag_reader)
        self.tag_box = tag_box
        self.tag_rows = tag_rows
        self.finished: list[Appearance] = []
        self._current: Appearance | None = None
        self._run_start: float | None = None
        self._run_length = 0
        self._misses = 0

    def update(self, time: float, cues: Cues, image: np.ndarray) -> None:
        if not cues.present:
            self._run_length = 0
            self._run_start = None
            if self._current is not None:
                self._misses += 1
                if self._misses > self.gap_tolerance:
                    self._close()
            return

        self._misses = 0
        if self._run_start is None:
            self._run_start = time
        self._run_length += 1

        if self._current is None:
            if self._run_length < self.confirm_samples:
                return
            self._current = Appearance(start=self._run_start, end=time)
        self._current.end = time

        # Ribbon icons differ, so the bars template misses some banners. The
        # banner reader finds the box by its position and returns nothing when
        # there is none, so it is tried whenever the stack is fully drawn.
        if cues.banner_readable or cues.tag_readable:
            self._read(self.banner, time, image)
        if cues.tag_readable:
            self.tag.box = self._tag_box_for(cues)
            self._read(self.tag, time, image)
        if cues.headshot:
            self._add(time, "tag", "HEADSHOT")

    def settled_before(self, time: float) -> bool:
        """True when no badge that started before this time is still being followed."""
        return self._current is None and (self._run_start is None or self._run_start >= time)

    def _tag_box_for(self, cues: Cues) -> Box:
        if not self.tag_rows or cues.tag_top is None:
            return self.tag_box
        row = min(self.tag_rows, key=lambda r: abs(r - cues.tag_top))
        shift = row - self.tag_rows[0]
        left, top, right, bottom = self.tag_box
        return left, top + shift, right, bottom + shift

    def finish(self) -> list[Appearance]:
        if self._current is not None:
            self._close()
        return self.finished

    def _read(self, slot: _TextSlot, time: float, image: np.ndarray) -> None:
        sig = ocr.signature(image, slot.box)
        if slot.settled and not ocr.changed(slot.last_signature, sig, self.change_threshold):
            return
        slot.last_signature = sig
        label = slot.reader(image, slot.box)
        if not label:
            slot.settled = False
            return
        count, first = slot.reads.get(label, (0, time))
        count += 1
        slot.reads[label] = (count, first)
        if count == self.confirm_reads:
            self._add(first, slot.kind, label)
        slot.settled = count >= self.confirm_reads

    def _add(self, time: float, kind: str, label: str) -> None:
        if not self._current.has(kind, label):
            self._current.sightings.append(Sighting(time, kind, label))
            self._current.sightings.sort(key=lambda s: s.time)

    def _close(self) -> None:
        self.finished.append(self._current)
        self._current = None
        self._misses = 0
        self.banner.reset()
        self.tag.reset()
