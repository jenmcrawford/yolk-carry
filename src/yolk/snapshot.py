"""Export the database to JSON, and load it back.

The SQLite file is not committed: a binary in git has no readable diff, cannot
merge, and breaks once a second person writes to it. This text export is the
durable copy instead, and it is the thing that would be handed to another
person later.

JSON rather than a SQL dump because a dump is SQLite dialect, and this loads
into Postgres just as easily.
"""

from __future__ import annotations

import json
from pathlib import Path

from yolk.config import REPO_ROOT
from yolk.db import Connection
from yolk.db.migrate import applied, latest_version
from yolk.errors import YolkError

DEFAULT_DIR = REPO_ROOT / "data"

# Parents before children, so an import with foreign keys on would still work.
TABLES: tuple[str, ...] = (
    "people",
    "tags",
    "foods",
    "food_tags",
    "food_units",
    "food_components",
    "protocols",
    "protocol_rules",
    "person_protocols",
    "macro_profiles",
    "slot_templates",
    "slot_template_roles",
    "day_plans",
    "day_plan_entries",
    "inventory",
)

_VERSION_TABLE = "schema_version"


class SnapshotError(YolkError):
    """An export could not be written, or an import could not be loaded."""


def _columns(conn: Connection, table: str) -> list[str]:
    cursor = conn.execute(f"SELECT * FROM {table} LIMIT 0")
    return [description[0] for description in cursor.description]


def _read_rows(conn: Connection, table: str) -> list[dict]:
    # Ordering by every column, rather than by primary key, is a total order
    # regardless of NULLs: every table's column list here contains a unique
    # key, either `id` or the composite primary key on food_tags, and a
    # unique key can never tie. A column that is NULL only ever breaks ties
    # among rows that already agree on that key, which cannot happen. Keep
    # this in mind before adding a table without a unique key to TABLES.
    columns = _columns(conn, table)
    order = ", ".join(columns)
    rows = conn.execute(f"SELECT * FROM {table} ORDER BY {order}").fetchall()
    return [dict(zip(columns, row)) for row in rows]


def export_database(conn: Connection, out_dir: Path = DEFAULT_DIR) -> list[Path]:
    """Write every table to `out_dir` as sorted, indented JSON.

    Ordering by every column, rather than by primary key, keeps output stable
    for tables whose key is composite, and means no per-table configuration.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for table in (*TABLES, _VERSION_TABLE):
        path = out_dir / f"{table}.json"
        text = json.dumps(_read_rows(conn, table), indent=2, sort_keys=True) + "\n"
        path.write_text(text, encoding="utf-8")
        written.append(path)
    return written


def _load(in_dir: Path, table: str) -> list[dict]:
    path = in_dir / f"{table}.json"
    if not path.is_file():
        raise SnapshotError(f"Export is incomplete: {path} is missing.")
    return json.loads(path.read_text(encoding="utf-8"))


def import_database(conn: Connection, in_dir: Path = DEFAULT_DIR) -> dict[str, int]:
    """Load an export into an empty, already-migrated database.

    Foreign keys are off for the load and checked before the commit, so a
    self-referencing table (a plan pointing at its parent plan) cannot fail on
    row order alone.
    """
    exported_version = max((row["version"] for row in _load(in_dir, _VERSION_TABLE)), default=0)
    if exported_version != latest_version():
        raise SnapshotError(
            f"Export was taken at schema version {exported_version}, but this "
            f"code is at {latest_version()}. Run the migrations that are "
            f"missing, re-export, and try again."
        )
    # latest_version() checks the export against the code on disk, but the
    # target database can lag behind that -- it exists and passes the guard
    # above, yet is one migration short. Without this, that mismatch is only
    # caught deep in the insert loop below, as an opaque OperationalError
    # about a missing column. Comparing against the database's own applied
    # version catches it up front, with a message that says what to run.
    db_version = max(applied(conn), default=0)
    if exported_version != db_version:
        raise SnapshotError(
            f"Export was taken at schema version {exported_version}, but this "
            f"database is at {db_version}. Run `yolk migrate` on this database, "
            f"then try the import again."
        )

    for table in TABLES:
        if conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]:
            raise SnapshotError(
                f"Refusing to import: this database already has data in "
                f"{table!r}. Import only into an empty database."
            )

    counts: dict[str, int] = {}
    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("BEGIN")
        for table in TABLES:
            rows = _load(in_dir, table)
            counts[table] = len(rows)
            for row in rows:
                columns = sorted(row)
                placeholders = ", ".join("?" for _ in columns)
                conn.execute(
                    f"INSERT INTO {table} ({', '.join(columns)}) "
                    f"VALUES ({placeholders})",
                    tuple(row[column] for column in columns),
                )
        # schema_version is exported but the migration run that got this
        # database to the exported version already wrote its own applied_on
        # (today's date), not the exported one. Without restoring it here, a
        # re-export churns schema_version.json every time it lands on a
        # different day than the original export -- silently, since nothing
        # else about the data changed. INSERT OR REPLACE puts the exported
        # dates back so a round trip is byte-identical.
        for row in _load(in_dir, _VERSION_TABLE):
            conn.execute(
                "INSERT OR REPLACE INTO schema_version (version, applied_on) "
                "VALUES (?, ?)",
                (row["version"], row["applied_on"]),
            )
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            conn.rollback()
            raise SnapshotError(
                f"Import would leave {len(violations)} row(s) referencing rows "
                f"that do not exist, so nothing was written. First offender: "
                f"table {violations[0][0]!r}."
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
    return counts
