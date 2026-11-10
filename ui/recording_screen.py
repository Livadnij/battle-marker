"""Second screen. Player with a badge timeline, scanning and the badge list for one recording."""

from PySide6.QtCore import QPoint, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QBrush, QFont, QImage, QKeySequence, QPalette, QPixmap, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QCheckBox, QGroupBox, QHBoxLayout, QLabel, QMessageBox, QProgressBar,
    QPushButton, QScrollBar, QSlider, QSplitter, QVBoxLayout, QWidget,
)

from service.badges import Badge, list_badges
from service.errors import ServiceError
from service.mark import MarkPlan, plan_marks, write_marks
from service.playlist import Playback, build_playback
from service.preview import chunk_at
from service.scan import ScanProgress, ScanResult
from service.sessions import SessionInfo, describe
from service.timefmt import fmt
from storage.settings import get_settings
from ui.common import duration, item, table
from ui.player.preview import PreviewCache, PreviewPopup, PreviewWorker
from ui.player.icons import icon_pixmap
from ui.player.timeline import TimelineBadge, TimelineBar
from ui.workers import ScanWorker, start_in_thread

BADGE_COLUMNS = ["Time", "Badge"]
BADGE_ICON_SIZE = 18
SKIP_SECONDS = 5
JUMP_LEAD_SECONDS = 2  # a badge click starts playback this long before the badge
SEEK_DEBOUNCE_MS = 120  # dragging the timeline seeks at most this often
SIDE_PANEL_WIDTH = 420


