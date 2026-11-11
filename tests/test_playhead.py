"""Finding where the playhead sits among the badges of the list."""

import pytest

from service.badges import next_badge_index

TIMES = [10.0, 20.0, 30.0]


@pytest.mark.parametrize("position, expected", [
    (0.0, 0),      # before the first badge
    (9.9, 0),
    (10.0, 1),     # a badge exactly at the position counts as reached
    (10.1, 1),     # between the first two
    (19.9, 1),
    (25.0, 2),
    (29.9, 2),
    (30.0, 3),     # on the last badge
    (500.0, 3),    # after the last badge
])
def test_the_next_badge_is_the_first_one_still_ahead(position, expected):
    assert next_badge_index(TIMES, position) == expected


def test_no_badges_gives_zero():
    assert next_badge_index([], 5.0) == 0


def test_one_badge_before_and_after_it():
    assert next_badge_index([12.0], 11.0) == 0
    assert next_badge_index([12.0], 12.5) == 1


def test_negative_positions_are_before_everything():
    assert next_badge_index(TIMES, -3.0) == 0


def test_two_badges_at_the_same_time_are_reached_together():
    assert next_badge_index([5.0, 5.0, 9.0], 4.0) == 0
    assert next_badge_index([5.0, 5.0, 9.0], 5.0) == 2


def test_a_neighbour_slightly_out_of_time_order_does_not_move_the_line_backwards():
    # The second badge started later but its text matched earlier, so the list is not sorted.
    times = [12.0, 11.4, 30.0]
    assert next_badge_index(times, 11.0) == 0
    assert next_badge_index(times, 11.5) == 0  # the first badge is still ahead
    assert next_badge_index(times, 12.0) == 2
