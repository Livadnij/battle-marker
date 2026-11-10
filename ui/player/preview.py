"""Hover preview above the timeline, like the small frame Steam shows on its scrub bar."""

from collections import OrderedDict

from PySide6.QtCore import QObject, QPoint, Qt, Signal, Slot
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from recording.session import Session
from service.preview import PREVIEW_HEIGHT, PREVIEW_WIDTH, keyframe_rgb

CACHE_SIZE = 400  # previews kept in memory, about 170 KB each


class PreviewWorker(QObject):
    """Decodes previews in its own thread. Only the newest request is worked on."""

    ready = Signal(str, int, QImage)  # session name, chunk, image
    wake = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._wanted: tuple[Session, int] | None = None
        self.wake.connect(self._work)

    def request(self, session: Session, chunk: int) -> None:
        # Called from the UI thread. A plain assignment, the worker reads the latest value.
        self._wanted = (session, chunk)
        self.wake.emit()

    @Slot()
    def _work(self) -> None:
        wanted, self._wanted = self._wanted, None
        if wanted is None:
            return  # an earlier wake already handled this request
        session, chunk = wanted
        rgb = keyframe_rgb(session, chunk)
        if rgb is not None:
            image = QImage(rgb, PREVIEW_WIDTH, PREVIEW_HEIGHT, PREVIEW_WIDTH * 3,
                           QImage.Format.Format_RGB888).copy()
            self.ready.emit(session.name, chunk, image)


class PreviewPopup(QWidget):
    """Frameless box with the frame and the time, drawn above the timeline."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent, Qt.WindowType.ToolTip)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.image = QLabel()
        self.image.setFixedSize(PREVIEW_WIDTH, PREVIEW_HEIGHT)
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setStyleSheet("background-color: black; color: #aaa;")
        self.time = QLabel()
        self.time.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)
        layout.addWidget(self.image)
        layout.addWidget(self.time)
        self.setStyleSheet("PreviewPopup { background-color: #202020; border: 1px solid #555; }"
                           "QLabel { color: white; }")

    def show_at(self, global_x: int, timeline_top: int, text: str, pixmap: QPixmap | None) -> None:
        self.time.setText(text)
        if pixmap is None:
            self.image.setPixmap(QPixmap())
            self.image.setText("...")
        else:
            self.image.setPixmap(pixmap)
        self.adjustSize()
        self.move(QPoint(global_x - self.width() // 2, timeline_top - self.height() - 6))
        self.show()


class PreviewCache:
    """Recently decoded previews by (session name, chunk), oldest dropped first."""

    def __init__(self) -> None:
        self._items: OrderedDict[tuple[str, int], QPixmap] = OrderedDict()

    def get(self, key: tuple[str, int]) -> QPixmap | None:
        pixmap = self._items.get(key)
        if pixmap is not None:
            self._items.move_to_end(key)
        return pixmap

    def put(self, key: tuple[str, int], pixmap: QPixmap) -> None:
        self._items[key] = pixmap
        self._items.move_to_end(key)
        while len(self._items) > CACHE_SIZE:
            self._items.popitem(last=False)
