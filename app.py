"""battle-marker window. Start it with `uv run app.py`."""

import sys

from PySide6.QtWidgets import QApplication

from child_processes import contain_children
from ui.main_window import MainWindow


def main() -> None:
    contain_children()  # ffmpeg and Tesseract end with the app, even after a crash
    app = QApplication(sys.argv)
    app.setApplicationName("battle-marker")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
