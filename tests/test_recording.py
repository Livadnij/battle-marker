"""Steam's files, meaning session.mpd, recording folders paired with timelines, and time text.

The mpd below is written by hand to hold what mpd.py reads. It is not a copy
of a real Steam file, so a Steam format change would not show up here.
"""

import pytest

from recording.mpd import parse_iso_duration, read_audio_track, read_video_track
from recording.session import find_session, find_sessions
from service.timefmt import fmt, parse_time

MPD = """<?xml version="1.0" encoding="utf-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static" mediaPresentationDuration="PT1H2M3.5S">
  <Period start="PT0S">
    <AdaptationSet contentType="video">
      <Representation id="0" width="3840" height="2160" codecs="hvc1.1.6.L153.B0">
        <SegmentTemplate timescale="1000000" duration="3000000" startNumber="1"
            initialization="init-stream$RepresentationID$.m4s"
            media="chunk-stream$RepresentationID$-$Number%05d$.m4s"/>
      </Representation>
    </AdaptationSet>
    <AdaptationSet contentType="audio">
      <Representation id="1" codecs="mp4a.40.2">
        <SegmentTemplate timescale="48000" duration="144000" startNumber="1"
            initialization="init-stream$RepresentationID$.m4s"
            media="chunk-stream$RepresentationID$-$Number%05d$.m4s"/>
      </Representation>
    </AdaptationSet>
  </Period>
</MPD>
"""

MPD_VIDEO_ONLY = MPD.split('    <AdaptationSet contentType="audio">')[0] + "  </Period>\n</MPD>\n"


# ---- mpd --------------------------------------------------------------------

@pytest.mark.parametrize("text, seconds", [
    ("PT0S", 0.0), ("PT3S", 3.0), ("PT1.5S", 1.5), ("PT2M", 120.0),
    ("PT1H", 3600.0), ("PT1H2M3.5S", 3723.5), ("PT30M10S", 1810.0),
])
def test_iso_durations(text, seconds):
    assert parse_iso_duration(text) == seconds


@pytest.mark.parametrize("text", ["", "3S", "P1D", "PT-3S", "PTS"])
def test_unsupported_durations_are_rejected(text):
    with pytest.raises(ValueError):
        parse_iso_duration(text)


def test_video_track_fields(tmp_path):
    path = tmp_path / "session.mpd"
    path.write_text(MPD, encoding="utf-8")
    track = read_video_track(path)
    assert (track.width, track.height) == (3840, 2160)
    assert track.codec == "hvc1.1.6.L153.B0"
    assert track.representation_id == "0"
    assert track.init_name == "init-stream0.m4s"
    assert track.segment_seconds == 3.0
    assert track.start_number == 1
    assert track.duration == 3723.5


def test_chunk_names_and_start_times(tmp_path):
    path = tmp_path / "session.mpd"
    path.write_text(MPD, encoding="utf-8")
    track = read_video_track(path)
    assert track.chunk_name(1) == "chunk-stream0-00001.m4s"
    assert track.chunk_name(12345) == "chunk-stream0-12345.m4s"
    assert track.chunk_start(1) == 0.0
    assert track.chunk_start(11) == 30.0


def test_audio_track_is_read_from_its_own_adaptation_set(tmp_path):
    path = tmp_path / "session.mpd"
    path.write_text(MPD, encoding="utf-8")
    audio = read_audio_track(path)
    assert audio.representation_id == "1"
    assert audio.width == 0 and audio.height == 0
    assert audio.segment_seconds == 3.0


def test_a_recording_without_audio_gives_none(tmp_path):
    path = tmp_path / "session.mpd"
    path.write_text(MPD_VIDEO_ONLY, encoding="utf-8")
    assert read_audio_track(path) is None


def test_a_recording_without_video_is_an_error(tmp_path):
    path = tmp_path / "session.mpd"
    path.write_text(MPD.replace('contentType="video"', 'contentType="text"'), encoding="utf-8")
    with pytest.raises(ValueError):
        read_video_track(path)


# ---- sessions ---------------------------------------------------------------

def make_recording(root, folder: str, chunks=(1, 2, 3)):
    video = root / "video" / folder
    video.mkdir(parents=True)
    (video / "session.mpd").write_text(MPD, encoding="utf-8")
    (video / "init-stream0.m4s").write_bytes(b"")
    (video / "init-stream1.m4s").write_bytes(b"")
    for n in chunks:
        (video / f"chunk-stream0-{n:05d}.m4s").write_bytes(b"")
        (video / f"chunk-stream1-{n:05d}.m4s").write_bytes(b"")
    return video


def make_timeline(root, name: str):
    folder = root / "timelines"
    folder.mkdir(exist_ok=True)
    (folder / name).write_text('{"entries": {}}', encoding="utf-8")


