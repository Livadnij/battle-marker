"""One-time import of the files used before the database.

Runs once, right after the database is created. The old files are left in
place and are not read again.
"""

import json

import config
from events.rules import rules_from_json
from events.tracker import Appearance, Sighting
from storage.app_names import put_app_name
from storage.rules import replace_rules
from storage.scans import save_appearances


def import_legacy_files() -> None:
    _import_rules()
    _import_scan_logs()
    _import_app_names()


def _import_rules() -> None:
    path = config.LEGACY_MARKERS_FILE
    if path.exists():
        replace_rules(rules_from_json(json.loads(path.read_text(encoding="utf-8"))))


def _import_scan_logs() -> None:
    folder = config.LEGACY_SCAN_LOGS_DIR
    if not folder.exists():
        return
    for path in sorted(folder.glob("bg_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            appearances = [
                Appearance(a["start"], a["end"], [Sighting(**s) for s in a["sightings"]])
                for a in data["appearances"]
            ]
        except (OSError, ValueError, KeyError, TypeError):
            continue  # a damaged log is skipped, the recording can be rescanned
        save_appearances(
            data.get("session", path.stem), data.get("timeline", ""), float(data.get("offset", 0)),
            appearances, [(float("-inf"), float("inf"))],
        )


def _import_app_names() -> None:
    path = config.LEGACY_APP_NAMES_FILE
    if not path.exists():
        return
    try:
        names = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    for app_id, name in names.items():
        put_app_name(str(app_id), str(name))
