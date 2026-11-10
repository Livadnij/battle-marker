"""First screen. Every recording Steam still has, double-click one to open it."""

from PySide6.QtCore import QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QBrush, QPalette, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from service.sessions import SessionInfo, list_sessions
from service.thumbnails import thumbnail_path
from service.timefmt import fmt
from ui.common import duration, item, table
from ui.rules_dialog import RulesDialog
from ui.settings_dialog import SettingsDialog
from ui.workers import ThumbnailWorker, start_in_thread

COLUMNS = ["Preview", "Game", "Started", "Length", "Video covers", "Scanned", "Timeline entries"]
PREVIEW_SIZE = QSize(160, 90)


class RecordingsScreen(QWidget):
    open_requested = Signal(object)  # SessionInfo

    def __init__(self) -> None:
        super().__init__()
        self.sessions: list[SessionInfo] = []
        self.thumb_jobs: list[tuple[QThread, ThumbnailWorker]] = []

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        self.rules_button = QPushButton("Rules...")
        self.rules_button.clicked.connect(self._edit_rules)
        self.settings_button = QPushButton("Settings...")
        self.settings_button.clicked.connect(self._edit_settings)
        self.hint = QLabel("Double-click a recording to open it.")
        self.steam_label = QLabel("")
        top = QHBoxLayout()
        top.addWidget(self.refresh_button)
        top.addWidget(self.rules_button)
        top.addWidget(self.settings_button)
        top.addWidget(self.hint)
        top.addStretch()
        top.addWidget(self.steam_label)

        self.table = table(COLUMNS, stretch_column=1)
        self.table.setIconSize(PREVIEW_SIZE)
        self.table.verticalHeader().setDefaultSectionSize(PREVIEW_SIZE.height() + 8)
        self.table.cellDoubleClicked.connect(self._on_double_click)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.table, 1)

    def _edit_rules(self) -> None:
        RulesDialog(self).exec()

    def _edit_settings(self) -> None:
        if SettingsDialog(self).exec():
            self.refresh()

    def set_steam_running(self, running: bool) -> None:
        self.steam_label.setText("Steam is running" if running else "Steam is closed")

    def refresh(self) -> None:
        selected = self._selected_name()
        try:
            infos = list_sessions()
        except Exception as e:
            QMessageBox.warning(self, "Could not read recordings", str(e))
            infos = []
        self.sessions = sorted(infos, key=lambda i: i.name.split("_", 2)[-1], reverse=True)

        muted = QBrush(self.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text))
        self.table.setRowCount(len(self.sessions))
        row_to_select = 0
        for row, info in enumerate(self.sessions):
            covers = "Video deleted"
            if info.covers_from is not None:
                covers = f"{fmt(info.covers_from)} to {fmt(info.covers_to)}"
            game = info.game if info.supported else f"{info.game} (unsupported game)"
            cells = [
                item(""),
                item(game),
                item(info.started.strftime("%Y-%m-%d %H:%M") if info.started else ""),
                item(duration(info.length) if info.length else "", align_right=True),
                item(covers),
                item("Yes" if info.scanned else "No"),
                item(str(info.timeline_entries), align_right=True),
            ]
            for col, cell in enumerate(cells):
                if not info.supported:
                    cell.setForeground(muted)
                self.table.setItem(row, col, cell)
            self._set_preview(row, thumbnail_path(info.session))
            if info.name == selected:
                row_to_select = row
        if self.sessions:
            self.table.selectRow(row_to_select)
        self._start_thumbnails()

    def _selected_name(self) -> str | None:
        rows = self.table.selectionModel().selectedRows()
        if rows and rows[0].row() < len(self.sessions):
            return self.sessions[rows[0].row()].name
        return None

    def _on_double_click(self, row: int, _column: int) -> None:
        if row < len(self.sessions):
            self.open_requested.emit(self.sessions[row])

    # ---- previews -------------------------------------------------------

    def _set_preview(self, row: int, path) -> None:
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            return
        scaled = pixmap.scaled(PREVIEW_SIZE, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
        self.table.item(row, 0).setData(Qt.ItemDataRole.DecorationRole, scaled)

    def _start_thumbnails(self) -> None:
        missing = [i.session for i in self.sessions
                   if i.covers_from is not None and not thumbnail_path(i.session).exists()]
        if not missing:
            return
        for _, worker in self.thumb_jobs:
            worker.stop()  # an older job would only redo the same previews
        worker = ThumbnailWorker(missing)
        # Bound methods of this widget run in the UI thread, queued after the signal.
        worker.ready.connect(self._on_thumbnail)
        worker.done.connect(self._on_thumbnails_done)
        thread = start_in_thread(worker, "run")
        self.thumb_jobs.append((thread, worker))

    def _on_thumbnail(self, name: str, path: str) -> None:
        for row, info in enumerate(self.sessions):
            if info.name == name:
                self._set_preview(row, path)

    def _on_thumbnails_done(self) -> None:
        # Released on the next event loop turn, never inside the worker's own signal.
        QTimer.singleShot(0, self._release_thumbnails)

    def _release_thumbnails(self) -> None:
        still_running = []
        for thread, worker in self.thumb_jobs:
            if worker.finished_work:
                thread.quit()
                thread.wait()
            else:
                still_running.append((thread, worker))
        self.thumb_jobs = still_running

    def shutdown(self) -> None:
        for thread, worker in self.thumb_jobs:
            worker.stop()
            thread.quit()
            thread.wait()
