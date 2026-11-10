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
    tag_top: int | None = None  # ROI row where the tag box's right end matched best


NO_BADGE = Cues(present=False, banner=False, headshot=False, banner_readable=False,
                tag_readable=False, scores={})


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

    def _match(self, gray: np.ndarray, name: str) -> tuple[float, int]:
        """Best score in the template's region and the ROI row it matched at."""
        left, top, right, bottom = self.regions[name]
        area = gray[top:bottom, left:right]
        result = cv2.matchTemplate(area, self.templates[name], cv2.TM_CCOEFF_NORMED)
        # A flat area gives NaN, which means no match.
        result = np.nan_to_num(result, nan=0.0)
        row, _ = np.unravel_index(int(result.argmax()), result.shape)
        return float(result.max()), top + int(row)

    def analyse(self, image: np.ndarray) -> Cues:
        # Only the badge part of the ROI is converted, the rest is for the downed and deploy screens.
        right = max(r[2] for r in self.regions.values())
        bottom = max(r[3] for r in self.regions.values())
        gray = cv2.cvtColor(image[:bottom, :right], cv2.COLOR_BGR2GRAY)
        matches = {name: self._match(gray, name) for name in self.regions}
        scores = {name: score for name, (score, _) in matches.items()}
        present = max(scores["tag_edge"], scores["score_zero"]) >= self.presence_threshold
        return Cues(
            present=present,
            banner=present and scores["banner_bars"] >= self.banner_threshold,
            headshot=present and scores["headshot_tag"] >= self.headshot_threshold,
            banner_readable=present and scores["banner_bars"] >= self.readable_threshold,
            tag_readable=present and scores["tag_edge"] >= self.readable_threshold,
            scores=scores,
            tag_top=matches["tag_edge"][1],
        )
