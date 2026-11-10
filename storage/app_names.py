"""Steam game names found so far, so each app id is looked up only once."""

from storage.db import connect


def get_app_name(app_id: str) -> str | None:
    with connect() as con:
        row = con.execute("SELECT name FROM app_names WHERE app_id = ?", (app_id,)).fetchone()
    return row["name"] if row else None


def put_app_name(app_id: str, name: str) -> None:
    with connect() as con:
        con.execute(
            "INSERT INTO app_names (app_id, name) VALUES (?, ?) "
            "ON CONFLICT(app_id) DO UPDATE SET name = excluded.name",
            (app_id, name),
        )
