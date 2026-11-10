"""Reads badge text with Tesseract.

Both text areas are first cut down to the box the game draws around the
text. Without that step the background next to the box ends up in the
crop and Tesseract reads noise.
"""

import re

import cv2
import numpy as np
import pytesseract

Box = tuple[int, int, int, int]


def configure(tesseract_cmd: str | None) -> None:
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd


def normalise(text: str) -> str:
    words = re.sub(r"[^A-Z0-9 ]+", " ", text.upper()).split()
    # Box edges come back as stray single letters like I or J.
    return " ".join(w for w in words if len(w) > 1 or w.isdigit())


def crop_gray(image: np.ndarray, box: Box) -> np.ndarray:
    left, top, right, bottom = box
    return cv2.cvtColor(image[top:bottom, left:right], cv2.COLOR_BGR2GRAY)


def _tesseract(gray: np.ndarray) -> str:
    gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    gray = cv2.copyMakeBorder(gray, 15, 15, 15, 15, cv2.BORDER_REPLICATE)
    return normalise(pytesseract.image_to_string(gray, config="--psm 7"))


# The ribbon box always ends at the same place, right before its icon.
# Measured on DOUBLE KILL, GUNSLINGER, PAYBACK and TROOPER, in BANNER_TEXT_BOX pixels.
BANNER_RIGHT_EDGE = 827
BANNER_TOP = 9
BANNER_HEIGHT = 52
BANNER_TOLERANCE = 6


def read_banner(image: np.ndarray, box: Box) -> str:
    """Ribbon banner, dark text on a filled light box.

    The box is found by shape and position instead of by its icon, because
    the icon frame differs between ribbons. A bright background that does
    not form a box ending at the ribbon's edge is ignored.
    """
    gray = crop_gray(image, box)
    mask = (gray > 190).astype(np.uint8)
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    for i in range(1, count):
        x, y, w, h, _ = stats[i]
        if (
            w >= 80
            and abs(x + w - BANNER_RIGHT_EDGE) <= BANNER_TOLERANCE
            and abs(y - BANNER_TOP) <= BANNER_TOLERANCE
            and abs(h - BANNER_HEIGHT) <= BANNER_TOLERANCE
        ):
            return _tesseract(gray[y + 3:y + h - 3, x + 3:x + w - 3])
    return ""


def _vertical_edges(mask: np.ndarray) -> list[tuple[int, int]]:
    """Column ranges where a box outline runs top to bottom."""
    columns = np.where(mask.sum(axis=0) >= 0.5 * mask.shape[0])[0]
    groups: list[list[int]] = []
    for c in columns:
        if groups and c - groups[-1][-1] <= 3:
            groups[-1].append(c)
        else:
            groups.append([c])
    return [(g[0], g[-1]) for g in groups]


def read_tag(image: np.ndarray, box: Box) -> str:
    """Tag boxes, light text inside thin light outlines.

    A row can hold several boxes, like KILL and OFFENSIVE. Each box is read
    on its own and the words are joined left to right.
    """
    gray = crop_gray(image, box)
    mask = gray > 170
    edges = _vertical_edges(mask)
    words = []
    i = 0
    while i + 1 < len(edges):
        left, right = edges[i][1], edges[i + 1][0]
        if right - left <= 30:  # two lines of the same edge, or a gap between boxes
            i += 1
            continue
        i += 2
        rows = np.where(mask[:, left:right + 1].mean(axis=1) > 0.6)[0]
        if len(rows) < 2:
            continue
        inside = gray[rows.min() + 4:rows.max() - 3, left + 4:right - 3]
        if inside.size:
            text = _tesseract(255 - inside)
            if text:
                words.append(text)
    return " ".join(words)


SIGNATURE_BRIGHT = 170  # same cut as the tag outline search in read_tag


def signature(image: np.ndarray, box: Box) -> np.ndarray:
    """Small thumbnail of the bright pixels, used to notice when the text changed.

    Only text and outlines are that bright. Tag boxes are see-through, and
    comparing plain gray made every move of the scene behind them look like
    new text, so the same tag was read again and again.
    """
    bright = np.where(crop_gray(image, box) > SIGNATURE_BRIGHT, 255, 0).astype(np.uint8)
    return cv2.resize(bright, None, fx=0.125, fy=0.125, interpolation=cv2.INTER_AREA).astype(np.int16)


def changed(a: np.ndarray | None, b: np.ndarray, threshold: float) -> bool:
    return a is None or float(np.abs(a - b).mean()) > threshold
