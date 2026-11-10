"""Timeline under the video. Shows a zoomable window of the recording with badge icons.

Only part of the recording is visible at a time, so badges a few seconds
apart stay apart. The wheel zooms around the cursor, Shift+wheel or the
scrollbar below pans, and while playing the view follows the playhead.
"""

from dataclasses import dataclass

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QPen, QWheelEvent
from PySide6.QtWidgets import QWidget

from service.timefmt import fmt
from ui.player.icons import icon_pixmap

DEFAULT_VIEW_SECONDS = 10 * 60  # visible span when a recording is opened
MIN_VIEW_SECONDS = 30
ZOOM_STEP = 1.25  # one wheel notch
FOLLOW_MARGIN = 0.1  # the view jumps ahead when the playhead gets this close to its right edge
BADGE_HOVER_PIXELS = 10  # how close the cursor must be for the preview to name a badge

ICON_SIZE = 18
BAR_HEIGHT = 6
MARGIN = 10
SELECTED = QColor("#ff7a1a")
MUTED = QColor(150, 150, 150, 150)
TRACK = QColor(70, 70, 70)
PLAYED = QColor("#3d8bfd")
PLAYHEAD = QColor("#ffffff")
LABEL = QColor(170, 170, 170)
BACKGROUND = QColor("#1b1d21")  # dark like Steam's player, the icons are white


@dataclass(frozen=True)
class TimelineBadge:
    time: float  # timeline seconds
    selected: bool  # picked by a rule
    icon: str
    title: str


class TimelineBar(QWidget):
    seek_requested = Signal(float)  # timeline seconds
    hovered = Signal(float, QPoint, str)  # timeline seconds, global top of the bar, nearby badge title
    hover_left = Signal()
    view_changed = Signal(float, float)  # visible start and end, timeline seconds

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(ICON_SIZE + BAR_HEIGHT + 30)
        self.setMouseTracking(True)
        self.start = 0.0
        self.end = 1.0
        self.view_start = 0.0
        self.view_end = 1.0
        self.position = 0.0
        self.badges: list[TimelineBadge] = []
        self.dragging = False

    # ---- data -----------------------------------------------------------

    def set_range(self, start: float, end: float) -> None:
        self.start, self.end = start, max(end, start + 1)
        span = min(DEFAULT_VIEW_SECONDS, self.end - self.start)
        self.set_view(self.start, self.start + span)

    def set_view(self, view_start: float, view_end: float) -> None:
        span = min(max(view_end - view_start, MIN_VIEW_SECONDS), self.end - self.start)
        view_start = min(max(view_start, self.start), self.end - span)
        self.view_start, self.view_end = view_start, view_start + span
        self.update()
        self.view_changed.emit(self.view_start, self.view_end)

    def set_position(self, seconds: float, follow: bool = False) -> None:
        self.position = seconds
        span = self.view_end - self.view_start
        if follow and not self.dragging and not (
            self.view_start <= seconds <= self.view_end - span * FOLLOW_MARGIN
        ):
            self.set_view(seconds - span * FOLLOW_MARGIN, seconds + span * (1 - FOLLOW_MARGIN))
        self.update()

    def set_badges(self, badges: list[TimelineBadge]) -> None:
        self.badges = sorted(badges, key=lambda b: b.selected)  # selected drawn last, on top
        self.update()

    # ---- geometry -------------------------------------------------------

    def _x(self, seconds: float) -> float:
        width = self.width() - 2 * MARGIN
        return MARGIN + (seconds - self.view_start) / (self.view_end - self.view_start) * width

    def _time(self, x: float) -> float:
        width = max(1, self.width() - 2 * MARGIN)
        fraction = min(1.0, max(0.0, (x - MARGIN) / width))
        return self.view_start + fraction * (self.view_end - self.view_start)

    def _bar_y(self) -> float:
        return ICON_SIZE + 10

    # ---- painting -------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bar_y = self._bar_y()
        left, right = MARGIN, self.width() - MARGIN
        head = self._x(self.position)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(BACKGROUND)
        p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 4, 4)
        p.setBrush(TRACK)
        p.drawRoundedRect(QRectF(left, bar_y, right - left, BAR_HEIGHT), 3, 3)
        played = min(max(head, left), right)
        p.setBrush(PLAYED)
        p.drawRoundedRect(QRectF(left, bar_y, played - left, BAR_HEIGHT), 3, 3)

        for badge in self.badges:
            if not self.view_start <= badge.time <= self.view_end:
                continue
            x = self._x(badge.time)
            if badge.selected:
                p.setPen(QPen(SELECTED, 2))
                p.drawLine(QPointF(x, ICON_SIZE + 2), QPointF(x, bar_y + BAR_HEIGHT))
                p.drawPixmap(int(x - ICON_SIZE / 2), 1, icon_pixmap(badge.icon, ICON_SIZE))
            else:
                p.setPen(QPen(MUTED, 1))
                p.drawLine(QPointF(x, bar_y - 7), QPointF(x, bar_y + BAR_HEIGHT))

        if left <= head <= right:
            p.setPen(QPen(PLAYHEAD, 2))
            p.drawLine(QPointF(head, 0), QPointF(head, bar_y + BAR_HEIGHT + 4))
            p.setBrush(PLAYHEAD)
            p.drawEllipse(QPointF(head, bar_y + BAR_HEIGHT / 2), 5, 5)

        # Start and end time of the visible window.
        p.setPen(LABEL)
        text_y = int(bar_y + BAR_HEIGHT + 4)
        rect_h = self.height() - text_y
        p.drawText(QRectF(left, text_y, 200, rect_h), Qt.AlignmentFlag.AlignLeft, fmt(self.view_start))
        p.drawText(QRectF(right - 200, text_y, 200, rect_h), Qt.AlignmentFlag.AlignRight, fmt(self.view_end))
        p.end()

    # ---- mouse ----------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = True
            self._seek_to(event.position().x())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        x = event.position().x()
        top = self.mapToGlobal(QPoint(int(x), 0))
        self.hovered.emit(self._time(x), top, self._badge_near(x))
        if self.dragging:
            self._seek_to(x)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self.dragging = False

    def leaveEvent(self, event: QEvent) -> None:
        if not self.dragging:
            self.hover_left.emit()

    def wheelEvent(self, event: QWheelEvent) -> None:
        steps = event.angleDelta().y() / 120 or event.angleDelta().x() / 120
        if not steps:
            return
        span = self.view_end - self.view_start
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            shift = -steps * span * 0.1
            self.set_view(self.view_start + shift, self.view_end + shift)
        else:
            anchor = self._time(event.position().x())
            new_span = span / (ZOOM_STEP ** steps)
            fraction = (anchor - self.view_start) / span
            self.set_view(anchor - fraction * new_span, anchor + (1 - fraction) * new_span)
        event.accept()

    def _badge_near(self, x: float) -> str:
        near = [b for b in self.badges
                if self.view_start <= b.time <= self.view_end
                and abs(self._x(b.time) - x) <= BADGE_HOVER_PIXELS]
        if not near:
            return ""
        return min(near, key=lambda b: (not b.selected, abs(self._x(b.time) - x))).title

    def _seek_to(self, x: float) -> None:
        seconds = self._time(x)
        self.set_position(seconds)
        self.seek_requested.emit(seconds)
