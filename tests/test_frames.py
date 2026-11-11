"""Detectors and OCR on real ROI frames cut from a Battlefield 6 recording.

The PNGs in tests/frames are 1516x780 crops, exactly what the scan hands to
the detectors. They come from bg_2807960_20261108_215340 at the video seconds
listed in FRAMES. Player names were blacked out, only in places no detector or
OCR box reads, and every score and OCR result was checked to be identical to the
original frame. Checks use score bands taken from the measurements in
config.py, not exact values, so a small change in a template does not break
them while a wrong detection does. OCR tests need Tesseract and skip without it.
"""

from functools import cache
from pathlib import Path

import cv2
import numpy as np
import pytest

import config
from detect import ocr
from detect.detector import BadgeDetector
from detect.life import LifeDetector
from events.life import DEATH, LifeTracker
from events.tracker import AppearanceTracker

FRAME_DIR = Path(__file__).parent / "frames"

# name -> what is on it, and the video second it was cut from
FRAMES = {
    "double_kill_kill": "DOUBLE KILL banner, KILL tag, 2317.4 s",
    "payback_kill": "PAYBACK banner, KILL tag, 2318.4 s",
    "headshot": "HEADSHOT tag, 1883.6 s",
    "row332_spawned_on": "SPAWNED ON tag with a player name and no icon, 2091.2 s",
    "row332_two_boxes": "SQUAD SUPPLY and EQUIPMENT DESTROYED side by side, 1951.6 s",
    "row274_equipment": "EQUIPMENT DESTROYED alone, no icon and no name, 1954.2 s",
    "downed_plain": "downed, plain heartbeat ring, 1686.0 s",
    "downed_revive_badge": "downed and being revived (dashed ring) with a tag, 1980.2 s",
    "deploy": "deploy screen, 1734.4 s",
    "alive_no_badge": "playing, nothing on the badge stack, 1739.0 s",
    "black": "all black frame between the scoreboard and deploy screen, 1733.2 s",
}

BADGE_FRAMES = ["double_kill_kill", "payback_kill", "headshot", "row332_spawned_on", "row332_two_boxes",
                "row274_equipment", "downed_revive_badge"]
NO_BADGE_FRAMES = ["downed_plain", "deploy", "alive_no_badge", "black"]
DOWNED_FRAMES = ["downed_plain", "downed_revive_badge"]
NOT_DOWNED_FRAMES = [n for n in FRAMES if n not in DOWNED_FRAMES]

TESSERACT = Path(config.DEFAULT_TESSERACT_CMD)
needs_tesseract = pytest.mark.skipif(not TESSERACT.exists(), reason=f"Tesseract not found at {TESSERACT}")


@cache
def frame(name: str) -> np.ndarray:
    image = cv2.imread(str(FRAME_DIR / f"{name}.png"))
    assert image is not None, f"missing frame {name}"
    assert image.shape == (config.ROI[3] - config.ROI[1], config.ROI[2] - config.ROI[0], 3)
    image.flags.writeable = False  # the detectors must not change what they are given
    return image


@cache
def badge_detector() -> BadgeDetector:
    return BadgeDetector(config.TEMPLATES_DIR, config.REGIONS, config.PRESENCE_THRESHOLD,
                         config.BANNER_THRESHOLD, config.HEADSHOT_THRESHOLD, config.READABLE_THRESHOLD)


@cache
def life_detector() -> LifeDetector:
    return LifeDetector(config.TEMPLATES_DIR, config.DOWNED_RING, config.DOWNED_THRESHOLD,
                        config.DEPLOY_REGION, config.DEPLOY_THRESHOLD)


def cues(name: str):
    return badge_detector().analyse(frame(name))


def tag_box(row: int) -> tuple[int, int, int, int]:
    left, top, right, bottom = config.TAG_TEXT_BOX
    shift = row - config.TAG_ROW_TOPS[0]
    return left, top + shift, right, bottom + shift


