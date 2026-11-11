"""scan_session end to end, with a scripted frame stream instead of ffmpeg.

The fake stream hands out frames the way decode/reader.py does, at 5 per
second from the start of the first chunk of each run, so a part that starts
in the middle of a recording sees the same frame times as a single pass.
Most tests replace the detectors and OCR with stubs that read a code from the
first pixel of each frame. That keeps a full scan fast and puts the focus on
how parts, seams, cancelling and saving behave. One test at the end runs the
real detectors on the real frames from tests/frames.
"""

import threading
import time as clock
from pathlib import Path

import cv2
import numpy as np
import pytest

import config
from decode.reader import Frame, chunk_range, contiguous_runs
from detect import ocr
from detect.detector import NO_BADGE, Cues
from detect.life import LifeCues
from events.tracker import Appearance, Sighting
from recording.mpd import VideoTrack
from recording.session import Session
from service import scan
from service.errors import NoFramesError, ResolutionError
from service.scan import ScanProgress, scan_session
from service.scan_log import is_scanned, load_scan, save_scan
from storage.settings import Settings, save_settings

FPS = config.SAMPLE_FPS
SEGMENT = 3.0
ROI_HEIGHT = config.ROI[3] - config.ROI[1]
ROI_WIDTH = config.ROI[2] - config.ROI[0]

# ---- the scripted recording, in video seconds -------------------------------

# The badge at 88 seconds sits on the seam between the first two of three parts.
BADGES = [(20.0, 23.0), (88.0, 93.0), (215.0, 218.0), (262.0, 269.0)]
DOWNS = [(100.0, 105.0), (178.0, 184.0)]  # the first is revived, the second ends on the deploy screen
DEPLOYS = [(0.0, 6.0), (190.0, 196.0)]  # the first is the match start, no death
CHUNKS = 90  # 270 seconds, three parts of 90 seconds with seams at 90 and 180

NONE, DOWN, DEPLOY, BADGE_BASE = 0, 1, 2, 10


def code_at(t: float) -> int:
    t = round(t, 3)
    if any(a <= t < b for a, b in DEPLOYS):
        return DEPLOY
    if any(a <= t < b for a, b in DOWNS):
        return DOWN
    for i, (a, b) in enumerate(BADGES):
        if a <= t < b:
            return BADGE_BASE + i
    return NONE


_images: dict[int, np.ndarray] = {}


def image_for_code(code: int) -> np.ndarray:
    if code not in _images:
        image = np.zeros((ROI_HEIGHT, ROI_WIDTH, 3), np.uint8)
        image[0, 0, 0] = code  # the one pixel outside every box the trackers look at
        _images[code] = image
    return _images[code]


def code_of(image: np.ndarray) -> int:
    return int(image[0, 0, 0])


class StubBadges:
    def analyse(self, image):
        if code_of(image) < BADGE_BASE:
            return NO_BADGE
        return Cues(present=True, banner=True, headshot=False, banner_readable=True,
                    tag_readable=True, scores={}, tag_top=config.TAG_ROW_TOPS[0])


class StubLife:
    def analyse(self, image):
        code = code_of(image)
        return LifeCues(downed=code == DOWN, deploy=code == DEPLOY, ring=0.0, deploy_score=0.0)


def stub_banner(image, box) -> str:
    code = code_of(image)
    return f"BANNER {code - BADGE_BASE}" if code >= BADGE_BASE else ""


def stub_tag(image, box) -> str:
    code = code_of(image)
    return f"TAG {code - BADGE_BASE}" if code >= BADGE_BASE else ""


# ---- the fake decoder -------------------------------------------------------

class World:
    """Stands in for scan.frames_for. It also records what the scan did with its streams."""

    def __init__(self, *, image_for=None, pause=0.0, block_after=None, fail_from=None, fail_after=0, empty=False):
        self.image_for = image_for or (lambda t: image_for_code(code_at(t)))
        self.pause = pause  # seconds per frame, keeps a scan running long enough for callbacks
        self.block_after = block_after  # frames a stream gives before it waits to be released
        self.fail_from = fail_from  # streams that start at or after this video second fail
        self.fail_after = fail_after  # after this many frames
        self.empty = empty
        self.release = threading.Event()
        self.lock = threading.Lock()
        self.frames: dict[float, int] = {}  # frames handed out, by the video second the stream started at
        self.closed = 0
        self.gpu_flags: list[bool] = []

    @property
    def started(self) -> int:
        return len(self.frames)

    def frames_for(self, session, start, end, gpu):
        return self._stream(session, start, end, gpu)

    def _stream(self, session, start, end, gpu):
        key = session.track.chunk_start(chunk_range(session, start, end)[0])
        with self.lock:
            self.frames[key] = 0
            self.gpu_flags.append(gpu)
        try:
            if self.empty:
                self._wait_if_blocked(key)
                return
            for run in contiguous_runs(chunk_range(session, start, end)):
                t0 = session.track.chunk_start(run[0])
                for i in range(round(len(run) * session.track.segment_seconds * FPS)):
                    if self.pause:
                        clock.sleep(self.pause)
                    self._wait_if_blocked(key)
                    if self.fail_from is not None and key >= self.fail_from and self.frames[key] >= self.fail_after:
                        raise RuntimeError("boom")
                    t = t0 + i / FPS
                    with self.lock:
                        self.frames[key] += 1
                    yield Frame(time=t, image=self.image_for(t))
        finally:
            with self.lock:
                self.closed += 1

    def _wait_if_blocked(self, key: float) -> None:
        if self.block_after is None or self.frames[key] < self.block_after:
            return
        deadline = clock.monotonic() + 10
        while not self.release.is_set() and clock.monotonic() < deadline:
            clock.sleep(0.005)


