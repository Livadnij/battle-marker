"""Shared test setup.

Every test gets its own database and backup folder in a temp directory, so
nothing touches the real battle-marker.db, backups or output folders.
"""

import pytest

import config
from storage import db, settings


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_FILE", tmp_path / "test.db")
    monkeypatch.setattr(config, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    # Nothing exists at these, so a new test database imports no old files.
    monkeypatch.setattr(config, "LEGACY_MARKERS_FILE", tmp_path / "no-markers.json")
    monkeypatch.setattr(config, "LEGACY_APP_NAMES_FILE", tmp_path / "no-app-names.json")
    monkeypatch.setattr(config, "LEGACY_SCAN_LOGS_DIR", tmp_path / "no-scan-logs")
    db.reset_for_tests()
    settings.forget_cache()
    yield
    db.reset_for_tests()
    settings.forget_cache()
