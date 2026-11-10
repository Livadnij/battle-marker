"""Marker rules in the database, and the badge texts scans have seen."""

from dataclasses import dataclass

from events.rules import Rule
from storage.db import connect


def list_rules() -> list[Rule]:
    """All rules, enabled or not, highest priority first."""
    with connect() as con:
        rows = con.execute(
            "SELECT name, pattern, source, icon, priority, enabled FROM rules "
            "ORDER BY priority DESC, id"
        ).fetchall()
    return [Rule(r["name"], r["pattern"], r["source"], r["icon"], r["priority"], bool(r["enabled"]))
            for r in rows]


def replace_rules(rules: list[Rule]) -> None:
    """Stores exactly these rules. The rules editor saves the whole list at once."""
    with connect() as con:
        con.execute("DELETE FROM rules")
        con.executemany(
            "INSERT INTO rules (name, pattern, source, icon, priority, enabled) VALUES (?, ?, ?, ?, ?, ?)",
            [(r.name, r.match, r.source, r.icon, r.priority, int(r.enabled)) for r in rules],
        )


@dataclass(frozen=True)
class SeenLabel:
    kind: str  # banner, tag or life
    label: str
    count: int  # badges it was read on, across all scans


def seen_labels() -> list[SeenLabel]:
    """Every text scans have read, most frequent first."""
    with connect() as con:
        rows = con.execute(
            "SELECT kind, label, COUNT(*) AS n FROM sightings GROUP BY kind, label ORDER BY n DESC, label"
        ).fetchall()
    return [SeenLabel(r["kind"], r["label"], r["n"]) for r in rows]