def test_every_frame_is_listed_and_every_listed_frame_exists():
    on_disk = {p.stem for p in FRAME_DIR.glob("*.png")}
    assert on_disk == set(FRAMES)


# ---- badge presence ---------------------------------------------------------

@pytest.mark.parametrize("name", BADGE_FRAMES)
def test_frames_with_a_badge_are_present_and_the_tag_is_readable(name):
    c = cues(name)
    assert c.present
    assert c.scores["tag_edge"] >= config.READABLE_THRESHOLD
    assert c.tag_readable


@pytest.mark.parametrize("name", NO_BADGE_FRAMES)
def test_frames_without_a_badge_stay_below_the_measured_ceiling(name):
    c = cues(name)
    assert not c.present
    assert c.scores["tag_edge"] < 0.55
    assert c.scores["score_zero"] < 0.55
    assert not c.tag_readable and not c.banner_readable and not c.headshot


def test_an_all_black_frame_gives_finite_scores_and_no_badge():
    # A flat frame has no structure to correlate. OpenCV gives finite scores for it here, so this
    # does not prove the NaN guard in the detector, it only pins that such a frame is no badge.
    c = cues("black")
    assert all(np.isfinite(s) for s in c.scores.values())
    assert not c.present


def test_the_detector_leaves_the_frame_alone():
    # frame() hands out a read-only array, so a write would raise.
    cues("double_kill_kill")


# ---- banner and headshot ----------------------------------------------------

@pytest.mark.parametrize("name", ["double_kill_kill", "payback_kill"])
def test_a_ribbon_banner_is_found_and_readable(name):
    c = cues(name)
    assert c.banner and c.banner_readable
    assert c.scores["banner_bars"] >= 0.9


@pytest.mark.parametrize("name", [n for n in BADGE_FRAMES if n not in ("double_kill_kill", "payback_kill")])
def test_frames_without_a_ribbon_have_no_banner(name):
    c = cues(name)
    assert not c.banner
    assert c.scores["banner_bars"] < 0.5


def test_the_headshot_box_is_found_on_the_headshot_frame_only():
    assert cues("headshot").headshot
    assert cues("headshot").scores["headshot_tag"] >= 0.9
    for name in FRAMES:
        if name != "headshot":
            assert not cues(name).headshot, name
            # A clear gap to the threshold, other tags score around 0.45 at most.
            assert cues(name).scores["headshot_tag"] < 0.6, name


# ---- tag row ----------------------------------------------------------------

@pytest.mark.parametrize("name, row", [
    ("double_kill_kill", 404), ("payback_kill", 404), ("headshot", 404),
    ("row332_spawned_on", 332), ("row332_two_boxes", 332),
    ("row274_equipment", 274), ("downed_revive_badge", 274),
])
def test_the_tag_edge_is_matched_at_the_measured_row(name, row):
    top = cues(name).tag_top
    assert abs(top - row) <= 3
    # What the tracker does with it, the nearest known row.
    assert min(config.TAG_ROW_TOPS, key=lambda r: abs(r - top)) == row


# ---- downed and deploy screens ----------------------------------------------

@pytest.mark.parametrize("name, at_least", [("downed_plain", 0.9), ("downed_revive_badge", 0.6)])
def test_downed_frames_are_found_with_a_clear_margin(name, at_least):
    cues_ = life_detector().analyse(frame(name))
    assert cues_.downed and not cues_.deploy
    assert cues_.ring >= at_least


@pytest.mark.parametrize("name", NOT_DOWNED_FRAMES)
def test_other_frames_are_not_downed(name):
    cues_ = life_detector().analyse(frame(name))
    assert not cues_.downed
    assert cues_.ring < 0.3  # nothing else went above 0.3 on a whole recording


def test_a_teammate_widget_saying_downed_is_not_the_downed_screen():
    # double_kill_kill shows a green "Downed" teammate entry, but no heartbeat ring.
    assert life_detector().analyse(frame("double_kill_kill")).ring < 0.1


