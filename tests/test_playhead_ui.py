"""The playhead line in the badge list of the recording screen, run offscreen.

No recording is opened. A stand-in playback object and a list of badges are set on
the screen directly, which is all the line logic looks at.
"""

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QAbstractSlider, QApplication

from service.badges import Badge
from ui.player.timeline import PLAYED
from ui.recording_screen import RecordingScreen


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def screen(app):
    window = RecordingScreen()
    window.resize(1300, 800)
    window.show()
    app.processEvents()
    yield window
    window.shutdown()
    window.close()


def show_badges(screen: RecordingScreen, times: list[float], playing_back: bool = True) -> None:
    screen.playback = SimpleNamespace(starts_at=0.0, length=100000.0) if playing_back else None
    screen.badges = [Badge(t, [f"BADGE {i}"], None, False) for i, t in enumerate(times)]
    screen._show_badges()
    QApplication.processEvents()  # the scroll range of a long list is only set once Qt has laid it out


def line_row(screen: RecordingScreen) -> int:
    return screen.playhead_line.line_row


def many(count: int = 200) -> list[float]:
    return [10.0 * (i + 1) for i in range(count)]


# ---- where the line is ------------------------------------------------------

def test_the_line_sits_above_the_next_badge(screen):
    show_badges(screen, [10.0, 20.0, 30.0])
    for position, row in [(0.0, 0), (10.0, 1), (15.0, 1), (25.0, 2), (30.0, 3), (99.0, 3)]:
        screen._update_playhead(position, scroll=False)
        assert line_row(screen) == row, position


def test_there_is_no_line_without_playback_or_without_badges(screen):
    show_badges(screen, [10.0, 20.0], playing_back=False)
    screen._update_playhead(5.0, scroll=False)
    assert line_row(screen) == -1
    show_badges(screen, [])
    screen._update_playhead(5.0, scroll=False)
    assert line_row(screen) == -1


def test_new_badges_get_the_line_at_the_current_position(screen):
    show_badges(screen, [10.0, 20.0, 30.0])
    screen._update_playhead(25.0, scroll=False)
    show_badges(screen, [5.0, 15.0, 25.0, 35.0])  # a rescan replaces the list
    assert line_row(screen) == 3


def test_the_table_keeps_one_row_per_badge_in_order(screen):
    show_badges(screen, [10.0, 20.0, 30.0])
    screen._update_playhead(15.0, scroll=False)
    assert screen.badge_table.rowCount() == 3
    assert [screen.badge_table.item(r, 1).text() for r in range(3)] == ["BADGE 0", "BADGE 1", "BADGE 2"]


def test_a_seek_moves_the_line(screen):
    show_badges(screen, [10.0, 20.0, 30.0])
    screen._seek(25.0)
    assert line_row(screen) == 2


def test_dragging_the_timeline_moves_the_line_before_the_seek_is_applied(screen):
    show_badges(screen, [10.0, 20.0, 30.0])
    screen._request_seek(12.0)
    assert line_row(screen) == 1


# ---- what is drawn ----------------------------------------------------------

def pixel(screen: RecordingScreen, x: int, y: int):
    return screen.badge_table.viewport().grab().toImage().pixelColor(x, y)


