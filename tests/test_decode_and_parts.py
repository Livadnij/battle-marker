"""Pure parts of decoding and of splitting a scan into parts. No ffmpeg is started."""

import math

import pytest

import config
from decode.reader import build_command, chunk_range, contiguous_runs
from recording.mpd import VideoTrack
from recording.session import Session
from service.scan import (
    LEAD_CHUNKS, MIN_PART_CHUNKS, TAIL_CHUNKS, ScanProgress, Stopwatch, check_resolution, split_parts,
)
from service.errors import ResolutionError


def make_session(tmp_path, chunks, width=3840, height=2160, codec="hvc1.1.6.L153.B0") -> Session:
    video = tmp_path / "bg_2807960_20261108_215340"
    video.mkdir(exist_ok=True)
    for n in chunks:
        (video / f"chunk-stream0-{n:05d}.m4s").write_bytes(b"")
    track = VideoTrack("0", width, height, codec, "init-stream0.m4s", 3.0, 1, 0.0, 3.0 * len(chunks))
    return Session("2807960", video, tmp_path / "timeline.json", track, 23.0)


# ---- runs and ranges --------------------------------------------------------

@pytest.mark.parametrize("numbers, runs", [
    ([], []),
    ([5], [[5]]),
    ([1, 2, 3], [[1, 2, 3]]),
    ([1, 2, 4, 5, 9], [[1, 2], [4, 5], [9]]),
])
def test_contiguous_runs(numbers, runs):
    assert contiguous_runs(numbers) == runs


def test_chunk_range_without_limits_is_everything(tmp_path):
    session = make_session(tmp_path, range(1, 11))
    assert chunk_range(session, None, None) == list(range(1, 11))


def test_chunk_range_maps_video_seconds_to_the_chunk_that_holds_them(tmp_path):
    session = make_session(tmp_path, range(1, 21))
    # Chunk N covers (N-1)*3 to N*3 seconds, so second 4 is in chunk 2 and second 12 in chunk 5.
    assert chunk_range(session, 4.0, 12.0) == [2, 3, 4, 5]


def test_chunk_range_includes_the_chunk_that_starts_exactly_at_the_limit(tmp_path):
    session = make_session(tmp_path, range(1, 21))
    assert chunk_range(session, 3.0, 9.0) == [2, 3, 4]


def test_chunk_range_is_clamped_to_the_chunks_that_exist(tmp_path):
    session = make_session(tmp_path, range(5, 10))
    assert chunk_range(session, 0.0, 1000.0) == [5, 6, 7, 8, 9]


def test_chunk_range_keeps_gaps_where_steam_deleted_chunks(tmp_path):
    session = make_session(tmp_path, [1, 2, 3, 6, 7])
    assert chunk_range(session, None, None) == [1, 2, 3, 6, 7]


def test_chunk_range_of_an_empty_recording_is_empty(tmp_path):
    assert chunk_range(make_session(tmp_path, []), None, None) == []


# ---- ffmpeg command ---------------------------------------------------------

def test_gpu_command_crops_inside_the_decoder():
    cmd = build_command("ffmpeg", "hvc1.1.6.L153.B0", config.ROI, config.SOURCE_SIZE, 5, gpu=True)
    left, top, right, bottom = config.ROI
    assert cmd[cmd.index("-c:v") + 1] == "hevc_cuvid"
    # NVDEC wants top x bottom x left x right, each as pixels cut off that side.
    assert cmd[cmd.index("-crop") + 1] == f"{top}x{2160 - bottom}x{left}x{3840 - right}"
    assert cmd[cmd.index("-vf") + 1] == "fps=5"
    assert cmd[cmd.index("-i") + 1] == "pipe:0"


def test_cpu_command_crops_with_a_filter():
    cmd = build_command("ffmpeg", "hvc1.1.6.L153.B0", config.ROI, config.SOURCE_SIZE, 5, gpu=False)
    left, top, right, bottom = config.ROI
    assert "-c:v" not in cmd and "-crop" not in cmd
    assert cmd[cmd.index("-vf") + 1] == f"fps=5,crop={right - left}:{bottom - top}:{left}:{top}"


@pytest.mark.parametrize("codec, decoder", [("hev1.1.6", "hevc_cuvid"), ("avc1.640033", "h264_cuvid"), ("av01.0.12M", "av1_cuvid")])
def test_the_decoder_follows_the_codec(codec, decoder):
    cmd = build_command("ffmpeg", codec, config.ROI, config.SOURCE_SIZE, 5, gpu=True)
    assert cmd[cmd.index("-c:v") + 1] == decoder


def test_an_unknown_codec_is_refused_for_gpu_decoding():
    with pytest.raises(ValueError, match="vp9"):
        build_command("ffmpeg", "vp9", config.ROI, config.SOURCE_SIZE, 5, gpu=True)


