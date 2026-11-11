"""AppearanceTracker groups frames into badge appearances and confirms texts.

The OCR readers are replaced by scripted ones, so these tests are about the
grouping and confirming logic, not about Tesseract. Frames are blank, a text
box is made to look changed by painting bright pixels into it.
"""

import numpy as np
import pytest

import config
from detect.detector import NO_BADGE, Cues
from events.tracker import AppearanceTracker

STEP = 0.2
BLANK = np.zeros((800, 1100, 3), np.uint8)


def frame_with(*boxes: tuple[int, int, int, int]) -> np.ndarray:
    """A frame with bright pixels inside each given (left, top, right, bottom) area."""
    image = BLANK.copy()
    for left, top, right, bottom in boxes:
        image[top:bottom, left:right] = 255
    return image


BANNER_LIT = frame_with((100, 170, 800, 230))
TAG_LIT = frame_with((300, 420, 900, 460))


def cues(*, banner=True, tag=True, headshot=False, tag_top=404) -> Cues:
    return Cues(present=True, banner=banner, headshot=headshot, banner_readable=banner,
                tag_readable=tag, scores={}, tag_top=tag_top)


class Reader:
    """Returns scripted labels in order, then the last one forever, and remembers every call."""

    def __init__(self, *labels: str) -> None:
        self.labels = list(labels)
        self.calls: list[tuple[int, int, int, int]] = []

    def __call__(self, image, box) -> str:
        self.calls.append(box)
        return self.labels.pop(0) if len(self.labels) > 1 else (self.labels[0] if self.labels else "")


def make_tracker(banner: Reader | None = None, tag: Reader | None = None, **overrides) -> AppearanceTracker:
    options = dict(
        banner_box=config.BANNER_TEXT_BOX,
        tag_box=config.TAG_TEXT_BOX,
        confirm_samples=config.CONFIRM_SAMPLES,
        gap_tolerance=config.GAP_TOLERANCE,
        change_threshold=config.TEXT_CHANGE_THRESHOLD,
        confirm_reads=config.TEXT_CONFIRM_READS,
        banner_reader=banner or Reader(),
        tag_reader=tag or Reader(),
        tag_rows=config.TAG_ROW_TOPS,
    )
    options.update(overrides)
    return AppearanceTracker(**options)


def feed(tracker: AppearanceTracker, frames: list[Cues | None], image=BLANK, start: float = 0.0) -> float:
    """None stands for a frame without a badge."""
    time = start
    for c in frames:
        tracker.update(round(time, 2), NO_BADGE if c is None else c, image)
        time += STEP
    return round(time, 2)


def sightings(appearance) -> list[tuple[str, str]]:
    return [(s.kind, s.label) for s in appearance.sightings]


# ---- appearances ------------------------------------------------------------

def test_two_present_samples_start_an_appearance_at_the_first_of_them():
    tracker = make_tracker()
    feed(tracker, [None, cues(), cues(), cues(), None, None, None])
    (appearance,) = tracker.finished
    assert appearance.start == 0.2
    assert appearance.end == 0.6


def test_a_single_present_sample_is_no_appearance():
    tracker = make_tracker()
    feed(tracker, [None, cues(), None, None, None, None])
    assert tracker.finish() == []


def test_a_short_dropout_keeps_the_appearance_going():
    tracker = make_tracker()
    # Two misses are within the tolerance, so this is one appearance.
    feed(tracker, [cues(), cues(), None, None, cues(), cues(), None, None, None])
    (appearance,) = tracker.finished
    assert appearance.start == 0.0
    assert appearance.end == 1.0


def test_a_longer_dropout_ends_the_appearance_and_a_new_one_starts():
    tracker = make_tracker()
    feed(tracker, [cues(), cues(), None, None, None, cues(), cues(), None, None, None])
    assert [a.start for a in tracker.finished] == [0.0, 1.0]


def test_finish_closes_an_appearance_that_is_still_open():
    tracker = make_tracker()
    feed(tracker, [cues(), cues(), cues()])
    assert tracker.finished == []
    assert len(tracker.finish()) == 1