def test_the_line_is_painted_on_the_top_edge_of_the_next_row(screen, app):
    show_badges(screen, [10.0, 20.0, 30.0])
    screen._update_playhead(15.0, scroll=False)
    app.processEvents()
    top = screen.badge_table.rowViewportPosition(1)
    inside_second_column = screen.badge_table.columnViewportPosition(1) + 40
    assert pixel(screen, inside_second_column, top).name() == PLAYED.name()
    assert pixel(screen, inside_second_column, top + 1).name() == PLAYED.name()
    # The row above and the middle of this row carry no line.
    assert pixel(screen, inside_second_column, top - 3).name() != PLAYED.name()
    assert pixel(screen, inside_second_column, top + screen.badge_table.rowHeight(1) // 2).name() != PLAYED.name()


def test_after_the_last_badge_the_line_sits_on_the_bottom_edge_of_the_last_row(screen, app):
    show_badges(screen, [10.0, 20.0, 30.0])
    screen._update_playhead(99.0, scroll=False)
    app.processEvents()
    table = screen.badge_table
    row_top, row_height = table.rowViewportPosition(2), table.rowHeight(2)
    x = table.columnViewportPosition(1) + 40
    image = table.viewport().grab().toImage()
    # The grid line takes the last pixel row of a cell, so the line sits just above it.
    lower_band = [image.pixelColor(x, row_top + row_height - k).name() for k in range(1, 5)]
    assert PLAYED.name() in lower_band
    assert image.pixelColor(x, row_top + row_height // 2).name() != PLAYED.name()


def test_the_arrow_is_in_the_first_column_only(screen, app):
    show_badges(screen, [10.0, 20.0, 30.0])
    screen._update_playhead(15.0, scroll=False)
    app.processEvents()
    top = screen.badge_table.rowViewportPosition(1)
    first = screen.badge_table.columnViewportPosition(0)
    second = screen.badge_table.columnViewportPosition(1)
    assert pixel(screen, first + 2, top + 4).name() == PLAYED.name()  # inside the arrow
    assert pixel(screen, second + 2, top + 4).name() != PLAYED.name()


# ---- following --------------------------------------------------------------

def test_the_list_scrolls_to_a_line_that_is_out_of_view(screen, app):
    show_badges(screen, many())
    bar = screen.badge_table.verticalScrollBar()
    assert bar.maximum() > 0 and bar.value() == 0
    screen._update_playhead(1500.0, scroll=True)
    app.processEvents()
    assert bar.value() > 0
    top = screen.badge_table.rowViewportPosition(line_row(screen))
    assert 0 <= top < screen.badge_table.viewport().height()


def test_the_list_does_not_scroll_while_the_line_stays_in_view(screen, app):
    show_badges(screen, many())
    bar = screen.badge_table.verticalScrollBar()
    screen._update_playhead(1500.0, scroll=True)
    app.processEvents()
    before = bar.value()
    screen._update_playhead(1510.0, scroll=True)  # one badge on
    assert bar.value() == before


def test_a_line_low_in_the_view_scrolls_the_list_before_it_leaves_it(screen, app):
    show_badges(screen, many())
    table = screen.badge_table
    row = int(0.9 * table.viewport().height() / table.rowHeight(0))  # visible, but below 80 percent of the height
    assert table.rowViewportPosition(row) + table.rowHeight(row) <= table.viewport().height()
    screen._update_playhead(10.0 * row + 1, scroll=True)
    app.processEvents()
    assert table.verticalScrollBar().value() > 0


def test_a_line_in_the_comfortable_part_of_the_view_leaves_the_list_alone(screen, app):
    show_badges(screen, many())
    table = screen.badge_table
    row = int(0.5 * table.viewport().height() / table.rowHeight(0))
    screen._update_playhead(10.0 * row + 1, scroll=True)
    app.processEvents()
    assert table.verticalScrollBar().value() == 0


def test_the_list_follows_the_line_after_the_last_badge(screen, app):
    show_badges(screen, many())
    screen._update_playhead(99999.0, scroll=True)
    app.processEvents()
    bar = screen.badge_table.verticalScrollBar()
    assert bar.value() == bar.maximum()


def test_following_does_not_select_a_row_or_pause_itself(screen, app):
    show_badges(screen, many())
    screen._update_playhead(1500.0, scroll=True)
    app.processEvents()
    assert screen.badge_table.selectedItems() == []
    assert screen._follow_paused_until == 0.0  # the list scrolling itself is not the user's doing


def test_unticking_follow_playback_stops_the_scrolling(screen, app):
    show_badges(screen, many())
    screen.follow_box.setChecked(False)
    screen._update_playhead(1500.0, scroll=True)
    app.processEvents()
    assert screen.badge_table.verticalScrollBar().value() == 0
    assert line_row(screen) == 150  # the line still moves, 150 badges are behind 1500 s


def test_ticking_it_again_scrolls_at_once(screen, app):
    show_badges(screen, many())
    screen.follow_box.setChecked(False)
    screen._update_playhead(1500.0, scroll=True)
    screen.follow_box.setChecked(True)
    app.processEvents()
    assert screen.badge_table.verticalScrollBar().value() > 0


def test_scrolling_by_hand_pauses_following_but_a_seek_still_scrolls(screen, app):
    show_badges(screen, many())
    bar = screen.badge_table.verticalScrollBar()
    bar.triggerAction(QAbstractSlider.SliderAction.SliderSingleStepAdd)  # what a wheel step does
    app.processEvents()
    assert screen._follow_paused_until > 0
    before = bar.value()
    screen._update_playhead(1500.0, scroll=True)  # normal playback tick
    assert bar.value() == before
    screen._seek(1500.0)  # the user jumped somewhere, so the list goes there
    app.processEvents()
    assert bar.value() > before


def test_the_pause_ends(screen, app):
    show_badges(screen, many())
    screen.badge_table.verticalScrollBar().triggerAction(QAbstractSlider.SliderAction.SliderSingleStepAdd)
    screen._follow_paused_until = 0.0  # as if the pause had run out
    screen._update_playhead(1500.0, scroll=True)
    app.processEvents()
    assert screen.badge_table.verticalScrollBar().value() > 1


def test_clicking_a_badge_still_jumps_to_it_and_the_line_lands_on_it(screen):
    show_badges(screen, [10.0, 20.0, 30.0])
    screen._on_badge_clicked(1, 0)
    # The jump starts 2 seconds early, so the clicked badge is the next one.
    assert line_row(screen) == 1
