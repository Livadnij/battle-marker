"""LifeTracker turns downed and deploy cues into deaths, downs and revives.

Frames come at 5 per second like a real scan. A scene is a list of
(what is on screen, seconds) pairs, so each test reads like a recording.
"""

from detect.life import LifeCues
from events.life import DEATH, DOWNED, KIND, REVIVED, LifeTracker

STEP = 0.2

ALIVE = "alive"
BADGE = "badge"  # alive, and a badge is on screen
DOWN = "down"
DEPLOY = "deploy"


def make_tracker(alive_known: bool = False) -> LifeTracker:
    return LifeTracker(confirm_samples=2, gap_seconds=4, death_wait_seconds=60, alive_known=alive_known)


def play(tracker: LifeTracker, scene: list[tuple[str, float]], start: float = 0.0) -> float:
    """Feeds the scene into the tracker and returns the time after its last frame."""
    index = 0
    for what, seconds in scene:
        for _ in range(round(seconds / STEP)):
            time = round(start + index * STEP, 2)
            cues = LifeCues(downed=what == DOWN, deploy=what == DEPLOY, ring=0.0, deploy_score=0.0)
            tracker.update(time, cues, badge_present=what == BADGE)
            index += 1
    return round(start + index * STEP, 2)


def summary(tracker: LifeTracker) -> list[tuple[str, float]]:
    return [(e.appearance.sightings[0].label, e.appearance.start) for e in tracker.finish()]


def test_down_then_deploy_is_a_death_at_the_down():
    tracker = make_tracker(alive_known=True)
    play(tracker, [(ALIVE, 2), (DOWN, 5), (DEPLOY, 3), (ALIVE, 6)])
    assert summary(tracker) == [(DEATH, 2.0)]


def test_death_event_is_a_life_sighting_spanning_the_down():
    tracker = make_tracker(alive_known=True)
    play(tracker, [(ALIVE, 2), (DOWN, 5), (DEPLOY, 3), (ALIVE, 6)])
    (event,) = tracker.finish()
    assert event.episode == 2.0
    assert event.appearance.start == 2.0
    assert 6.5 < event.appearance.end <= 7.0
    assert [(s.kind, s.label) for s in event.appearance.sightings] == [(KIND, DEATH)]


def test_down_without_deploy_is_downed_then_revived():
    tracker = make_tracker()
    play(tracker, [(ALIVE, 2), (DOWN, 5), (ALIVE, 70)])
    events = tracker.finish()
    assert [e.appearance.sightings[0].label for e in events] == [DOWNED, REVIVED]
    downed, revived = (e.appearance for e in events)
    assert downed.start == 2.0
    # The revive is where the button was last seen, not where the 60 s wait ended.
    assert revived.start == revived.end
    assert 6.5 < revived.start <= 7.0
    assert revived.start > downed.start


def test_loadout_detour_between_down_and_deploy_is_still_a_death():
    tracker = make_tracker()
    play(tracker, [(ALIVE, 2), (DOWN, 5), (ALIVE, 30), (DEPLOY, 3), (ALIVE, 6)])
    assert summary(tracker) == [(DEATH, 2.0)]


def test_deploy_after_the_death_wait_is_a_revive_and_a_later_death():
    tracker = make_tracker()
    play(tracker, [(ALIVE, 2), (DOWN, 5), (ALIVE, 70), (DEPLOY, 3), (ALIVE, 6)])
    labels = [label for label, _ in summary(tracker)]
    assert labels == [DOWNED, REVIVED, DEATH]


def test_short_gap_in_the_downed_button_does_not_end_the_down():
    tracker = make_tracker(alive_known=True)
    play(tracker, [(ALIVE, 2), (DOWN, 2), (ALIVE, 3), (DOWN, 2), (DEPLOY, 3), (ALIVE, 6)])
    assert summary(tracker) == [(DEATH, 2.0)]


def test_going_down_again_after_a_long_gap_means_the_first_down_was_a_revive():
    tracker = make_tracker()
    play(tracker, [(ALIVE, 2), (DOWN, 3), (ALIVE, 20), (DOWN, 3), (DEPLOY, 3), (ALIVE, 6)])
    labels = [label for label, _ in summary(tracker)]
    assert labels == [DOWNED, REVIVED, DEATH]


