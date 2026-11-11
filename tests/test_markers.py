"""Planning and writing Steam timeline markers, with the database and a temp timeline."""

import json
from pathlib import Path

import pytest

import service.mark as mark
from events.rules import Rule
from events.tracker import Appearance, Sighting
from markers.writer import PlannedMarker, apply_markers, backup, plan_markers
from recording.mpd import VideoTrack
from recording.session import Session
from recording.timeline import load_timeline, save_timeline
from service.errors import NoScanError, SteamRunningError
from service.scan_log import save_scan
from storage.rules import replace_rules
from storage.settings import Settings, save_settings

OFFSET = 23.0


def write_timeline(path: Path, entries, endtime="600000") -> Path:
    path.write_text(json.dumps({"endtime": endtime, "entries": entries}), encoding="utf-8")
    return path


def entry(time_ms: int, id_="1") -> dict:
    return {"id": id_, "time": str(time_ms), "type": "event", "icon": "steam_marker", "title": "x"}


def marker(seconds: float, title="Kill", icon="steam_star", priority=10) -> PlannedMarker:
    return PlannedMarker(seconds, title, icon, priority)


# ---- timeline files ---------------------------------------------------------

def test_an_empty_entries_object_reads_as_an_empty_list(tmp_path):
    timeline = load_timeline(write_timeline(tmp_path / "t.json", {}))
    assert timeline.entries == []
    assert timeline.marker_times() == []


def test_entries_given_as_an_object_are_turned_into_a_list(tmp_path):
    timeline = load_timeline(write_timeline(tmp_path / "t.json", {"a": entry(5000, "1"), "b": entry(9000, "2")}))
    assert timeline.marker_times() == [5.0, 9.0]


def test_end_seconds_comes_from_endtime_in_milliseconds(tmp_path):
    assert load_timeline(write_timeline(tmp_path / "t.json", [], endtime="90500")).end_seconds == 90.5


def test_a_timeline_without_endtime_has_no_end(tmp_path):
    path = tmp_path / "t.json"
    path.write_text(json.dumps({"entries": []}), encoding="utf-8")
    assert load_timeline(path).end_seconds is None


def test_save_and_load_roundtrip_keeps_unknown_fields(tmp_path):
    path = tmp_path / "t.json"
    path.write_text(json.dumps({"version": 3, "endtime": "1000", "entries": [], "extra": {"a": [1, 2]}}), encoding="utf-8")
    timeline = load_timeline(path)
    timeline.entries.append(entry(500))
    save_timeline(timeline)
    again = load_timeline(path)
    assert again.raw["extra"] == {"a": [1, 2]}
    assert again.raw["version"] == 3
    assert again.marker_times() == [0.5]


# ---- planning ---------------------------------------------------------------

def test_a_marker_close_to_an_existing_entry_is_skipped(tmp_path):
    timeline = load_timeline(write_timeline(tmp_path / "t.json", [entry(100_000)]))
    new, skipped = plan_markers(timeline, [marker(102.5), marker(103.5), marker(97.0)], dedup_seconds=3.0)
    assert [m.timeline_seconds for m in new] == [103.5]
    assert [m.timeline_seconds for m in skipped] == [102.5, 97.0]


def test_the_dedup_distance_is_inclusive(tmp_path):
    timeline = load_timeline(write_timeline(tmp_path / "t.json", [entry(100_000)]))
    new, skipped = plan_markers(timeline, [marker(103.0)], dedup_seconds=3.0)
    assert new == [] and len(skipped) == 1


def test_two_new_markers_a_second_apart_are_both_kept(tmp_path):
    timeline = load_timeline(write_timeline(tmp_path / "t.json", []))
    new, skipped = plan_markers(timeline, [marker(50.0), marker(51.0)], dedup_seconds=3.0)
    assert len(new) == 2 and skipped == []


def test_markers_outside_the_timeline_are_skipped(tmp_path):
    timeline = load_timeline(write_timeline(tmp_path / "t.json", [], endtime="60000"))
    new, skipped = plan_markers(timeline, [marker(-1.0), marker(0.0), marker(60.0), marker(60.1)], dedup_seconds=3.0)
    assert [m.timeline_seconds for m in new] == [0.0, 60.0]
    assert [m.timeline_seconds for m in skipped] == [-1.0, 60.1]


def test_without_an_end_time_nothing_is_out_of_range(tmp_path):
    path = tmp_path / "t.json"
    path.write_text(json.dumps({"entries": []}), encoding="utf-8")
    new, _ = plan_markers(load_timeline(path), [marker(99999.0)], dedup_seconds=3.0)
    assert len(new) == 1


# ---- writing ----------------------------------------------------------------

def test_apply_markers_writes_event_entries_with_string_milliseconds(tmp_path):
    timeline = load_timeline(write_timeline(tmp_path / "t.json", {}))
    apply_markers(timeline, [marker(12.3456, title="Double Kill", icon="steam_star", priority=50)])
    (written,) = load_timeline(tmp_path / "t.json").entries
    assert written == {
        "id": "1", "time": "12346", "type": "event", "icon": "steam_star",
        "priority": 50, "title": "Double Kill", "description": "battle-marker",
    }


def test_new_ids_continue_after_the_highest_existing_one(tmp_path):
    timeline = load_timeline(write_timeline(tmp_path / "t.json", [entry(1000, "4"), entry(2000, "9"), entry(3000, "x")]))
    apply_markers(timeline, [marker(50.0), marker(60.0)])
    assert [e["id"] for e in load_timeline(tmp_path / "t.json").entries][-2:] == ["10", "11"]


