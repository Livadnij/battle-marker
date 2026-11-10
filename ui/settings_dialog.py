"""Settings a user changes, stored in the database."""

from dataclasses import replace
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from storage.settings import get_settings, save_settings


def _path_row(edit: QLineEdit, pick) -> QWidget:
    browse = QPushButton("Browse...")
    browse.clicked.connect(pick)
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(edit, 1)
    layout.addWidget(browse)
    return row


def _seconds(value: float, maximum: float) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(0, maximum)
    box.setDecimals(1)
    box.setSingleStep(0.5)
    box.setSuffix(" s")
    box.setValue(value)
    return box


class SettingsDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(640)
        s = get_settings()

        self.root = QLineEdit(str(s.recordings_root))
        self.ffmpeg = QLineEdit(s.ffmpeg)
        self.tesseract = QLineEdit(s.tesseract_cmd)
        self.gpu = QCheckBox("Decode on the GPU when scanning (NVDEC)")
        self.gpu.setChecked(s.gpu_decoding)
        self.parts = QSpinBox()
        self.parts.setRange(1, 8)
        self.parts.setValue(s.scan_parts)
        self.dedup = _seconds(s.dedup_seconds, 60)
        self.lead = _seconds(s.lead_seconds, 30)

        form = QFormLayout()
        form.addRow("Steam recordings folder", _path_row(self.root, self._pick_root))
        form.addRow("ffmpeg", _path_row(self.ffmpeg, lambda: self._pick_file(self.ffmpeg)))
        form.addRow("Tesseract", _path_row(self.tesseract, lambda: self._pick_file(self.tesseract)))
        form.addRow("", self.gpu)
        form.addRow("Parts scanned at once", self.parts)
        form.addRow("Skip markers closer than", self.dedup)
        form.addRow("Place markers earlier by", self.lead)

        note = QLabel("The recordings folder is the one that holds video and timelines, "
                      "set in Steam under Game Recording. ffmpeg can stay \"ffmpeg\" when it is on PATH.")
        note.setWordWrap(True)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(buttons)

    def _pick_root(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Steam recordings folder", self.root.text())
        if folder:
            self.root.setText(folder)

    def _pick_file(self, edit: QLineEdit) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose program", edit.text(), "Programs (*.exe);;All files (*)")
        if path:
            edit.setText(path)

    def _save(self) -> None:
        root = Path(self.root.text().strip())
        if not (root / "video").is_dir():
            answer = QMessageBox.question(
                self, "Folder without recordings",
                f"{root} has no video folder, so no recordings will be listed. Save anyway?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        save_settings(replace(
            get_settings(),
            recordings_root=root,
            ffmpeg=self.ffmpeg.text().strip() or "ffmpeg",
            tesseract_cmd=self.tesseract.text().strip(),
            gpu_decoding=self.gpu.isChecked(),
            scan_parts=self.parts.value(),
            dedup_seconds=self.dedup.value(),
            lead_seconds=self.lead.value(),
        ))
        self.accept()