def test_finish_with_nothing_seen_returns_nothing():
    assert make_tracker().finish() == []


def test_confirm_samples_is_configurable():
    tracker = make_tracker(confirm_samples=3)
    feed(tracker, [cues(), cues(), None, None, None])
    assert tracker.finish() == []


# ---- text confirming --------------------------------------------------------

def test_text_counts_after_two_identical_reads_and_keeps_the_first_read_time():
    banner = Reader("DOUBLE KILL")
    tracker = make_tracker(banner=banner)
    feed(tracker, [cues(), cues(), cues(), cues(), None, None, None], image=BANNER_LIT)
    (appearance,) = tracker.finished
    (sighting,) = appearance.sightings
    assert (sighting.kind, sighting.label) == ("banner", "DOUBLE KILL")
    # Reads begin on the frame that confirmed the appearance, the second one.
    assert sighting.time == 0.2


def test_a_text_read_only_once_is_dropped():
    banner = Reader("GARBAGE", "KILL")
    tracker = make_tracker(banner=banner)
    feed(tracker, [cues(), cues(), cues(), cues(), None, None, None], image=BANNER_LIT)
    (appearance,) = tracker.finished
    assert sightings(appearance) == [("banner", "KILL")]


def test_a_settled_text_is_not_read_again_while_its_pixels_stay_the_same():
    banner = Reader("DOUBLE KILL")
    tracker = make_tracker(banner=banner)
    feed(tracker, [cues()] * 12, image=BANNER_LIT)
    assert len(banner.calls) == 2


def test_a_text_is_read_again_when_its_pixels_change():
    banner = Reader("DOUBLE KILL", "DOUBLE KILL", "GUNSLINGER", "GUNSLINGER")
    tracker = make_tracker(banner=banner)
    time = feed(tracker, [cues()] * 4, image=BANNER_LIT)
    other = frame_with((100, 170, 800, 200))  # less of the box is lit
    feed(tracker, [cues()] * 4, image=other, start=time)
    (appearance,) = tracker.finish()
    assert sightings(appearance) == [("banner", "DOUBLE KILL"), ("banner", "GUNSLINGER")]


def test_the_same_text_is_only_added_once_per_appearance():
    banner = Reader("KILL")
    tracker = make_tracker(banner=banner)
    time = feed(tracker, [cues()] * 4, image=BANNER_LIT)
    feed(tracker, [cues()] * 4, image=frame_with((100, 170, 800, 200)), start=time)
    (appearance,) = tracker.finish()
    assert sightings(appearance) == [("banner", "KILL")]


def test_an_empty_read_adds_nothing():
    banner = Reader("")
    tracker = make_tracker(banner=banner)
    feed(tracker, [cues()] * 6, image=BANNER_LIT)
    (appearance,) = tracker.finish()
    assert appearance.sightings == []


def test_text_is_not_read_when_neither_element_is_fully_drawn():
    banner, tag = Reader("KILL"), Reader("KILL")
    tracker = make_tracker(banner=banner, tag=tag)
    feed(tracker, [cues(banner=False, tag=False)] * 6)
    assert banner.calls == [] and tag.calls == []


def test_banner_is_tried_when_only_the_tag_is_readable():
    # Some ribbon icons make the bars template miss, the banner reader finds the box itself.
    banner, tag = Reader("TROOPER"), Reader("KILL")
    tracker = make_tracker(banner=banner, tag=tag)
    feed(tracker, [cues(banner=False, tag=True)] * 4, image=frame_with((100, 170, 800, 230), (300, 420, 900, 460)))
    (appearance,) = tracker.finish()
    assert set(sightings(appearance)) == {("banner", "TROOPER"), ("tag", "KILL")}


def test_tag_is_not_read_when_only_the_banner_is_readable():
    tag = Reader("KILL")
    tracker = make_tracker(banner=Reader("TROOPER"), tag=tag)
    feed(tracker, [cues(banner=True, tag=False)] * 4, image=BANNER_LIT)
    assert tag.calls == []