def test_the_deploy_screen_is_found_and_the_ring_is_skipped_there():
    cues_ = life_detector().analyse(frame("deploy"))
    assert cues_.deploy and cues_.deploy_score >= 0.95
    assert cues_.ring == 0.0 and not cues_.downed


@pytest.mark.parametrize("name", [n for n in FRAMES if n != "deploy"])
def test_other_frames_are_not_the_deploy_screen(name):
    cues_ = life_detector().analyse(frame(name))
    assert not cues_.deploy
    assert cues_.deploy_score < 0.3


def test_a_roi_that_does_not_reach_the_ring_or_the_class_row_gives_no_cues():
    short = frame("downed_plain")[:650]
    cues_ = life_detector().analyse(short)
    assert not cues_.downed and not cues_.deploy


# ---- OCR --------------------------------------------------------------------

@needs_tesseract
@pytest.mark.parametrize("name, text", [("double_kill_kill", "DOUBLE KILL"), ("payback_kill", "PAYBACK")])
def test_banner_text_is_read(name, text):
    ocr.configure(str(TESSERACT))
    assert ocr.read_banner(frame(name), config.BANNER_TEXT_BOX) == text


@needs_tesseract
@pytest.mark.parametrize("name", ["headshot", "row332_spawned_on", "row274_equipment", "black", "alive_no_badge"])
def test_no_banner_is_read_where_there_is_none(name):
    ocr.configure(str(TESSERACT))
    assert ocr.read_banner(frame(name), config.BANNER_TEXT_BOX) == ""


@needs_tesseract
@pytest.mark.parametrize("name, row, text", [
    ("double_kill_kill", 404, "KILL"),
    ("payback_kill", 404, "KILL"),
    ("headshot", 404, "HEADSHOT"),
    ("row332_spawned_on", 332, "SPAWNED ON"),
    ("row332_two_boxes", 332, "SQUAD SUPPLY EQUIPMENT DESTROYED"),
    ("row274_equipment", 274, "EQUIPMENT DESTROYED"),
    ("downed_revive_badge", 274, "PROJECTILE DESTROYED X2"),
])
def test_tag_text_is_read_at_its_row(name, row, text):
    ocr.configure(str(TESSERACT))
    assert ocr.read_tag(frame(name), tag_box(row)) == text


@needs_tesseract
@pytest.mark.parametrize("name", ["black", "alive_no_badge", "deploy"])
def test_no_tag_is_read_where_there_is_none(name):
    ocr.configure(str(TESSERACT))
    assert ocr.read_tag(frame(name), config.TAG_TEXT_BOX) == ""


def sig_changed(a: str, b: str, box) -> bool:
    return ocr.changed(ocr.signature(frame(a), box), ocr.signature(frame(b), box), config.TEXT_CHANGE_THRESHOLD)


def test_the_text_signature_is_stable_for_the_same_frame():
    assert not sig_changed("double_kill_kill", "double_kill_kill", config.TAG_TEXT_BOX)
    assert ocr.changed(None, ocr.signature(frame("double_kill_kill"), config.TAG_TEXT_BOX), config.TEXT_CHANGE_THRESHOLD)


def test_a_tag_row_that_gains_a_box_counts_as_changed():
    # The measured mean differences are 35 and 18, against a threshold of 12.
    assert sig_changed("row332_spawned_on", "row332_two_boxes", tag_box(332))
    assert sig_changed("row274_equipment", "row332_two_boxes", tag_box(332))


def test_a_new_banner_counts_as_changed_and_a_repeat_of_the_same_one_does_not():
    # DOUBLE KILL to PAYBACK measures 14.4 against the threshold of 12, little room.
    assert sig_changed("double_kill_kill", "payback_kill", config.BANNER_TEXT_BOX)
    assert sig_changed("double_kill_kill", "black", config.BANNER_TEXT_BOX)
    assert not sig_changed("payback_kill", "payback_kill", config.BANNER_TEXT_BOX)


