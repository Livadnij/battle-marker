"""Cues for the downed screen and the deploy screen on a single ROI frame.

The downed screen draws a round heartbeat button at a fixed spot. It is
found by sampling a circle and counting how much of it is white against
what lies just outside, which holds for the plain, the filled and the
dashed revive variants alike.

The deploy screen is found by its row of class icons. One class box is
always filled white, so the row is matched on its edges, which look the
same whether an icon is white on dark or dark on white.
"""

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

Box = tuple[int, int, int, int]

RING_SAMPLES = 120
RING_WIDTH = 2  # the drawn ring is a few pixels thick, the brightest of three radii is used
RING_OUTSIDE = 12  # pixels outside the ring that are compared against
RING_CONTRAST = 35  # how much brighter the ring has to be than its outside, 0..255
RING_WHITE = 170  # the ring itself is near white
TEMPLATE_MARGIN = 2  # deploy_icons.png has this border, so its edges are not cut


@dataclass(frozen=True)
class LifeCues:
    downed: bool
    deploy: bool
    ring: float  # share of the heartbeat ring drawn, 0..1
    deploy_score: float  # edge match of the class row, -1..1


def _edges(gray: np.ndarray) -> np.ndarray:
    blurred = cv2.GaussianBlur(gray, (3, 3), 0).astype(np.float32)
    return cv2.magnitude(cv2.Sobel(blurred, cv2.CV_32F, 1, 0), cv2.Sobel(blurred, cv2.CV_32F, 0, 1))


class LifeDetector:
    def __init__(
        self,
        templates_dir: Path,
        ring: tuple[int, int, int],
        ring_threshold: float,
        deploy_region: Box,
        deploy_threshold: float,
    ) -> None:
        path = templates_dir / "deploy_icons.png"
        template = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if template is None:
            raise FileNotFoundError(f"Missing template {path}")
        m = TEMPLATE_MARGIN
        self.deploy_template = _edges(template)[m:-m, m:-m]
        self.deploy_region = deploy_region
        self.deploy_threshold = deploy_threshold
        self.ring_threshold = ring_threshold

        cx, cy, r = ring
        reach = r + RING_OUTSIDE + RING_WIDTH + 1
        self.ring_box = (cx - reach, cy - reach, cx + reach + 1, cy + reach + 1)
        angles = np.linspace(0, 2 * np.pi, RING_SAMPLES, endpoint=False)

        def points(radius: int) -> tuple[np.ndarray, np.ndarray]:
            # Relative to ring_box, so only that small area is converted to gray.
            xs = np.round(reach + radius * np.cos(angles)).astype(int)
            ys = np.round(reach + radius * np.sin(angles)).astype(int)
            return ys, xs

        self.ring_points = [points(r + d) for d in (-RING_WIDTH, 0, RING_WIDTH)]
        self.outside_points = points(r + RING_OUTSIDE)

    def ring_score(self, image: np.ndarray) -> float:
        left, top, right, bottom = self.ring_box
        gray = cv2.cvtColor(image[top:bottom, left:right], cv2.COLOR_BGR2GRAY).astype(np.int16)
        if gray.shape != (bottom - top, right - left):
            return 0.0  # the ROI does not reach the button
        ring = np.maximum.reduce([gray[p] for p in self.ring_points])
        outside = gray[self.outside_points]
        return float(np.mean(((ring - outside) > RING_CONTRAST) & (ring > RING_WHITE)))

    def deploy_match(self, image: np.ndarray) -> float:
        left, top, right, bottom = self.deploy_region
        area = cv2.cvtColor(image[top:bottom, left:right], cv2.COLOR_BGR2GRAY)
        if area.shape[0] < self.deploy_template.shape[0] or area.shape[1] < self.deploy_template.shape[1]:
            return 0.0
        result = cv2.matchTemplate(_edges(area), self.deploy_template, cv2.TM_CCOEFF_NORMED)
        return float(np.nan_to_num(result.max(), nan=0.0))

    def analyse(self, image: np.ndarray) -> LifeCues:
        deploy_score = self.deploy_match(image)
        deploy = deploy_score >= self.deploy_threshold
        # The deploy screen never shows the button, so the ring is not checked there.
        ring = 0.0 if deploy else self.ring_score(image)
        return LifeCues(downed=ring >= self.ring_threshold, deploy=deploy, ring=ring, deploy_score=deploy_score)