def test_deploy_screen_at_the_start_of_a_scan_is_no_death():
    tracker = make_tracker(alive_known=False)
    play(tracker, [(DEPLOY, 5), (ALIVE, 10)])
    assert summary(tracker) == []


def test_deploy_after_a_badge_is_a_death_at_the_deploy_screen():
    tracker = make_tracker(alive_known=False)
    play(tracker, [(BADGE, 2), (ALIVE, 2), (DEPLOY, 3), (ALIVE, 6)])
    assert summary(tracker) == [(DEATH, 4.0)]


def test_deploy_after_only_plain_alive_frames_is_no_death():
    tracker = make_tracker(alive_known=False)
    play(tracker, [(ALIVE, 10), (DEPLOY, 3), (ALIVE, 6)])
    assert summary(tracker) == []


def test_part_that_starts_mid_recording_counts_the_player_as_alive():
    tracker = make_tracker(alive_known=True)
    play(tracker, [(ALIVE, 2), (DEPLOY, 3), (ALIVE, 6)])
    assert summary(tracker) == [(DEATH, 2.0)]


def test_second_deploy_without_a_new_life_is_no_second_death():
    tracker = make_tracker(alive_known=True)
    play(tracker, [(ALIVE, 2), (DEPLOY, 3), (ALIVE, 10), (DEPLOY, 3), (ALIVE, 6)])
    assert summary(tracker) == [(DEATH, 2.0)]


def test_badge_after_spawning_makes_the_next_deploy_a_death():
    tracker = make_tracker(alive_known=True)
    play(tracker, [(DEPLOY, 3), (ALIVE, 5), (BADGE, 2), (ALIVE, 4), (DEPLOY, 3), (ALIVE, 6)])
    assert [label for label, _ in summary(tracker)] == [DEATH, DEATH]


def test_badge_right_after_spawning_makes_the_next_deploy_a_death():
    tracker = make_tracker(alive_known=True)
    play(tracker, [(DEPLOY, 3), (BADGE, 2), (ALIVE, 4), (DEPLOY, 3), (ALIVE, 6)])
    assert [label for label, _ in summary(tracker)] == [DEATH, DEATH]


def test_one_down_sample_is_ignored():
    tracker = make_tracker(alive_known=True)
    play(tracker, [(ALIVE, 2), (DOWN, STEP), (ALIVE, 70)])
    assert summary(tracker) == []


def test_undecided_down_at_the_end_is_kept_as_a_plain_down():
    tracker = make_tracker()
    play(tracker, [(ALIVE, 2), (DOWN, 3)])
    assert summary(tracker) == [(DOWNED, 2.0)]


def test_down_in_the_waiting_state_at_the_end_is_kept_as_a_plain_down():
    tracker = make_tracker()
    play(tracker, [(ALIVE, 2), (DOWN, 3), (ALIVE, 10)])
    assert summary(tracker) == [(DOWNED, 2.0)]


def test_finish_twice_does_not_repeat_the_down():
    tracker = make_tracker()
    play(tracker, [(ALIVE, 2), (DOWN, 3)])
    tracker.finish()
    assert len(tracker.finish()) == 1


def test_settled_before_is_false_while_a_down_that_started_earlier_is_open():
    tracker = make_tracker()
    end = play(tracker, [(ALIVE, 2), (DOWN, 3)])
    assert not tracker.settled_before(10.0)
    # A down that started after the time does not hold it up.
    assert tracker.settled_before(1.0)
    assert end > 4


def test_settled_before_is_true_once_the_down_was_decided():
    tracker = make_tracker(alive_known=True)
    play(tracker, [(ALIVE, 2), (DOWN, 3), (DEPLOY, 3), (ALIVE, 6)])
    assert tracker.settled_before(100.0)


def test_settled_before_is_false_while_a_deploy_run_is_still_unconfirmed():
    tracker = make_tracker(alive_known=True)
    play(tracker, [(ALIVE, 2), (DEPLOY, STEP)])
    assert not tracker.settled_before(100.0)


def test_two_deaths_in_one_recording_come_out_in_order():
    tracker = make_tracker(alive_known=True)
    play(tracker, [(ALIVE, 2), (DOWN, 3), (DEPLOY, 3), (ALIVE, 10), (BADGE, 1), (DOWN, 3), (DEPLOY, 3), (ALIVE, 5)])
    events = summary(tracker)
    assert [label for label, _ in events] == [DEATH, DEATH]
    assert events[0][1] < events[1][1]