def make_session(tmp_path: Path, chunk_count: int, size=(3840, 2160)) -> Session:
    video = tmp_path / "bg_2807960_20261108_215340"
    video.mkdir(exist_ok=True)
    for n in range(1, chunk_count + 1):
        (video / f"chunk-stream0-{n:05d}.m4s").write_bytes(b"")
    track = VideoTrack("0", size[0], size[1], "hvc1.1.6.L153.B0", "init-stream0.m4s",
                       SEGMENT, 1, 0.0, SEGMENT * chunk_count)
    return Session("2807960", video, tmp_path / "timeline_x.json", track, 23.0)


@pytest.fixture
def stubbed(monkeypatch, tmp_path):
    """Builds a session and a World, with stub detectors and OCR."""

    def build(chunk_count: int = CHUNKS, **world_options):
        world = World(**world_options)
        monkeypatch.setattr(scan, "frames_for", world.frames_for)
        monkeypatch.setattr(scan, "_new_detector", lambda: StubBadges())
        monkeypatch.setattr(scan, "_new_life_detector", lambda: StubLife())
        monkeypatch.setattr(ocr, "read_banner", stub_banner)
        monkeypatch.setattr(ocr, "read_tag", stub_tag)
        return make_session(tmp_path, chunk_count), world

    return build


def use_parts(count: int) -> None:
    save_settings(Settings(scan_parts=count))


def shape(appearances: list[Appearance]) -> list[tuple]:
    return [(round(a.start, 1), round(a.end, 1), tuple((s.kind, s.label, round(s.time, 1)) for s in a.sightings))
            for a in appearances]


def badge(i: int, start: float, end: float, first_read: float) -> tuple:
    return start, end, (("banner", f"BANNER {i}", first_read), ("tag", f"TAG {i}", first_read))


# What a single pass over the scripted recording finds, worked out from the script.
# A badge counts after 2 samples and its text after 2 reads, so the text is first read on the second frame.
EXPECTED = [
    badge(0, 20.0, 22.8, 20.2),
    badge(1, 88.0, 92.8, 88.2),
    (100.0, 104.8, (("life", "DOWNED", 100.0),)),
    (104.8, 104.8, (("life", "REVIVED", 104.8),)),
    (178.0, 183.8, (("life", "DEATH", 178.0),)),
    badge(2, 215.0, 217.8, 215.2),
    badge(3, 262.0, 268.8, 262.2),
]


# ---- one pass and many parts find the same things ---------------------------

def test_a_single_pass_finds_what_the_script_holds(stubbed):
    session, world = stubbed()
    use_parts(1)
    result = scan_session(session)
    assert result.parts == 1
    assert shape(result.appearances) == EXPECTED


@pytest.mark.parametrize("parts", [2, 3, 4])
def test_any_number_of_parts_finds_the_same_as_a_single_pass(stubbed, parts):
    session, world = stubbed()
    use_parts(parts)
    result = scan_session(session)
    assert result.parts == parts
    assert shape(result.appearances) == EXPECTED


def test_a_badge_on_the_seam_is_found_once_and_whole(stubbed):
    session, world = stubbed()
    use_parts(3)
    result = scan_session(session)
    seam = [a for a in result.appearances if a.start == 88.0]
    assert len(seam) == 1
    assert round(seam[0].end, 1) == 92.8  # it ends after the seam at 90 seconds
    assert [s.label for s in seam[0].sightings] == ["BANNER 1", "TAG 1"]


def test_a_down_on_the_seam_is_one_death_at_the_down(stubbed):
    session, world = stubbed()
    use_parts(3)
    result = scan_session(session)
    deaths = [a for a in result.appearances if a.sightings[0].label == "DEATH"]
    assert [round(a.start, 1) for a in deaths] == [178.0]  # the down starts before the seam at 180


