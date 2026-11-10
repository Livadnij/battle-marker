"""Reads the parts of Steam's session.mpd that matter for decoding."""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

NS = {"m": "urn:mpeg:dash:schema:mpd:2011"}


@dataclass(frozen=True)
class VideoTrack:
    representation_id: str
    width: int
    height: int
    codec: str
    init_name: str
    segment_seconds: float
    start_number: int
    period_start: float
    duration: float

    def chunk_name(self, number: int) -> str:
        return f"chunk-stream{self.representation_id}-{number:05d}.m4s"

    def chunk_start(self, number: int) -> float:
        """Folder-clock time where a chunk begins, in seconds."""
        return (number - 1) * self.segment_seconds


def parse_iso_duration(value: str) -> float:
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:([\d.]+)S)?", value)
    if not match:
        raise ValueError(f"Unsupported duration {value!r}")
    hours, minutes, seconds = match.groups()
    return int(hours or 0) * 3600 + int(minutes or 0) * 60 + float(seconds or 0)


def read_video_track(mpd_path: Path) -> VideoTrack:
    root = ET.parse(mpd_path).getroot()
    period = root.find("m:Period", NS)
    if period is None:
        raise ValueError(f"No Period in {mpd_path}")

    for adaptation in period.findall("m:AdaptationSet", NS):
        if adaptation.get("contentType") != "video":
            continue
        rep = adaptation.find("m:Representation", NS)
        template = rep.find("m:SegmentTemplate", NS)
        timescale = int(template.get("timescale"))
        rep_id = rep.get("id")
        return VideoTrack(
            representation_id=rep_id,
            width=int(rep.get("width")),
            height=int(rep.get("height")),
            codec=rep.get("codecs", ""),
            init_name=template.get("initialization").replace("$RepresentationID$", rep_id),
            segment_seconds=int(template.get("duration")) / timescale,
            start_number=int(template.get("startNumber", "1")),
            period_start=parse_iso_duration(period.get("start", "PT0S")),
            duration=parse_iso_duration(root.get("mediaPresentationDuration", "PT0S")),
        )
    raise ValueError(f"No video track in {mpd_path}")