def test_output_is_raw_bgr_on_stdout_without_audio():
    cmd = build_command("C:/tools/ffmpeg.exe", "hvc1", config.ROI, config.SOURCE_SIZE, 5, gpu=True)
    assert cmd[0] == "C:/tools/ffmpeg.exe"
    assert cmd[-6:] == ["-an", "-pix_fmt", "bgr24", "-f", "rawvideo", "pipe:1"]


# ---- resolution -------------------------------------------------------------

def test_a_4k_recording_passes_the_resolution_check(tmp_path):
    check_resolution(make_session(tmp_path, [1]))


def test_another_resolution_is_refused_with_both_sizes_in_the_message(tmp_path):
    with pytest.raises(ResolutionError, match=r"1920x1080.*3840x2160"):
        check_resolution(make_session(tmp_path, [1], width=1920, height=1080))


# ---- splitting a scan into parts --------------------------------------------

def test_a_long_recording_is_split_into_the_wanted_number_of_parts(tmp_path):
    chunks = list(range(1, 301))
    parts = split_parts(make_session(tmp_path, chunks), chunks, 3)
    assert len(parts) == 3


def test_own_stretches_cover_everything_without_overlap(tmp_path):
    chunks = list(range(1, 301))
    parts = split_parts(make_session(tmp_path, chunks), chunks, 3)
    assert parts[0].own_start == -math.inf
    assert parts[-1].own_end == math.inf
    for before, after in zip(parts, parts[1:]):
        assert before.own_end == after.own_start


def test_boundaries_fall_on_chunk_starts(tmp_path):
    chunks = list(range(1, 301))
    parts = split_parts(make_session(tmp_path, chunks), chunks, 3)
    # 300 chunks in 3 parts of 100, chunk 101 starts at 300 s.
    assert parts[0].own_end == 300.0
    assert parts[1].own_end == 600.0


def test_later_parts_decode_early_and_earlier_parts_decode_late(tmp_path):
    chunks = list(range(1, 301))
    first, middle, last = split_parts(make_session(tmp_path, chunks), chunks, 3)
    assert first.chunks[0] == 1
    assert first.chunks[-1] == 100 + TAIL_CHUNKS  # the first 140 chunks end at chunk 140
    assert middle.chunks[0] == 101 - LEAD_CHUNKS
    assert middle.chunks[-1] == 200 + TAIL_CHUNKS
    assert last.chunks[0] == 201 - LEAD_CHUNKS
    assert last.chunks[-1] == 300  # the last part has no tail to run into


def test_tail_does_not_run_past_the_last_chunk(tmp_path):
    chunks = list(range(1, 101))
    parts = split_parts(make_session(tmp_path, chunks), chunks, 2)
    assert max(parts[0].chunks) == 50 + TAIL_CHUNKS
    assert max(parts[1].chunks) == 100


def test_a_short_recording_gets_fewer_parts(tmp_path):
    chunks = list(range(1, 2 * MIN_PART_CHUNKS + 5))
    parts = split_parts(make_session(tmp_path, chunks), chunks, 5)
    assert len(parts) == 2


def test_a_very_short_recording_is_one_part_with_open_ends(tmp_path):
    chunks = list(range(1, 11))
    (part,) = split_parts(make_session(tmp_path, chunks), chunks, 3)
    assert part.chunks == chunks
    assert (part.own_start, part.own_end) == (-math.inf, math.inf)


def test_one_part_wanted_gives_one_part(tmp_path):
    chunks = list(range(1, 301))
    assert len(split_parts(make_session(tmp_path, chunks), chunks, 1)) == 1


def test_chunk_numbers_that_do_not_start_at_one_still_split_correctly(tmp_path):
    chunks = list(range(101, 401))
    parts = split_parts(make_session(tmp_path, chunks), chunks, 3)
    assert parts[0].own_end == 300.0 + 100 * 3.0
    assert parts[1].chunks[0] == chunks[100 - LEAD_CHUNKS]


# ---- progress and timing ----------------------------------------------------

def test_progress_fraction_is_capped_and_safe_for_an_empty_range():
    assert ScanProgress(30, 60, 0, 1.0, 3).fraction == 0.5
    assert ScanProgress(90, 60, 0, 1.0, 3).fraction == 1.0
    assert ScanProgress(0, 0, 0, 0.0, 3).fraction == 0.0


def test_stopwatch_adds_up_time_and_calls():
    watch = Stopwatch()
    watch.add("ocr", 1.5)
    watch.add("ocr", 0.5)
    assert watch.timings["ocr"] == (2.0, 2)


def test_stopwatch_wrap_times_the_call_and_returns_its_result():
    watch = Stopwatch()
    assert watch.wrap("add", lambda a, b: a + b)(2, b=3) == 5
    assert watch.timings["add"][1] == 1


def test_stopwatch_wrap_counts_a_call_that_raised():
    watch = Stopwatch()

    def fails():
        raise RuntimeError("no")

    with pytest.raises(RuntimeError):
        watch.wrap("fails", fails)()
    assert watch.timings["fails"][1] == 1
