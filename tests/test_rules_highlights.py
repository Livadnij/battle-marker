"""Marker rules, icon names and how appearances become highlights."""

import pytest

from events.highlights import build_highlights
from events.rules import Rule, find_rule, rule_problems, rules_from_json
from events.tracker import Appearance, Sighting
from markers.icons import is_valid_icon


def rule(match="KILL", source="any", priority=10, name=None, icon="steam_marker", enabled=True) -> Rule:
    return Rule(name or match.title(), match, source, icon, priority, enabled)


# ---- matching ---------------------------------------------------------------

def test_a_rule_matches_text_that_contains_its_match():
    assert rule("KILL").matches("banner", "DOUBLE KILL")


def test_matching_ignores_case_and_extra_spaces():
    assert rule("double  kill").matches("tag", "DOUBLE KILL")
    assert rule("DOUBLE KILL").matches("tag", "double   kill ")


def test_a_rule_does_not_match_unrelated_text():
    assert not rule("HEADSHOT").matches("tag", "KILL")


def test_a_disabled_rule_never_matches():
    assert not rule("KILL", enabled=False).matches("banner", "KILL")


def test_source_banner_only_matches_banner_text():
    r = rule("KILL", source="banner")
    assert r.matches("banner", "KILL")
    assert not r.matches("tag", "KILL")
    assert not r.matches("life", "KILL")


def test_source_any_matches_banner_and_tag_but_not_life():
    r = rule("DEATH", source="any")
    assert r.matches("banner", "DEATH")
    assert r.matches("tag", "DEATH")
    assert not r.matches("life", "DEATH")


def test_source_life_only_matches_life_events():
    r = rule("DEATH", source="life")
    assert r.matches("life", "DEATH")
    assert not r.matches("banner", "DEATH")


def test_find_rule_picks_the_highest_priority_match():
    low, high = rule("KILL", priority=5, name="Kill"), rule("DOUBLE KILL", priority=50, name="Double")
    assert find_rule([low, high], "banner", "DOUBLE KILL") is high
    assert find_rule([high, low], "banner", "DOUBLE KILL") is high


def test_find_rule_skips_disabled_rules_even_with_top_priority():
    off, on = rule("KILL", priority=99, enabled=False), rule("KILL", priority=1)
    assert find_rule([off, on], "tag", "KILL") is on


def test_find_rule_returns_none_without_a_match():
    assert find_rule([rule("HEADSHOT")], "tag", "KILL") is None
    assert find_rule([], "tag", "KILL") is None


# ---- validation -------------------------------------------------------------

def test_a_good_rule_has_no_problems():
    assert rule_problems(rule("KILL", icon="steam_star")) == []


def test_every_problem_of_a_rule_is_reported():
    bad = Rule(name="Bad", match=" ", source="sky", icon="nope", priority=-1)
    assert len(rule_problems(bad)) == 4


def test_the_problem_text_names_the_rule():
    (problem,) = rule_problems(Rule("Mine", "KILL", "banner", "nope", 1))
    assert "Mine" in problem and "nope" in problem


@pytest.mark.parametrize("name", ["steam_death", "steam_marker", "steam_0", "steam_42", "steam_99"])
def test_known_icons_are_valid(name):
    assert is_valid_icon(name)


@pytest.mark.parametrize("name", ["", "death", "steam_100", "steam_", "steam_-1", "steam_unknown", "STEAM_DEATH"])
def test_unknown_icons_are_invalid(name):
    assert not is_valid_icon(name)


def test_old_markers_json_becomes_rules_with_defaults():
    rules = rules_from_json({"markers": [
        {"name": "Kill", "match": "KILL", "source": "tag", "icon": "steam_star", "priority": 7, "enabled": False},
        {"match": "HEADSHOT"},
    ]})
    assert rules[0] == Rule("Kill", "KILL", "tag", "steam_star", 7, False)
    assert rules[1] == Rule("HEADSHOT", "HEADSHOT", "any", "steam_marker", 0, True)


def test_old_markers_json_without_markers_gives_no_rules():
    assert rules_from_json({}) == []


# ---- highlights -------------------------------------------------------------

DOUBLE = rule("DOUBLE KILL", source="banner", priority=50, name="Double Kill", icon="steam_star")
HEAD = rule("HEADSHOT", source="tag", priority=30, name="Headshot", icon="steam_bolt")
DEATH = rule("DEATH", source="life", priority=70, name="Death", icon="steam_death")


def appearance(start, *sights) -> Appearance:
    return Appearance(start, start + 2, [Sighting(t, kind, label) for t, kind, label in sights])


def test_an_appearance_with_two_matching_texts_makes_one_highlight():
    a = appearance(10, (10.4, "banner", "DOUBLE KILL"), (10.8, "tag", "HEADSHOT"))
    (h,) = build_highlights([a], rules=[DOUBLE, HEAD])
    assert h.time == 10.4
    assert h.rules == [DOUBLE, HEAD]
    assert h.title == "Double Kill + Headshot"


def test_the_highlight_icon_comes_from_the_top_priority_rule():
    a = appearance(10, (10.4, "tag", "HEADSHOT"), (10.8, "banner", "DOUBLE KILL"))
    (h,) = build_highlights([a], rules=[DOUBLE, HEAD])
    assert h.top is DOUBLE
    # The time is the first matching text, not the top rule's.
    assert h.time == 10.4


def test_sightings_are_used_in_time_order_whatever_their_list_order():
    a = appearance(10, (10.8, "tag", "HEADSHOT"), (10.4, "banner", "DOUBLE KILL"))
    (h,) = build_highlights([a], rules=[DOUBLE, HEAD])
    assert h.title == "Double Kill + Headshot"


def test_the_same_rule_twice_in_one_appearance_is_listed_once():
    a = appearance(10, (10.4, "banner", "DOUBLE KILL"), (11.0, "tag", "DOUBLE KILL"))
    (h,) = build_highlights([a], rules=[rule("DOUBLE KILL", source="any", priority=50, name="Double Kill")])
    assert [r.name for r in h.rules] == ["Double Kill"]


def test_an_appearance_without_a_matching_text_makes_no_highlight():
    a = appearance(10, (10.4, "banner", "SUPPLY"))
    assert build_highlights([a], rules=[DOUBLE, HEAD]) == []


def test_an_appearance_without_any_text_makes_no_highlight():
    assert build_highlights([appearance(10)], rules=[DOUBLE]) == []


def test_separate_appearances_are_never_merged_even_a_second_apart():
    a, b = appearance(10, (10.4, "banner", "DOUBLE KILL")), appearance(11, (11.4, "banner", "DOUBLE KILL"))
    assert len(build_highlights([a, b], rules=[DOUBLE])) == 2


def test_highlights_come_out_oldest_first():
    late, early = appearance(50, (50.4, "banner", "DOUBLE KILL")), appearance(10, (10.4, "banner", "DOUBLE KILL"))
    assert [h.time for h in build_highlights([late, early], rules=[DOUBLE])] == [10.4, 50.4]


def test_life_events_use_life_rules_only():
    died = appearance(100, (100.0, "life", "DEATH"))
    assert [h.title for h in build_highlights([died], rules=[DEATH])] == ["Death"]
    # A rule for banner text called DEATH must not pick up a life event.
    assert build_highlights([died], rules=[rule("DEATH", source="banner")]) == []


def test_no_rules_means_no_highlights():
    assert build_highlights([appearance(10, (10.4, "banner", "DOUBLE KILL"))], rules=[]) == []
