"""Draws the playback position as a line between two rows of the badge list.

The line sits on the top edge of the next badge that has not been reached, with a
small arrow centered on it in the first column. After the last badge it sits on the
bottom edge of the last row. Nothing is inserted into the table, so rows never move
and their numbers keep matching the badge list.

The arrow reaches into the row above the line, so that row paints its own half. A
repaint of one row alone, like the selection moving to it, then never wipes half of
the arrow.
"""

from PySide6.QtCore import QModelIndex, QPointF
from PySide6.QtGui import QPainter, QPolygonF
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem

from ui.player.timeline import PLAYED

LINE_WIDTH = 2
ARROW_SIZE = 9


class PlayheadLineDelegate(QStyledItemDelegate):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.line_row = -1  # the line sits above this row, row count means below the last row

    def set_line_row(self, row: int) -> bool:
        """Returns True when the line moved, so the caller knows to repaint."""
        changed = row != self.line_row
        self.line_row = row
        return changed

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        super().paint(painter, option, index)
        row, rows = index.row(), index.model().rowCount()
        above = row == self.line_row
        below = row == rows - 1 and self.line_row == rows
        before = row == self.line_row - 1  # the row just above the line
        if not (above or below or before):
            return
        rect = option.rect
        painter.save()
        if above:
            painter.fillRect(rect.left(), rect.top(), rect.width(), LINE_WIDTH, PLAYED)
            line_center = rect.top() + LINE_WIDTH / 2
        elif below:
            line_top = rect.bottom() - LINE_WIDTH + 1
            painter.fillRect(rect.left(), line_top, rect.width(), LINE_WIDTH, PLAYED)
            line_center = line_top + LINE_WIDTH / 2
        else:
            line_center = self._row_top(option, self.line_row, rect.bottom() + 2) + LINE_WIDTH / 2
        if index.column() == 0:
            self._draw_arrow(painter, option, rect, line_center, unclipped=below)
        painter.restore()

    @staticmethod
    def _row_top(option: QStyleOptionViewItem, row: int, fallback: int) -> int:
        table = option.widget
        return table.rowViewportPosition(row) if table is not None else fallback

    @staticmethod
    def _draw_arrow(painter: QPainter, option: QStyleOptionViewItem, rect, line_center: float, unclipped: bool) -> None:
        half = ARROW_SIZE / 2
        table = option.widget
        # At the very top or bottom of the view a centered arrow would be cut in half, so it slides inside.
        if table is not None:
            line_center = min(max(line_center, half), table.viewport().height() - half)
        if not unclipped:
            painter.setClipRect(rect)
        left = rect.left() + 1
        painter.setBrush(PLAYED)
        painter.setPen(PLAYED)
        painter.drawPolygon(QPolygonF([
            QPointF(left, line_center - half),
            QPointF(left + ARROW_SIZE * 0.8, line_center),
            QPointF(left, line_center + half),
        ]))
