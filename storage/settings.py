"""User settings, stored as JSON values in the settings table.

A setting that was never saved has its default from config.py.
"""

import json
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path

import config
from storage.db import connect


@dataclass(frozen=True)
class Settings:
    recordings_root: Path = config.DEFAULT_RECORDINGS_ROOT
    ffmpeg: str = config.DEFAULT_FFMPEG
    tesseract_cmd: str = config.DEFAULT_TESSERACT_CMD
    gpu_decoding: bool = config.DEFAULT_GPU_DECODING
    scan_parts: int = config.DEFAULT_SCAN_PARTS
    dedup_seconds: float = config.DEFAULT_DEDUP_SECONDS
    lead_seconds: float = config.DEFAULT_LEAD_SECONDS


_cached: Settings | None = None


def get_settings() -> Settings:
    global _cached
    if _cached is None:
        with connect() as con:
            stored = {row["key"]: json.loads(row["value"])
                      for row in con.execute("SELECT key, value FROM settings")}
        values = {}
        for f in fields(Settings):
            if f.name in stored:
                value = stored[f.name]
                values[f.name] = Path(value) if f.name == "recordings_root" else value
        _cached = replace(Settings(), **values)
    return _cached


def save_settings(settings: Settings) -> None:
    global _cached
    data = asdict(settings)
    data["recordings_root"] = str(settings.recordings_root)
    with connect() as con:
        con.executemany(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            [(key, json.dumps(value)) for key, value in data.items()],
        )
    _cached = settings


def forget_cache() -> None:
    global _cached
    _cached = None
