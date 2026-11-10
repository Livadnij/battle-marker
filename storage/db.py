"""The SQLite database. One file next to the project, opened per operation.

Every call opens its own connection, so the scan thread and the window
never share one. WAL mode lets the window read while a scan writes.

The schema version is kept in PRAGMA user_version. A new version adds a step
to MIGRATIONS and never edits an older step.
"""

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager

import config

MIGRATIONS = [
    # 1, first version
    """
    CREATE TABLE settings (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL            -- JSON
    );
    CREATE TABLE rules (
        id       INTEGER PRIMARY KEY,
        name     TEXT NOT NULL,
        pattern  TEXT NOT NULL,         -- the rule's match text
        source   TEXT NOT NULL,         -- banner, tag or any
        icon     TEXT NOT NULL,
        priority INTEGER NOT NULL,
        enabled  INTEGER NOT NULL
    );
    CREATE TABLE scans (
        session  TEXT PRIMARY KEY,      -- bg_* folder name
        timeline TEXT NOT NULL,         -- timeline file name
        time_offset REAL NOT NULL,      -- timeline time minus video time
        updated  TEXT NOT NULL          -- ISO time of the last scan
    );
    CREATE TABLE badges (
        id      INTEGER PRIMARY KEY,
        session TEXT NOT NULL REFERENCES scans(session) ON DELETE CASCADE,
        video_start REAL NOT NULL,      -- video seconds
        video_end   REAL NOT NULL
    );
    CREATE INDEX badges_session ON badges(session, video_start);
    CREATE TABLE sightings (
        id       INTEGER PRIMARY KEY,
        badge_id INTEGER NOT NULL REFERENCES badges(id) ON DELETE CASCADE,
        time     REAL NOT NULL,         -- video seconds the text was first read
        kind     TEXT NOT NULL,         -- banner or tag
        label    TEXT NOT NULL
    );
    CREATE INDEX sightings_badge ON sightings(badge_id);
    CREATE TABLE app_names (
        app_id TEXT PRIMARY KEY,
        name   TEXT NOT NULL
    );
    """,
    # 2, deaths, downs and revives from the downed and deploy screens
    """
    INSERT INTO rules (name, pattern, source, icon, priority, enabled) VALUES
        ('Death',   'DEATH',   'life', 'steam_death',   70, 1),
        ('Downed',  'DOWNED',  'life', 'steam_caution', 15, 1),
        ('Revived', 'REVIVED', 'life', 'steam_heart',   15, 1);
    """,
]

_ready = False
_ready_lock = threading.Lock()


def _open() -> sqlite3.Connection:
    con = sqlite3.connect(config.DB_FILE, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def _prepare() -> None:
    """Creates or upgrades the schema, once per run. A new database imports the old files."""
    global _ready
    with _ready_lock:
        if _ready:
            return
        config.DB_FILE.parent.mkdir(parents=True, exist_ok=True)
        con = _open()
        try:
            con.execute("PRAGMA journal_mode = WAL")
            version = con.execute("PRAGMA user_version").fetchone()[0]
            created = version == 0
            for number, script in enumerate(MIGRATIONS[version:], start=version + 1):
                con.executescript("BEGIN;" + script + f"PRAGMA user_version = {number}; COMMIT;")
        finally:
            con.close()
        _ready = True
    if created:
        from storage.legacy import import_legacy_files  # imports storage modules, so not at the top
        import_legacy_files()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """A connection inside one transaction. Commits on success, rolls back on error."""
    _prepare()
    con = _open()
    try:
        yield con
        con.commit()
    except BaseException:
        con.rollback()
        raise
    finally:
        con.close()


def reset_for_tests() -> None:
    """Forgets that the schema was checked, so a different DB_FILE gets prepared."""
    global _ready
    _ready = False
