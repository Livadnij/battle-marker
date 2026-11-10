"""Template cues on a single ROI frame.

Normalised cross-correlation ignores overall brightness and contrast, so a
bright background does not by itself trigger or hide a cue. Only the shape
of the HUD element matters.
"""

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

Box = tuple[int, int, int, int]


@dataclass(frozen=True)
class Cues:
    present: bool
    banner: bool
    headshot: bool
    banner_readable: bool  # banner fully drawn, safe to OCR
    tag_readable: bool  # tag box fully drawn, safe to OCR
    scores: dict[str, float]


class BadgeDetector:
    def __init__(
        self,
        templates_dir: Path,
        regions: dict[str, Box],
        presence_threshold: float,
        banner_threshold: float,
        headshot_threshold: float,
        readable_threshold: float,
    ) -> None:
        self.regions = regions
        self.templates = {}
        for name in regions:
            path = templates_dir / f"{name}.png"
            image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if image is None:
                raise FileNotFoundError(f"Missing template {path}")
            self.templates[name] = image
        self.presence_threshold = presence_threshold
        self.banner_threshold = banner_threshold
        self.headshot_threshold = headshot_threshold
        self.readable_threshold = readable_threshold

    def _score(self, gray: np.ndarray, name: str) -> float:
        left, top, right, bottom = self.regions[name]
        area = gray[top:bottom, left:right]
        result = cv2.matchTemplate(area, self.templates[name], cv2.TM_CCOEFF_NORMED)
        # A flat area gives NaN, which means no match.
        return float(np.nan_to_num(result.max(), nan=0.0))

    def analyse(self, image: np.ndarray) -> Cues:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        scores = {name: self._score(gray, name) for name in self.regions}
        present = max(scores["tag_edge"], scores["score_zero"]) >= self.presence_threshold
        return Cues(
            present=present,
            banner=present and scores["banner_bars"] >= self.banner_threshold,
            headshot=present and scores["headshot_tag"] >= self.headshot_threshold,
            banner_readable=present and scores["banner_bars"] >= self.readable_threshold,
            tag_readable=present and scores["tag_edge"] >= self.readable_threshold,
            scores=scores,
        )