def test_existing_entries_are_left_untouched(tmp_path):
    original = entry(1000, "1")
    timeline = load_timeline(write_timeline(tmp_path / "t.json", [original]))
    apply_markers(timeline, [marker(50.0)])
    assert load_timeline(tmp_path / "t.json").entries[0] == original


def test_backup_copies_the_file_with_a_time_stamp(tmp_path):
    path = write_timeline(tmp_path / "timeline_x.json", [entry(1000)])
    saved = backup(load_timeline(path), tmp_path / "bk")
    assert saved.parent == tmp_path / "bk"
    assert saved.name.startswith("timeline_x.") and saved.suffix == ".json"
    assert saved.read_text(encoding="utf-8") == path.read_text(encoding="utf-8")


# ---- the whole path from a scan to the file ---------------------------------

@pytest.fixture
def session(tmp_path) -> Session:
    track = VideoTrack("0", 3840, 2160, "hvc1", "init-stream0.m4s", 3.0, 1, 0.0, 600.0)
    timeline = write_timeline(tmp_path / "timeline_x.json", {}, endtime="600000")
    return Session("2807960", tmp_path / "bg_2807960_20261108_215340", timeline, track, OFFSET)


@pytest.fixture
def rules():
    replace_rules([
        Rule("Double Kill", "DOUBLE KILL", "banner", "steam_star", 50),
        Rule("Headshot", "HEADSHOT", "tag", "steam_bolt", 30),
        Rule("Death", "DEATH", "life", "steam_death", 70),
    ])


def scanned(session: Session) -> None:
    save_scan(session, [
        Appearance(100.0, 102.0, [Sighting(100.4, "banner", "DOUBLE KILL"), Sighting(100.8, "tag", "HEADSHOT")]),
        Appearance(200.0, 202.0, [Sighting(200.4, "banner", "SUPPLY")]),
        Appearance(300.0, 300.0, [Sighting(300.0, "life", "DEATH")]),
    ], [(0.0, 600.0)])


def test_planning_without_a_scan_says_to_scan_first(session, rules):
    with pytest.raises(NoScanError):
        mark.plan_marks(session)


def test_the_plan_turns_matching_badges_into_timeline_markers(session, rules):
    scanned(session)
    plan = mark.plan_marks(session)
    assert [(m.timeline_seconds, m.title, m.icon, m.priority) for m in plan.new] == [
        (100.4 + OFFSET, "Double Kill + Headshot", "steam_star", 50),
        (300.0 + OFFSET, "Death", "steam_death", 70),
    ]
    assert plan.skipped == []


def test_lead_seconds_moves_markers_earlier(session, rules):
    save_settings(Settings(lead_seconds=2.0))
    scanned(session)
    plan = mark.plan_marks(session)
    assert plan.new[0].timeline_seconds == pytest.approx(100.4 + OFFSET - 2.0)


def test_writing_adds_the_markers_and_makes_a_backup(session, rules, monkeypatch):
    monkeypatch.setattr(mark, "steam_running", lambda: False)
    scanned(session)
    written, saved = mark.write_marks(mark.plan_marks(session))
    assert written == 2
    assert saved.exists()
    assert len(load_timeline(session.timeline_path).entries) == 2


def test_writing_twice_does_not_add_the_same_markers_again(session, rules, monkeypatch):
    monkeypatch.setattr(mark, "steam_running", lambda: False)
    scanned(session)
    plan = mark.plan_marks(session)
    mark.write_marks(plan)
    written, _ = mark.write_marks(plan)
    assert written == 0
    assert len(load_timeline(session.timeline_path).entries) == 2
    assert mark.plan_marks(session).new == []


def test_writing_is_refused_while_steam_runs_and_the_file_stays_as_it_was(session, rules, monkeypatch):
    monkeypatch.setattr(mark, "steam_running", lambda: True)
    scanned(session)
    before = session.timeline_path.read_text(encoding="utf-8")
    with pytest.raises(SteamRunningError):
        mark.write_marks(mark.plan_marks(session))
    assert session.timeline_path.read_text(encoding="utf-8") == before


def test_force_writes_even_while_steam_runs(session, rules, monkeypatch):
    monkeypatch.setattr(mark, "steam_running", lambda: True)
    scanned(session)
    written, _ = mark.write_marks(mark.plan_marks(session), force=True)
    assert written == 2


def test_only_the_chosen_markers_are_written(session, rules, monkeypatch):
    monkeypatch.setattr(mark, "steam_running", lambda: False)
    scanned(session)
    plan = mark.plan_marks(session)
    written, _ = mark.write_marks(plan, markers=plan.new[:1])
    assert written == 1
    assert [e["title"] for e in load_timeline(session.timeline_path).entries] == ["Double Kill + Headshot"]


def test_markers_added_by_steam_after_planning_are_respected(session, rules, monkeypatch):
    monkeypatch.setattr(mark, "steam_running", lambda: False)
    scanned(session)
    plan = mark.plan_marks(session)
    # The file changed between planning and writing, a marker now sits at the first one.
    write_timeline(session.timeline_path, [entry(round((100.4 + OFFSET) * 1000))])
    written, _ = mark.write_marks(plan)
    assert written == 1
