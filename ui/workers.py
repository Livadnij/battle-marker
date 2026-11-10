"""Background work for the window, so scanning and process checks never freeze it."""

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot

from markers.writer import steam_running
from recording.session import Session
from service.scan import ScanProgress, scan_session
from service.thumbnails import make_thumbnail

# How often the Steam process check runs.
STEAM_POLL_MS = 3000


class ScanWorker(QObject):
    """Runs one scan. Lives in its own QThread for as long as the scan lasts."""

    progress = Signal(object)  # ScanProgress
    finished = Signal(object)  # ScanResult
    failed = Signal(str)

    def __init__(self, session: Session, gpu: bool) -> None:
        super().__init__()
        self.session = session
        self.gpu = gpu
        self._stop = False

    def stop(self) -> None:
        # Read by the scan loop between frames, so a plain flag is enough.
        self._stop = True

    @Slot()
    def run(self) -> None:
        try:
            result = scan_session(
                self.session,
                gpu=self.gpu,
                on_progress=self._report,
                should_stop=lambda: self._stop,
                progress_interval=0.5,
            )
        except Exception as e:  # shown to the user, the thread must not die silently
            self.failed.emit(str(e))
        else:
            self.finished.emit(result)

    def _report(self, p: ScanProgress) -> None:
        self.progress.emit(p)


class ThumbnailWorker(QObject):
    """Creates missing recording previews one by one and reports each one."""

    ready = Signal(str, str)  # session name, image path
    done = Signal()

    def __init__(self, sessions: list[Session]) -> None:
        super().__init__()
        self.sessions = sessions
        self._stop = False
        self.finished_work = False

    def stop(self) -> None:
        self._stop = True

    @Slot()
    def run(self) -> None:
        self._make_all()
        self.finished_work = True
        self.done.emit()

    def _make_all(self) -> None:
        for session in self.sessions:
            if self._stop:
                break
            try:
                path = make_thumbnail(session)
            except Exception:  # a missing preview is not worth bothering the user
                path = None
            if path is not None:
                self.ready.emit(session.name, str(path))


class SteamWatcher(QObject):
    """Polls for steam.exe in its own thread and reports changes."""

    changed = Signal(bool)  # True while Steam is running

    def __init__(self) -> None:
        super().__init__()
        self._running: bool | None = None
        self._timer: QTimer | None = None

    @Slot()
    def start(self) -> None:
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._check)
        self._timer.start(STEAM_POLL_MS)
        self._check()

    @Slot()
    def stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()

    @Slot()
    def _check(self) -> None:
        running = steam_running()
        if running != self._running:
            self._running = running
            self.changed.emit(running)


def start_in_thread(worker: QObject, entry: str) -> QThread:
    """Moves a worker to a new thread and calls its entry slot when the thread starts."""
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(getattr(worker, entry))
    thread.start()
    return thread