def test_a_part_that_starts_mid_recording_counts_a_lone_deploy_screen_as_a_death(stubbed):
    # Only a deploy screen at 130 s, with nothing before it that shows the player alive.
    # A single pass takes it for the match start. A part that begins at 120 s assumes the player was
    # alive before it, as scan.py documents, so the same screen becomes a death there. That is the price
    # of scanning in parts, and it only matters when the match start falls inside a later part.
    lone = lambda t: image_for_code(DEPLOY if 130.0 <= t < 136.0 else NONE)
    session, world = stubbed(chunk_count=60, image_for=lone)
    use_parts(1)
    assert scan_session(session).appearances == []
    use_parts(3)
    assert shape(scan_session(session).appearances) == [(130.0, 130.0, (("life", "DEATH", 130.0),))]


def test_the_deploy_screen_at_the_start_is_no_death(stubbed):
    session, world = stubbed()
    use_parts(3)
    result = scan_session(session)
    assert not [a for a in result.appearances if a.start < 6.0]


def test_a_part_stops_decoding_once_what_started_in_it_is_decided(stubbed):
    session, world = stubbed()
    use_parts(3)
    scan_session(session)
    # Without the stop the first part would read its whole 40 chunk tail, 600 frames past its end.
    assert world.frames[0.0] < 90 * FPS + 100


def test_the_result_covers_the_whole_recording_once(stubbed):
    session, world = stubbed()
    use_parts(3)
    result = scan_session(session)
    assert result.video_seconds == 270.0
    assert not result.cancelled
    assert len(result.part_timings) == 3
    assert {"templates", "life", "waiting for frames"} <= set(result.part_timings[0])


def test_gpu_choice_reaches_every_stream(stubbed):
    session, world = stubbed()
    use_parts(3)
    scan_session(session, gpu=False)
    assert world.gpu_flags == [False, False, False]


# ---- saving -----------------------------------------------------------------

def test_the_scan_is_saved_and_loads_back_the_same(stubbed):
    session, world = stubbed()
    use_parts(3)
    result = scan_session(session)
    assert is_scanned(session)
    assert shape(load_scan(session)) == shape(result.appearances)


def test_scanning_twice_does_not_duplicate_anything(stubbed):
    session, world = stubbed()
    use_parts(3)
    scan_session(session)
    scan_session(session)
    assert shape(load_scan(session)) == EXPECTED


def test_rescanning_a_stretch_replaces_only_that_stretch(stubbed):
    session, world = stubbed()
    use_parts(3)
    scan_session(session)
    # Seconds 96 to 201 hold the revived down and the death, and no badge.
    result = scan_session(session, start=96.0, end=200.0)
    assert [a.sightings[0].label for a in result.appearances] == ["DOWNED", "REVIVED", "DEATH"]
    assert shape(load_scan(session)) == EXPECTED


def test_rescanning_a_stretch_drops_a_badge_that_is_gone_from_it(stubbed):
    session, world = stubbed()
    use_parts(3)
    scan_session(session)
    save_scan(session, load_scan(session) + [Appearance(150.0, 152.0, [Sighting(150.2, "banner", "OLD")])],
              [(150.0, 152.0)])
    scan_session(session, start=96.0, end=200.0)
    assert "OLD" not in [s.label for a in load_scan(session) for s in a.sightings]


# ---- progress ---------------------------------------------------------------

def test_progress_only_goes_forward_and_ends_with_the_whole_recording(stubbed):
    session, world = stubbed(pause=0.001)
    use_parts(3)
    reports: list[ScanProgress] = []
    result = scan_session(session, on_progress=reports.append, progress_interval=0.05)
    assert reports
    fractions = [p.fraction for p in reports]
    assert fractions == sorted(fractions) and 0 <= fractions[0] and fractions[-1] <= 1.0
    assert {p.parts for p in reports} == {3}
    assert {p.video_total for p in reports} == {270.0}
    assert all(p.speed > 0 for p in reports)
    assert result.video_seconds == 270.0


# ---- cancelling -------------------------------------------------------------

def release_when_all_parts_have_started(world: World, frames: int):
    def should_stop() -> bool:
        if world.started == 3 and min(world.frames.values()) >= frames:
            world.release.set()
            return True
        return False

    return should_stop


def test_a_cancelled_scan_stops_every_part_and_closes_every_stream(stubbed):
    session, world = stubbed(block_after=40)
    use_parts(3)
    result = scan_session(session, should_stop=release_when_all_parts_have_started(world, 40))
    assert result.cancelled
    assert world.started == 3 and world.closed == 3
    assert 0 < result.video_seconds < 270