class RecordingScreen(QWidget):
    back_requested = Signal()
    recording_changed = Signal()  # scan or write changed what the list screen shows

    def __init__(self) -> None:
        super().__init__()
        self.info: SessionInfo | None = None
        self.playback: Playback | None = None
        self.badges: list[Badge] = []
        self.plan: MarkPlan | None = None
        self.steam_running = False
        self.write_pending = False
        self.scan_thread: QThread | None = None
        self.scan_worker: ScanWorker | None = None
        self._pending_seek: float | None = None
        self._reloaded_after_error = False

        self._build_player()
        self._build()
        self._build_shortcuts()
        self._build_preview()

    # ---- layout ---------------------------------------------------------

    def _build_player(self) -> None:
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.video = QVideoWidget()
        self.video.setStyleSheet("background-color: black;")
        self.player.setVideoOutput(self.video)
        self.player.positionChanged.connect(self._on_position)
        self.player.playbackStateChanged.connect(self._on_playback_state)
        self.player.errorOccurred.connect(self._on_media_error)
        self.seek_timer = QTimer(self)
        self.seek_timer.setSingleShot(True)
        self.seek_timer.timeout.connect(self._apply_seek)

    def _build(self) -> None:
        self.back_button = QPushButton("< Recordings")
        self.back_button.clicked.connect(self.back_requested.emit)
        self.title = QLabel("")
        self.steam_label = QLabel("")
        top = QHBoxLayout()
        top.addWidget(self.back_button)
        top.addWidget(self.title, 1)
        top.addWidget(self.steam_label)

        self.play_button = QPushButton("Play")
        self.play_button.clicked.connect(self.toggle_play)
        self.time_label = QLabel("")
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(60)
        self.volume.setFixedWidth(110)
        self.volume.valueChanged.connect(lambda v: self.audio.setVolume(v / 100))
        self.audio.setVolume(0.6)
        controls = QHBoxLayout()
        controls.addWidget(self.play_button)
        controls.addWidget(self.time_label)
        controls.addStretch()
        controls.addWidget(QLabel("Volume"))
        controls.addWidget(self.volume)
        self.timeline = TimelineBar()
        self.timeline.seek_requested.connect(self._request_seek)
        self.timeline_scroll = QScrollBar(Qt.Orientation.Horizontal)
        self.timeline.view_changed.connect(self._on_view_changed)
        self.timeline_scroll.valueChanged.connect(self._on_scroll)
        self.view_hint = QLabel("Wheel zooms the timeline, Shift+wheel or the bar below scrolls it.")
        self.view_hint.setStyleSheet("color: gray;")
        self.media_status = QLabel("")

        player_column = QWidget()
        player_layout = QVBoxLayout(player_column)
        player_layout.setContentsMargins(0, 0, 0, 0)
        player_layout.addWidget(self.video, 1)
        player_layout.addWidget(self.timeline)
        player_layout.addWidget(self.timeline_scroll)
        player_layout.addLayout(controls)
        player_layout.addWidget(self.media_status)
        player_layout.addWidget(self.view_hint)

        self.scan_button = QPushButton("Scan")
        self.scan_button.clicked.connect(self.start_scan)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel_scan)
        self.gpu_box = QCheckBox("GPU decoding")
        self.gpu_box.setChecked(True)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        self.scan_status = QLabel("")
        self.scan_status.setWordWrap(True)
        scan_buttons = QHBoxLayout()
        scan_buttons.addWidget(self.scan_button)
        scan_buttons.addWidget(self.cancel_button)
        scan_buttons.addStretch()
        scan_buttons.addWidget(self.gpu_box)
        scan_group = QGroupBox("Scan")
        scan_layout = QVBoxLayout(scan_group)
        scan_layout.addLayout(scan_buttons)
        scan_layout.addWidget(self.progress)
        scan_layout.addWidget(self.scan_status)

        self.badge_table = table(BADGE_COLUMNS, stretch_column=1)
        self.badge_table.cellClicked.connect(self._on_badge_clicked)
        self.badge_summary = QLabel("")
        self.badge_summary.setWordWrap(True)
        self.write_button = QPushButton("Write markers")
        self.write_button.clicked.connect(self.on_write_clicked)
        badge_group = QGroupBox("Badges")
        badge_layout = QVBoxLayout(badge_group)
        badge_layout.addWidget(self.badge_table, 1)
        badge_layout.addWidget(self.badge_summary)
        badge_layout.addWidget(self.write_button)

        side = QWidget()
        side.setMinimumWidth(SIDE_PANEL_WIDTH)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.addWidget(scan_group)
        side_layout.addWidget(badge_group, 1)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(player_column)
        splitter.addWidget(side)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(splitter, 1)

    def _build_preview(self) -> None:
        self.preview_popup = PreviewPopup(self)
        self.preview_cache = PreviewCache()
        self.preview_worker = PreviewWorker()
        self.preview_worker.ready.connect(self._on_preview_ready)
        self.preview_thread = QThread()
        self.preview_worker.moveToThread(self.preview_thread)
        self.preview_thread.start()
        self._hover: tuple[int, QPoint, str] | None = None  # chunk, point, popup text
        self.timeline.hovered.connect(self._on_timeline_hover)
        self.timeline.hover_left.connect(self._hide_preview)

    def _on_timeline_hover(self, seconds: float, point: QPoint, badge: str) -> None:
        if self.info is None or self.playback is None:
            return
        chunk = chunk_at(self.info.session, seconds)
        if chunk is None:
            self._hide_preview()
            return
        text = f"{fmt(seconds)}  ·  {badge}" if badge else fmt(seconds)
        self._hover = (chunk, point, text)
        pixmap = self.preview_cache.get((self.info.name, chunk))
        self.preview_popup.show_at(point.x(), point.y(), text, pixmap)
        if pixmap is None:
            self.preview_worker.request(self.info.session, chunk)

    def _on_preview_ready(self, name: str, chunk: int, image: QImage) -> None:
        pixmap = QPixmap.fromImage(image)
        self.preview_cache.put((name, chunk), pixmap)
        if self.info is not None and self.info.name == name and self._hover and self._hover[0] == chunk:
            _, point, text = self._hover
            if self.preview_popup.isVisible():
                self.preview_popup.show_at(point.x(), point.y(), text, pixmap)

    def _hide_preview(self) -> None:
        self._hover = None
        self.preview_popup.hide()

    def _build_shortcuts(self) -> None:
        context = Qt.ShortcutContext.WidgetWithChildrenShortcut
        for key, action in (
            (Qt.Key.Key_Space, self.toggle_play),
            (Qt.Key.Key_Left, lambda: self._skip(-SKIP_SECONDS)),
            (Qt.Key.Key_Right, lambda: self._skip(SKIP_SECONDS)),
        ):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(context)
            shortcut.activated.connect(action)

    # ---- opening and closing --------------------------------------------

    def open(self, info: SessionInfo) -> None:
        self.close_recording()
        self.info = info
        self.write_pending = False
        length = duration(info.length) if info.length else "video deleted"
        started = info.started.strftime("%Y-%m-%d %H:%M") if info.started else ""
        self.title.setText(f"<b>{info.game}</b>  ·  {started}  ·  {length}")
        self.progress.setValue(1000 if info.scanned else 0)
        self.gpu_box.setChecked(get_settings().gpu_decoding)
        if not info.supported:
            self.scan_status.setText("battle-marker only recognises badges from supported games. "
                                     "This recording can't be scanned.")
        else:
            self.scan_status.setText("" if info.scanned else "Not scanned yet.")
        self._load_video()
        self._load_badges()
        self._update_controls()
        self.setFocus()

    def close_recording(self) -> None:
        """Stops playback and lets go of the chunk files."""
        self._hide_preview()
        self.player.stop()
        self.player.setSource(QUrl())
        self.playback = None

    def _load_video(self, at: float | None = None) -> None:
        self.playback = build_playback(self.info.session)
        if self.playback is None:
            self.media_status.setText("Steam has deleted the video of this recording.")
            self.timeline.set_range(0, 1)
            self.timeline.set_position(0)
            self._update_time_label(0)
            return
        self.media_status.setText("" if self.playback.has_audio else "This recording has no audio.")
        self.timeline.set_range(self.playback.starts_at, self.playback.starts_at + self.playback.length)
        self.player.setSource(QUrl.fromLocalFile(str(self.playback.master)))
        self._seek(at if at is not None else self.playback.starts_at)

    # ---- playback -------------------------------------------------------

    def toggle_play(self) -> None:
        if self.playback is None:
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _skip(self, seconds: float) -> None:
        if self.playback is not None:
            self._seek(self._current_time() + seconds)

    def _current_time(self) -> float:
        if self.playback is None:
            return 0.0
        return self.playback.starts_at + self.player.position() / 1000

    def _seek(self, timeline_seconds: float) -> None:
        if self.playback is None:
            return
        start = self.playback.starts_at
        clamped = min(max(timeline_seconds, start), start + self.playback.length - 0.5)
        self.player.setPosition(int((clamped - start) * 1000))
        self.timeline.set_position(clamped, follow=True)
        self._update_time_label(clamped)

    def _request_seek(self, timeline_seconds: float) -> None:
        # Dragging produces many positions. Only the latest one is applied.
        self._pending_seek = timeline_seconds
        self._update_time_label(timeline_seconds)
        if not self.seek_timer.isActive():
            self.seek_timer.start(SEEK_DEBOUNCE_MS)

    def _apply_seek(self) -> None:
        if self._pending_seek is not None:
            self._seek(self._pending_seek)
            self._pending_seek = None

    def _on_position(self, ms: int) -> None:
        if self.playback is None or self.seek_timer.isActive() or self.timeline.dragging:
            return
        seconds = self.playback.starts_at + ms / 1000
        playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        self.timeline.set_position(seconds, follow=playing)
        self._update_time_label(seconds)
        self._reloaded_after_error = False

    def _update_time_label(self, seconds: float) -> None:
        if self.playback is None:
            self.time_label.setText("")
            return
        end = self.playback.starts_at + self.playback.length
        self.time_label.setText(f"{fmt(seconds)} / {fmt(end)}")

    def _on_playback_state(self, state) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.play_button.setText("Pause" if playing else "Play")

    def _on_media_error(self, error, message: str) -> None:
        # Usually Steam deleted chunks the playlist still lists. Rebuild it once and carry on.
        if self.info is not None and not self._reloaded_after_error:
            self._reloaded_after_error = True
            position = self._current_time()
            self._load_video(at=position)
            return
        self.media_status.setText(f"Playback error. {message}")

    # ---- badges and markers ---------------------------------------------

    def _load_badges(self) -> None:
        self.badges = []
        self.plan = None
        if self.info is not None and self.info.scanned:
            try:
                self.badges = list_badges(self.info.session) or []
                self.plan = plan_marks(self.info.session)
            except ServiceError as e:
                self.scan_status.setText(str(e))
            except Exception as e:
                QMessageBox.warning(self, "Could not read the scan", str(e))
        self._show_badges()

    def _show_badges(self) -> None:
        muted = QBrush(self.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text))
        italic = QFont()
        italic.setItalic(True)
        self.badge_table.setRowCount(len(self.badges))
        for row, badge in enumerate(self.badges):
            cells = [item(fmt(badge.time)), self._title_item(badge)]
            for col, cell in enumerate(cells):
                if not badge.selected:
                    cell.setForeground(muted)
                    cell.setFont(italic)
                    cell.setToolTip("No rule picks this badge.")
                self.badge_table.setItem(row, col, cell)
        self.timeline.set_badges([
            TimelineBadge(b.time, b.selected, b.rule.icon if b.rule else "", b.title)
            for b in self.badges
        ])

        if self.info is None or not self.info.scanned:
            self.badge_summary.setText("Scan the recording to find its badges.")
        else:
            selected = sum(b.selected for b in self.badges)
            new = len(self.plan.new) if self.plan else 0
            self.badge_summary.setText(
                f"{len(self.badges)} badges, {selected} picked by rules. "
                f"{new} new markers to write."
            )
        self._update_controls()

    def _title_item(self, badge: Badge):
        """Badge text with the marker icon in front. Badges no rule picks get an empty space, so texts line up."""
        cell = item(badge.title)
        if badge.rule is not None:
            color = self.palette().color(QPalette.ColorRole.Text)
            icon = icon_pixmap(badge.rule.icon, BADGE_ICON_SIZE, color)
        else:
            icon = QPixmap(BADGE_ICON_SIZE, BADGE_ICON_SIZE)
            icon.fill(Qt.GlobalColor.transparent)
        cell.setData(Qt.ItemDataRole.DecorationRole, icon)
        return cell

    def _on_view_changed(self, view_start: float, view_end: float) -> None:
        # Scrollbar units are tenths of a second.
        span = view_end - view_start
        full = self.timeline.end - self.timeline.start
        self.timeline_scroll.blockSignals(True)
        self.timeline_scroll.setRange(0, int((full - span) * 10))
        self.timeline_scroll.setPageStep(max(1, int(span * 10)))
        self.timeline_scroll.setSingleStep(max(1, int(span)))
        self.timeline_scroll.setValue(int((view_start - self.timeline.start) * 10))
        self.timeline_scroll.blockSignals(False)
        self.timeline_scroll.setVisible(full - span > 0.5)

    def _on_scroll(self, value: int) -> None:
        span = self.timeline.view_end - self.timeline.view_start
        view_start = self.timeline.start + value / 10
        self.timeline.set_view(view_start, view_start + span)

    def _on_badge_clicked(self, row: int, _column: int) -> None:
        if row < len(self.badges):
            self._seek(self.badges[row].time - JUMP_LEAD_SECONDS)

    def on_write_clicked(self) -> None:
        if self.write_pending:
            self.write_pending = False
        elif self.steam_running:
            self.write_pending = True
        else:
            self._write()
        self._update_controls()

    def _write(self) -> None:
        self.write_pending = False
        if self.plan is None or not self.plan.new:
            return
        try:
            written, backup = write_marks(self.plan)
        except Exception as e:
            QMessageBox.warning(self, "Markers not written", str(e))
            return
        self._refresh_info()
        QMessageBox.information(
            self, "Markers written",
            f"Wrote {written} markers.\nStart Steam to see them.\n\nBackup of the old timeline:\n{backup}",
        )

    def _refresh_info(self) -> None:
        if self.info is not None:
            self.info = describe(self.info.session)
        self._load_badges()
        self.recording_changed.emit()

    def set_steam_running(self, running: bool) -> None:
        self.steam_running = running
        self.steam_label.setText("Steam is running" if running else "Steam is closed")
        if not running and self.write_pending:
            self._write()
        self._update_controls()

    # ---- scanning -------------------------------------------------------

    def start_scan(self) -> None:
        if self.info is None or self.scan_thread is not None:
            return
        self.progress.setValue(0)
        self.scan_status.setText("Starting...")
        self.scan_worker = ScanWorker(self.info.session, self.gpu_box.isChecked())
        self.scan_worker.progress.connect(self._on_scan_progress)
        self.scan_worker.finished.connect(self._on_scan_finished)
        self.scan_worker.failed.connect(self._on_scan_failed)
        self.scan_thread = start_in_thread(self.scan_worker, "run")
        self._update_controls()

    def cancel_scan(self) -> None:
        if self.scan_worker is not None:
            self.scan_worker.stop()
            self.scan_status.setText("Stopping...")

    def _on_scan_progress(self, p: ScanProgress) -> None:
        self.progress.setValue(int(p.fraction * 1000))
        self.scan_status.setText(
            f"{p.fraction:.0%}  ·  {p.badges} badges  ·  {p.speed:.1f}x realtime  ·  "
            f"{p.parts} parts at once"
        )

    def _on_scan_finished(self, result: ScanResult) -> None:
        reached = self.progress.value()
        self._end_scan()
        self._refresh_info()
        verb = "Stopped after" if result.cancelled else "Scanned"
        self.scan_status.setText(
            f"{verb} {fmt(result.video_seconds)} of video in {fmt(result.elapsed)}. "
            f"{len(result.appearances)} badges found."
        )
        self.progress.setValue(reached if result.cancelled else 1000)

    def _on_scan_failed(self, message: str) -> None:
        self._end_scan()
        self.scan_status.setText("Scan failed.")
        QMessageBox.warning(self, "Scan failed", message)

    def _end_scan(self) -> None:
        if self.scan_thread is not None:
            self.scan_thread.quit()
            self.scan_thread.wait()
        # This runs inside the worker's own signal. The references are released
        # on the next event loop turn so Qt never deletes it mid-delivery.
        QTimer.singleShot(0, self._release_scan)

    def _release_scan(self) -> None:
        self.scan_thread = None
        self.scan_worker = None
        self._update_controls()

    @property
    def scanning(self) -> bool:
        return self.scan_thread is not None

    # ---- state ----------------------------------------------------------

    def _update_controls(self) -> None:
        scanning = self.scanning
        info = self.info
        can_scan = info is not None and info.supported and info.covers_from is not None
        self.back_button.setEnabled(not scanning)
        self.scan_button.setEnabled(can_scan and not scanning)
        self.scan_button.setText("Rescan" if info is not None and info.scanned else "Scan")
        self.cancel_button.setEnabled(scanning)
        self.gpu_box.setEnabled(not scanning)
        self.play_button.setEnabled(self.playback is not None)

        can_write = self.plan is not None and bool(self.plan.new) and not scanning
        self.write_button.setEnabled(can_write or self.write_pending)
        if self.write_pending:
            self.write_button.setText("Waiting for Steam to close... (click to cancel)")
        elif can_write and self.steam_running:
            self.write_button.setText("Write when Steam closes")
        else:
            self.write_button.setText("Write markers")

    def shutdown(self) -> None:
        self.preview_thread.quit()
        self.preview_thread.wait()
        if self.scan_worker is not None:
            self.scan_worker.stop()
        if self.scan_thread is not None:
            self.scan_thread.quit()
            self.scan_thread.wait()
        self.close_recording()
