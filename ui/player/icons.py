"""Steam timeline icons as pixmaps, from the PNG files in icons/.

The PNGs are white glyphs on transparency. Steam's number icons, steam_0 to
steam_99, have no files, so they are drawn as text in the same style.
"""

import re

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap

import config

ICONS_DIR = config.PROJECT_DIR / "icons"
FALLBACK = "steam_marker"
_NUMBER = re.compile(r"steam_(\d{1,2})")
_cache: dict[tuple[str, int], QPixmap] = {}
_tinted_cache: dict[tuple[str, int, str], QPixmap] = {}


def _number_pixmap(text: str, size: int) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    font = QFont()
    font.setBold(True)
    font.setPixelSize(int(size * (0.9 if len(text) == 1 else 0.7)))
    p.setFont(font)
    p.setPen(QColor("white"))
    p.drawText(QRect(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, text)
    p.end()
    return pixmap


def icon_pixmap(name: str, size: int, color: QColor | None = None) -> QPixmap:
    """The icon at size x size pixels, white or tinted. Unknown names get the default marker icon."""
    if color is not None:
        return _tinted(name, size, color)
    key = (name, size)
    if key not in _cache:
        number = _NUMBER.fullmatch(name)
        if number:
            pixmap = _number_pixmap(number.group(1), size)
        else:
            pixmap = QPixmap(str(ICONS_DIR / f"{name}.png"))
            if pixmap.isNull():
                pixmap = QPixmap(str(ICONS_DIR / f"{FALLBACK}.png"))
            if not pixmap.isNull():
                pixmap = pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation)
        _cache[key] = pixmap
    return _cache[key]


def _tinted(name: str, size: int, color: QColor) -> QPixmap:
    """The white glyph recoloured, for light backgrounds like the badge table."""
    key = (name, size, color.name(QColor.NameFormat.HexArgb))
    if key not in _tinted_cache:
        pixmap = QPixmap(icon_pixmap(name, size))
        p = QPainter(pixmap)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        p.fillRect(pixmap.rect(), color)
        p.end()
        _tinted_cache[key] = pixmap
    return _tinted_cache[key]
