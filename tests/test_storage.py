"""The SQLite storage, covering migrations, settings, rules, scans, game names and the old-file import."""

import json
import sqlite3
from pathlib import Path

import pytest

import config
from events.rules import Rule
from events.tracker import Appearance, Sighting
from service.scan_log import is_scanned, load_scan, save_scan
from storage import db, scans, settings as settings_store
from storage.app_names import get_app_name, put_app_name
from storage.rules import list_rules, replace_rules, seen_labels
from storage.settings import Settings, forget_cache, get_settings, save_settings


def app(start, end, *sights) -> Appearance:
    return Appearance(start, end, [Sighting(t, k, label) for t, k, label in sights])


# ---- schema -----------------------------------------------------------------

def test_a_new_database_is_at_the_latest_schema_version():
    with db.connect() as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == len(db.MIGRATIONS)


def test_a_new_database_has_the_life_rules_from_migration_two():
    rules = {r.name: r for r in list_rules()}
    assert rules["Death"] == Rule("Death", "DEATH", "life", "steam_death", 70, True)
    assert rules["Downed"].icon == "steam_caution" and rules["Revived"].icon == "steam_heart"
    assert len(rules) == 3


def test_opening_the_database_twice_does_not_run_migrations_again():
    with db.connect():
        pass
    db.reset_for_tests()
    assert len(list_rules()) == 3


def test_a_version_one_database_is_upgraded(tmp_path):
    con = sqlite3.connect(config.DB_FILE)
    con.executescript(db.MIGRATIONS[0] + "PRAGMA user_version = 1;")
    con.close()
    db.reset_for_tests()
    assert [r.name for r in list_rules()] == ["Death", "Downed", "Revived"]


def test_a_failed_operation_is_rolled_back():
    with pytest.raises(RuntimeError):
        with db.connect() as con:
            con.execute("INSERT INTO app_names (app_id, name) VALUES ('1', 'A')")
            raise RuntimeError("stop")
    assert get_app_name("1") is None


def test_foreign_keys_are_enforced():
    with pytest.raises(sqlite3.IntegrityError):
        with db.connect() as con:
            con.execute("INSERT INTO badges (session, video_start, video_end) VALUES ('missing', 0, 1)")


# ---- settings ---------------------------------------------------------------

def test_settings_default_to_the_config_values():
    s = get_settings()
    assert s.recordings_root == config.DEFAULT_RECORDINGS_ROOT
    assert s.scan_parts == config.DEFAULT_SCAN_PARTS
    assert s.gpu_decoding is config.DEFAULT_GPU_DECODING


def test_saved_settings_survive_a_restart(tmp_path):
    save_settings(Settings(recordings_root=tmp_path / "rec", ffmpeg="C:/ff/ffmpeg.exe", gpu_decoding=False,
                           scan_parts=2, dedup_seconds=1.5, lead_seconds=2.0))
    forget_cache()
    s = get_settings()
    assert s.recordings_root == tmp_path / "rec" and isinstance(s.recordings_root, Path)
    assert (s.ffmpeg, s.gpu_decoding, s.scan_parts, s.dedup_seconds, s.lead_seconds) == (
        "C:/ff/ffmpeg.exe", False, 2, 1.5, 2.0)


def test_saving_twice_replaces_the_values():
    save_settings(Settings(scan_parts=2))
    save_settings(Settings(scan_parts=4))
    forget_cache()
    assert get_settings().scan_parts == 4


def test_settings_are_cached_until_saved_or_forgotten():
    first = get_settings()
    assert get_settings() is first
    save_settings(Settings(scan_parts=6))
    assert get_settings().scan_parts == 6


def test_a_setting_that_no_longer_exists_in_the_dataclass_is_ignored():
    with db.connect() as con:
        con.execute("INSERT INTO settings (key, value) VALUES ('old_thing', '1')")
    forget_cache()
    assert get_settings() == Settings()


# ---- rules ------------------------------------------------------------------

def test_replace_rules_stores_exactly_the_given_rules():
    replace_rules([Rule("A", "A", "banner", "steam_star", 5), Rule("B", "B", "tag", "steam_bolt", 9, False)])
    assert list_rules() == [Rule("B", "B", "tag", "steam_bolt", 9, False), Rule("A", "A", "banner", "steam_star", 5, True)]


def test_rules_are_listed_by_priority_then_insertion_order():
    replace_rules([Rule("first", "x", "any", "steam_star", 5), Rule("second", "y", "any", "steam_star", 5),
                   Rule("top", "z", "any", "steam_star", 9)])
    assert [r.name for r in list_rules()] == ["top", "first", "second"]


def test_replacing_with_an_empty_list_removes_all_rules():
    replace_rules([])
    assert list_rules() == []


# ---- scans ------------------------------------------------------------------

def test_an_unscanned_recording_loads_as_none():
    assert scans.load_appearances("bg_x") is None
    assert not scans.is_scanned("bg_x")


def test_a_scan_roundtrips(tmp_path):
    original = [app(10, 12, (10.4, "banner", "DOUBLE KILL"), (10.9, "tag", "HEADSHOT")), app(50, 51)]
    scans.save_appearances("bg_x", "t.json", 23.0, original, [(0, 100)])
    assert scans.is_scanned("bg_x")
    assert scans.load_appearances("bg_x") == original


def test_a_scan_with_no_badges_still_counts_as_scanned():
    scans.save_appearances("bg_x", "t.json", 23.0, [], [(0, 100)])
    assert scans.load_appearances("bg_x") == []


