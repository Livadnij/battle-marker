"""Main window. Switches between the recordings list and one opened recording."""

from PySide6.QtCore import QMetaObject, Qt
from PySide6.QtWidgets import QMainWindow, QStackedWidget

from service.sessions import SessionInfo
from ui.recording_screen import RecordingScreen
from ui.recordings_screen import RecordingsScreen
from ui.workers import SteamWatcher, start_in_thread

WINDOW_TITLE = "battle-marker"
WINDOW_SIZE = (1400, 860)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(*WINDOW_SIZE)

        self.list_screen = RecordingsScreen()
        self.recording_screen = RecordingScreen()
        self.stack = QStackedWidget()
        self.stack.addWidget(self.list_screen)
        self.stack.addWidget(self.recording_screen)
        self.setCentralWidget(self.stack)

        self.list_screen.open_requested.connect(self.open_recording)
        self.recording_screen.back_requested.connect(self.show_list)
        self.recording_screen.recording_changed.connect(self.list_screen.refresh)

        self.steam_watcher = SteamWatcher()
        self.steam_watcher.changed.connect(self._on_steam_changed)
        self.steam_thread = start_in_thread(self.steam_watcher, "start")

        self.list_screen.refresh()

    def open_recording(self, info: SessionInfo) -> None:
        self.recording_screen.open(info)
        self.stack.setCurrentWidget(self.recording_screen)

    def show_list(self) -> None:
        self.recording_screen.close_recording()
        self.stack.setCurrentWidget(self.list_screen)

    def _on_steam_changed(self, running: bool) -> None:
        self.list_screen.set_steam_running(running)
        self.recording_screen.set_steam_running(running)

    def closeEvent(self, event) -> None:
        self.list_screen.shutdown()
        self.recording_screen.shutdown()
        QMetaObject.invokeMethod(self.steam_watcher, "stop", Qt.ConnectionType.BlockingQueuedConnection)
        self.steam_thread.quit()
        self.steam_thread.wait()
        super().closeEvent(event)