def test_the_same_kill_tag_on_two_different_scenes_does_not_count_as_changed():
    # Both frames show a KILL tag at the same place over a different background, as the tracker sees
    # when the scene moves behind a see-through box.
    assert not sig_changed("double_kill_kill", "payback_kill", config.TAG_TEXT_BOX)


# ---- real frames through the trackers ---------------------------------------

STEP = 0.2


def run_appearances(sequence: list[str]) -> list:
    """Each name is one frame, in order, at 5 frames per second."""
    ocr.configure(str(TESSERACT))
    tracker = AppearanceTracker(
        banner_box=config.BANNER_TEXT_BOX, tag_box=config.TAG_TEXT_BOX,
        confirm_samples=config.CONFIRM_SAMPLES, gap_tolerance=config.GAP_TOLERANCE,
        change_threshold=config.TEXT_CHANGE_THRESHOLD, confirm_reads=config.TEXT_CONFIRM_READS,
        tag_rows=config.TAG_ROW_TOPS,
    )
    for i, name in enumerate(sequence):
        tracker.update(round(i * STEP, 2), cues(name), frame(name))
    return tracker.finish()


@needs_tesseract
def test_a_double_kill_badge_comes_out_as_one_appearance_with_both_texts():
    (appearance,) = run_appearances(["black"] * 2 + ["double_kill_kill"] * 5 + ["black"] * 4)
    assert [(s.kind, s.label) for s in appearance.sightings] == [("banner", "DOUBLE KILL"), ("tag", "KILL")]
    assert appearance.start == 0.4


@needs_tesseract
def test_a_skull_less_tag_on_another_row_is_read_in_place():
    (appearance,) = run_appearances(["row332_spawned_on"] * 5 + ["black"] * 4)
    assert [(s.kind, s.label) for s in appearance.sightings] == [("tag", "SPAWNED ON")]


@needs_tesseract
def test_a_headshot_frame_gives_the_headshot_tag():
    (appearance,) = run_appearances(["headshot"] * 5 + ["black"] * 4)
    assert ("tag", "HEADSHOT") in [(s.kind, s.label) for s in appearance.sightings]


@needs_tesseract
def test_two_badges_with_a_gap_between_come_out_as_two_appearances():
    appearances = run_appearances(["double_kill_kill"] * 4 + ["black"] * 5 + ["payback_kill"] * 4 + ["black"] * 4)
    assert len(appearances) == 2
    assert ("banner", "PAYBACK") in [(s.kind, s.label) for s in appearances[1].sightings]


@needs_tesseract
def test_frames_without_badges_give_no_appearance():
    assert run_appearances(["alive_no_badge"] * 6 + ["deploy"] * 3 + ["downed_plain"] * 3) == []


def run_life(sequence: list[str], alive_known: bool = True):
    tracker = LifeTracker(confirm_samples=config.LIFE_CONFIRM_SAMPLES, gap_seconds=config.DOWNED_GAP_SECONDS,
                          death_wait_seconds=config.DEATH_WAIT_SECONDS, alive_known=alive_known)
    for i, name in enumerate(sequence):
        tracker.update(round(i * STEP, 2), life_detector().analyse(frame(name)), cues(name).present)
    return tracker.finish()


def test_a_down_followed_by_the_deploy_screen_is_a_death_at_the_down():
    sequence = ["alive_no_badge"] * 5 + ["downed_plain"] * 10 + ["black"] * 3 + ["deploy"] * 6 + ["alive_no_badge"] * 30
    (event,) = run_life(sequence)
    assert event.appearance.sightings[0].label == DEATH
    assert event.appearance.start == 1.0


def test_the_deploy_screen_alone_at_the_start_of_a_scan_is_no_death():
    assert run_life(["deploy"] * 6 + ["alive_no_badge"] * 30, alive_known=False) == []