def test_appearances_load_oldest_first_and_sightings_by_time():
    scans.save_appearances("bg_x", "t.json", 0.0,
                           [app(50, 51, (50.2, "banner", "B")), app(10, 12, (10.9, "tag", "T2"), (10.4, "banner", "T1"))],
                           [(0, 100)])
    first, second = scans.load_appearances("bg_x")
    assert (first.start, second.start) == (10, 50)
    assert [s.label for s in first.sightings] == ["T1", "T2"]


def test_rescanning_a_stretch_keeps_badges_outside_it():
    scans.save_appearances("bg_x", "t.json", 0.0, [app(10, 12), app(50, 52), app(90, 92)], [(0, 100)])
    scans.save_appearances("bg_x", "t.json", 0.0, [app(51, 53)], [(40, 60)])
    assert [a.start for a in scans.load_appearances("bg_x")] == [10, 51, 90]


def test_a_badge_overlapping_the_rescanned_range_is_replaced():
    scans.save_appearances("bg_x", "t.json", 0.0, [app(38, 42)], [(0, 100)])
    scans.save_appearances("bg_x", "t.json", 0.0, [], [(40, 60)])
    assert scans.load_appearances("bg_x") == []


def test_a_badge_on_the_seam_of_two_ranges_is_kept():
    # Ranges are cleared before anything is inserted, so the seam badge is not wiped by the second range.
    scans.save_appearances("bg_x", "t.json", 0.0, [app(99, 101)], [(0, 100), (100, 200)])
    assert [a.start for a in scans.load_appearances("bg_x")] == [99]


def test_scans_of_different_recordings_do_not_mix():
    scans.save_appearances("bg_a", "a.json", 0.0, [app(1, 2)], [(0, 10)])
    scans.save_appearances("bg_b", "b.json", 0.0, [app(5, 6)], [(0, 10)])
    scans.save_appearances("bg_a", "a.json", 0.0, [], [(0, 10)])
    assert scans.load_appearances("bg_a") == []
    assert [a.start for a in scans.load_appearances("bg_b")] == [5]


def test_the_session_level_helpers_use_the_session_name(tmp_path):
    from recording.mpd import VideoTrack
    from recording.session import Session

    track = VideoTrack("0", 3840, 2160, "hvc1", "init-stream0.m4s", 3.0, 1, 0.0, 60.0)
    session = Session("2807960", tmp_path / "bg_2807960_20261108_215340", tmp_path / "tl.json", track, 23.0)
    assert not is_scanned(session) and load_scan(session) is None
    save_scan(session, [app(10, 12, (10.4, "banner", "KILL"))], [(0, 60)])
    assert is_scanned(session)
    assert load_scan(session)[0].sightings[0].label == "KILL"
    with db.connect() as con:
        row = con.execute("SELECT timeline, time_offset FROM scans").fetchone()
    assert (row["timeline"], row["time_offset"]) == ("tl.json", 23.0)


def test_seen_labels_count_badges_most_frequent_first():
    scans.save_appearances("bg_a", "a.json", 0.0,
                           [app(1, 2, (1.2, "banner", "KILL")), app(5, 6, (5.2, "banner", "KILL")),
                            app(9, 10, (9.2, "tag", "HEADSHOT"))], [(0, 20)])
    scans.save_appearances("bg_b", "b.json", 0.0, [app(1, 2, (1.2, "banner", "KILL"))], [(0, 20)])
    labels = [(s.kind, s.label, s.count) for s in seen_labels()]
    assert labels == [("banner", "KILL", 3), ("tag", "HEADSHOT", 1)]


# ---- game names -------------------------------------------------------------

def test_game_names_are_stored_and_replaced():
    assert get_app_name("2807960") is None
    put_app_name("2807960", "Battlefield 6")
    put_app_name("2807960", "Battlefield 6 Beta")
    assert get_app_name("2807960") == "Battlefield 6 Beta"


# ---- one-time import of the old files ---------------------------------------

def test_the_old_files_are_imported_when_the_database_is_created(tmp_path, monkeypatch):
    markers = tmp_path / "markers.json"
    markers.write_text(json.dumps({"markers": [
        {"name": "Kill", "match": "KILL", "source": "tag", "icon": "steam_star", "priority": 4},
    ]}), encoding="utf-8")
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "bg_old.json").write_text(json.dumps({
        "session": "bg_old", "timeline": "t.json", "offset": 20,
        "appearances": [{"start": 5, "end": 7, "sightings": [{"time": 5.4, "kind": "banner", "label": "KILL"}]}],
    }), encoding="utf-8")
    (logs / "bg_broken.json").write_text("{not json", encoding="utf-8")
    names = tmp_path / "names.json"
    names.write_text(json.dumps({"2807960": "Battlefield 6"}), encoding="utf-8")
    monkeypatch.setattr(config, "LEGACY_MARKERS_FILE", markers)
    monkeypatch.setattr(config, "LEGACY_SCAN_LOGS_DIR", logs)
    monkeypatch.setattr(config, "LEGACY_APP_NAMES_FILE", names)
    db.reset_for_tests()

    # Rules come from markers.json, and the life rules from the migration are kept.
    assert [r.name for r in list_rules()] == ["Death", "Downed", "Revived", "Kill"]
    assert scans.load_appearances("bg_old")[0].sightings[0].label == "KILL"
    assert scans.load_appearances("bg_broken") is None
    assert get_app_name("2807960") == "Battlefield 6"


def test_the_old_files_are_not_read_again_for_an_existing_database(tmp_path, monkeypatch):
    with db.connect():
        pass
    markers = tmp_path / "markers.json"
    markers.write_text(json.dumps({"markers": [{"match": "KILL"}]}), encoding="utf-8")
    monkeypatch.setattr(config, "LEGACY_MARKERS_FILE", markers)
    db.reset_for_tests()
    assert {r.name for r in list_rules()} == {"Death", "Downed", "Revived"}