def test_sightings_are_ordered_by_time():
    banner, tag = Reader("DOUBLE KILL"), Reader("KILL")
    tracker = make_tracker(banner=banner, tag=tag)
    # The tag becomes readable two frames after the banner.
    time = feed(tracker, [cues(tag=False)] * 3, image=BANNER_LIT)
    feed(tracker, [cues()] * 4, image=frame_with((100, 170, 800, 230), (300, 420, 900, 460)), start=time)
    (appearance,) = tracker.finish()
    times = [s.time for s in appearance.sightings]
    assert times == sorted(times)
    assert sightings(appearance) == [("banner", "DOUBLE KILL"), ("tag", "KILL")]


def test_texts_are_read_afresh_in_the_next_appearance():
    banner = Reader("KILL")
    tracker = make_tracker(banner=banner)
    feed(tracker, [cues()] * 4 + [None] * 4 + [cues()] * 4, image=BANNER_LIT)
    first, second = tracker.finish()
    assert sightings(first) == sightings(second) == [("banner", "KILL")]


# ---- headshot ---------------------------------------------------------------

def test_headshot_cue_adds_a_headshot_tag_at_once_and_only_once():
    tracker = make_tracker()
    feed(tracker, [cues(banner=False, tag=False, headshot=True)] * 5)
    (appearance,) = tracker.finish()
    assert sightings(appearance) == [("tag", "HEADSHOT")]
    assert appearance.sightings[0].time == 0.2


# ---- tag row ----------------------------------------------------------------

@pytest.mark.parametrize("tag_top, row", [(404, 404), (410, 404), (332, 332), (330, 332), (274, 274), (200, 274)])
def test_tag_box_snaps_to_the_nearest_known_row(tag_top, row):
    tag = Reader("KILL")
    tracker = make_tracker(tag=tag)
    feed(tracker, [cues(tag_top=tag_top)] * 3, image=TAG_LIT)
    left, top, right, bottom = config.TAG_TEXT_BOX
    shift = row - config.TAG_ROW_TOPS[0]
    assert tag.calls[0] == (left, top + shift, right, bottom + shift)


def test_tag_box_stays_put_without_rows_configured():
    tag = Reader("KILL")
    tracker = make_tracker(tag=tag, tag_rows=())
    feed(tracker, [cues(tag_top=274)] * 3, image=TAG_LIT)
    assert tag.calls[0] == config.TAG_TEXT_BOX


def test_a_wobble_of_the_matched_row_does_not_cause_a_new_read():
    tag = Reader("KILL")
    tracker = make_tracker(tag=tag)
    frames = [cues(tag_top=top) for top in (404, 405, 403, 404, 405, 404, 403, 404)]
    feed(tracker, frames, image=TAG_LIT)
    assert len(tag.calls) == 2


# ---- parts ------------------------------------------------------------------

def test_settled_before_is_true_with_nothing_open():
    assert make_tracker().settled_before(10.0)


def test_settled_before_is_false_while_an_older_appearance_is_open():
    tracker = make_tracker()
    feed(tracker, [cues()] * 3)
    assert not tracker.settled_before(5.0)


@pytest.mark.xfail(strict=True, reason=(
    "The docstring says only badges that started before the time count, but any open "
    "appearance does, so a part keeps reading until the next part's first badge closes."
))
def test_settled_before_ignores_an_appearance_that_started_after_the_time():
    tracker = make_tracker()
    feed(tracker, [None] * 5 + [cues()] * 3)
    assert tracker.settled_before(0.5)


def test_settled_before_is_false_for_a_run_that_is_still_unconfirmed():
    tracker = make_tracker()
    feed(tracker, [cues()])
    assert not tracker.settled_before(5.0)


def test_settled_before_is_true_after_the_appearance_closed():
    tracker = make_tracker()
    feed(tracker, [cues()] * 3 + [None] * 4)
    assert tracker.settled_before(5.0)