def test_a_recording_is_paired_with_its_timeline_and_gets_the_offset(tmp_path):
    make_recording(tmp_path, "bg_2807960_20261108_215340")
    make_timeline(tmp_path, "timeline_280796020261108_215317.json")
    (session,) = find_sessions(tmp_path)
    assert session.app_id == "2807960"
    assert session.name == "bg_2807960_20261108_215340"
    assert session.timeline_path.name == "timeline_280796020261108_215317.json"
    assert session.offset == 23.0


def test_video_time_and_timeline_time_convert_both_ways(tmp_path):
    make_recording(tmp_path, "bg_2807960_20261108_215340")
    make_timeline(tmp_path, "timeline_280796020261108_215317.json")
    (session,) = find_sessions(tmp_path)
    assert session.to_timeline(100.0) == 123.0
    assert session.to_video(123.0) == 100.0
    assert session.to_video(session.to_timeline(41.7)) == pytest.approx(41.7)


def test_the_latest_timeline_before_the_recording_owns_it(tmp_path):
    make_recording(tmp_path, "bg_2807960_20261108_215340")
    make_timeline(tmp_path, "timeline_280796020261108_200000.json")
    make_timeline(tmp_path, "timeline_280796020261108_215317.json")
    make_timeline(tmp_path, "timeline_280796020261108_220000.json")  # starts after the recording
    (session,) = find_sessions(tmp_path)
    assert session.timeline_path.name == "timeline_280796020261108_215317.json"


def test_a_timeline_of_another_game_is_not_used(tmp_path):
    make_recording(tmp_path, "bg_2807960_20261108_215340")
    make_timeline(tmp_path, "timeline_99999920261108_215317.json")
    assert find_sessions(tmp_path) == []


def test_a_recording_without_an_earlier_timeline_is_left_out(tmp_path):
    make_recording(tmp_path, "bg_2807960_20261108_215340")
    make_timeline(tmp_path, "timeline_280796020261108_220000.json")
    assert find_sessions(tmp_path) == []


def test_folders_that_are_not_recordings_are_ignored(tmp_path):
    make_recording(tmp_path, "bg_2807960_20261108_215340")
    make_timeline(tmp_path, "timeline_280796020261108_215317.json")
    (tmp_path / "video" / "something_else").mkdir()
    no_mpd = tmp_path / "video" / "bg_2807960_20261108_230000"
    no_mpd.mkdir()
    assert [s.name for s in find_sessions(tmp_path)] == ["bg_2807960_20261108_215340"]


def test_files_in_the_timelines_folder_that_are_not_timelines_are_ignored(tmp_path):
    make_recording(tmp_path, "bg_2807960_20261108_215340")
    make_timeline(tmp_path, "timeline_280796020261108_215317.json")
    make_timeline(tmp_path, "notes.json")
    make_timeline(tmp_path, "timeline_broken.json")
    assert len(find_sessions(tmp_path)) == 1


def test_several_recordings_are_listed_oldest_first(tmp_path):
    make_recording(tmp_path, "bg_2807960_20261109_100000")
    make_recording(tmp_path, "bg_2807960_20261108_215340")
    make_timeline(tmp_path, "timeline_280796020261108_215317.json")
    make_timeline(tmp_path, "timeline_280796020261109_095940.json")
    sessions = find_sessions(tmp_path)
    assert [s.name for s in sessions] == ["bg_2807960_20261108_215340", "bg_2807960_20261109_100000"]
    assert [s.offset for s in sessions] == [23.0, 20.0]


def test_chunk_numbers_come_from_the_video_stream_files_only_and_sorted(tmp_path):
    make_recording(tmp_path, "bg_2807960_20261108_215340", chunks=(10, 2, 3, 11))
    make_timeline(tmp_path, "timeline_280796020261108_215317.json")
    (session,) = find_sessions(tmp_path)
    assert session.chunk_numbers() == [2, 3, 10, 11]


def test_find_session_by_name_and_a_clear_error_for_a_missing_one(tmp_path):
    make_recording(tmp_path, "bg_2807960_20261108_215340")
    make_timeline(tmp_path, "timeline_280796020261108_215317.json")
    assert find_session(tmp_path, "bg_2807960_20261108_215340").offset == 23.0
    with pytest.raises(LookupError, match="bg_nothing"):
        find_session(tmp_path, "bg_nothing")


# ---- time text --------------------------------------------------------------

@pytest.mark.parametrize("text, seconds", [
    ("0", 0.0), ("45", 45.0), ("1:05", 65.0), ("0:01:05", 65.0),
    ("1:02:03", 3723.0), ("0:00:12.5", 12.5),
])
def test_parse_time(text, seconds):
    assert parse_time(text) == seconds


@pytest.mark.parametrize("seconds, text", [
    (0, "0:00:00.0"), (65, "0:01:05.0"), (3723.5, "1:02:03.5"), (-5, "-0:00:05.0"),
])
def test_fmt(seconds, text):
    assert fmt(seconds) == text


def test_fmt_and_parse_time_are_inverse():
    for seconds in (0.0, 12.5, 3599.9, 7384.2):
        assert parse_time(fmt(seconds)) == pytest.approx(seconds, abs=0.05)