def test_a_cancelled_scan_saves_what_it_covered_and_keeps_older_results_elsewhere(stubbed):
    session, world = stubbed(block_after=40)
    use_parts(3)
    older = [Appearance(start, start + 2, [Sighting(start + 0.2, "banner", f"OLD {start:.0f}")])
             for start in (2.0, 50.0, 100.0, 215.0)]
    save_scan(session, older, [(0.0, 270.0)])
    scan_session(session, should_stop=release_when_all_parts_have_started(world, 40))
    kept = [round(a.start, 1) for a in load_scan(session)]
    # Only the first seconds of each part were scanned. The old badge at 2 s lies in them, the others do not.
    assert kept == [50.0, 100.0, 215.0]


def test_cancelling_when_no_frame_was_decoded_saves_nothing_and_returns_an_empty_result(stubbed):
    # The decoder waits, then ends without a frame once the scan is stopped.
    session, world = stubbed(block_after=0, empty=True)
    use_parts(3)
    result = scan_session(session, should_stop=release_when_all_parts_have_started(world, 0))
    assert result.cancelled and result.appearances == [] and result.video_seconds == 0.0
    assert not is_scanned(session)


# ---- errors -----------------------------------------------------------------

def test_an_error_in_one_part_stops_the_others_saves_nothing_and_reaches_the_caller(stubbed):
    session, world = stubbed(pause=0.001, fail_from=80.0, fail_after=10)
    use_parts(3)
    with pytest.raises(RuntimeError, match="boom"):
        scan_session(session)
    assert world.closed == world.started == 3
    assert world.frames[0.0] < 300  # the first part was cut short, a full run is 450 frames or more
    assert not is_scanned(session)


def test_an_error_in_the_progress_callback_stops_every_part(stubbed):
    session, world = stubbed(pause=0.002)
    use_parts(3)

    def broken(progress: ScanProgress) -> None:
        raise RuntimeError("callback broke")

    with pytest.raises(RuntimeError, match="callback broke"):
        scan_session(session, on_progress=broken, progress_interval=0.0)
    assert world.closed == world.started == 3
    assert not is_scanned(session)


def test_a_recording_with_no_chunks_is_refused_with_a_clear_message(stubbed):
    session, world = stubbed(chunk_count=0)
    with pytest.raises(NoFramesError, match="No video"):
        scan_session(session)
    assert world.started == 0


def test_a_range_outside_the_recording_is_refused(stubbed):
    session, world = stubbed()
    with pytest.raises(NoFramesError, match="No video"):
        scan_session(session, start=5000.0)


def test_a_decoder_that_gives_no_frames_is_reported(stubbed):
    session, world = stubbed(empty=True)
    use_parts(3)
    with pytest.raises(NoFramesError, match="No frames decoded"):
        scan_session(session)
    assert not is_scanned(session)


def test_a_recording_in_another_resolution_is_refused_before_decoding(stubbed, tmp_path):
    session, world = stubbed()
    small = make_session(tmp_path, CHUNKS, size=(1920, 1080))
    with pytest.raises(ResolutionError):
        scan_session(small)
    assert world.started == 0


# ---- real detectors on real frames ------------------------------------------

TESSERACT = Path(config.DEFAULT_TESSERACT_CMD)
FRAME_DIR = Path(__file__).parent / "frames"

# name of the real frame shown from each second on, for a 36 second recording
REAL_SCRIPT = [(0, "black"), (10, "double_kill_kill"), (14, "alive_no_badge"), (18, "downed_plain"),
               (22, "black"), (23, "deploy"), (29, "alive_no_badge")]


def real_frame_at(t: float) -> np.ndarray:
    name = [n for start, n in REAL_SCRIPT if start <= round(t, 3)][-1]
    if name not in _images_real:
        _images_real[name] = cv2.imread(str(FRAME_DIR / f"{name}.png"))
    return _images_real[name]


_images_real: dict[str, np.ndarray] = {}


@pytest.mark.skipif(not TESSERACT.exists(), reason=f"Tesseract not found at {TESSERACT}")
def test_real_frames_through_the_real_detectors_give_a_badge_and_a_death(monkeypatch, tmp_path):
    world = World(image_for=real_frame_at)
    monkeypatch.setattr(scan, "frames_for", world.frames_for)
    session = make_session(tmp_path, 12)
    use_parts(1)
    result = scan_session(session)
    assert result.video_seconds == 36.0
    assert shape(result.appearances) == [
        (10.0, 13.8, (("banner", "DOUBLE KILL", 10.2), ("tag", "KILL", 10.2))),
        (18.0, 21.8, (("life", "DEATH", 18.0),)),
    ]
