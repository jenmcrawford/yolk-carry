"""Forward-only SQL migrations.

Migrations are the single source of truth for the schema. A fresh database,
including every test's in-memory database, is built by applying all of them
in order.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from yolk.db import Connection
from yolk.errors import YolkError

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_FILENAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")

_VERSION_TABLE = """
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_on  TEXT NOT NULL
)
"""


class MigrationError(YolkError):
    """A migration could not be applied, and nothing was changed."""


def available(directory: Path = MIGRATIONS_DIR) -> list[tuple[int, Path]]:
    """Every migration in `directory`, ordered by version."""
    found: list[tuple[int, Path]] = []
    for path in sorted(directory.glob("*.sql")):
        match = _FILENAME.match(path.name)
        if match is None:
            raise ValueError(
                f"Migration filename {path.name!r} is not usable. Names must "
                f"look like 0001_name.sql: four digits, an underscore, then "
                f"lowercase words."
            )
        found.append((int(match.group(1)), path))
    return found


def latest_version(directory: Path = MIGRATIONS_DIR) -> int:
    """The highest migration version on disk, or 0 if there are none."""
    return max((version for version, _ in available(directory)), default=0)


def applied(conn: Connection) -> set[int]:
    """Versions already applied to this database, creating the table if needed."""
    conn.execute(_VERSION_TABLE)
    conn.commit()
    return {row["version"] for row in conn.execute("SELECT version FROM schema_version")}


def apply_migrations(
    conn: Connection, directory: Path = MIGRATIONS_DIR
) -> list[int]:
    """Apply every pending migration in order. Returns the versions applied."""
    done = applied(conn)
    applied_now: list[int] = []
    for version, path in available(directory):
        if version in done:
            continue
        _apply_one(conn, version, path)
        applied_now.append(version)
    return applied_now


def _apply_one(conn: Connection, version: int, path: Path) -> None:
    """Apply one migration, all of it or none of it.

    Foreign keys are turned off first, and outside any transaction, because
    `PRAGMA foreign_keys` is a no-op inside one and because a table rebuild
    must be able to drop a parent table without firing ON DELETE CASCADE on
    its children.

    The script text is prefixed with BEGIN and deliberately not followed by
    COMMIT, so the transaction is still open when the script ends. That is
    what lets the foreign key check run before anything is committed.
    `executescript` commits any pending transaction before it runs, so the
    BEGIN has to be inside the script rather than issued separately.
    """
    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.executescript("BEGIN;\n" + path.read_text(encoding="utf-8"))
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            conn.rollback()
            raise MigrationError(
                f"Migration {path.name} left {len(violations)} row(s) pointing at "
                f"rows that do not exist, so it was rolled back. First offender: "
                f"table {violations[0][0]!r}, rowid {violations[0][1]!r}, "
                f"referencing {violations[0][2]!r}."
            )
        conn.execute(
            "INSERT INTO schema_version (version, applied_on) VALUES (?, ?)",
            (version, date.today().isoformat()),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
