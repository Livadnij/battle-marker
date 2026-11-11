"""Draws the playback position as a line between two rows of the badge list.

The line sits on the top edge of the next badge that has not been reached, with a
small arrow in the first column. After the last badge it sits on the bottom edge
of the last row. Nothing is inserted into the table, so rows never move and
their numbers keep matching the badge list.
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
        if not (above or below):
            return
        rect = option.rect
        y = rect.top() if above else rect.bottom() - LINE_WIDTH + 1
        painter.save()
        painter.fillRect(rect.left(), y, rect.width(), LINE_WIDTH, PLAYED)
        if index.column() == 0:
            top = y + LINE_WIDTH if above else y - ARROW_SIZE
            painter.setBrush(PLAYED)
            painter.setPen(PLAYED)
            painter.drawPolygon(QPolygonF([
                QPointF(rect.left() + 1, top),
                QPointF(rect.left() + 1 + ARROW_SIZE * 0.8, top + ARROW_SIZE / 2),
                QPointF(rect.left() + 1, top + ARROW_SIZE),
            ]))
        painter.restore()
