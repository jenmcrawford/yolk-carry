"""Forward-only SQL migrations.

Migrations are the single source of truth for the schema. A fresh database,
including every test's in-memory database, is built by applying all of them
in order.

Migration files contain no transaction control (no BEGIN, COMMIT, ROLLBACK,
SAVEPOINT, RELEASE, or END) and no pragmas. The runner owns both: it wraps
each migration in the transaction that lets `PRAGMA foreign_key_check` run
before anything commits, and it turns `PRAGMA foreign_keys` off and back on
around the script so a table rebuild can drop a parent without cascading. A
migration that took either of those over would silently break the
all-or-nothing guarantee.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from yolk.db import Connection
from yolk.errors import YolkError

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_FILENAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")

# Transaction-control keywords a migration must never contain: the runner
# owns BEGIN/COMMIT/ROLLBACK so the foreign-key check can run before anything
# is committed. Matched whole-word and case-insensitively so this cannot be
# defeated by "begin;" or dodged by "beginning" tripping a false positive.
_TRANSACTION_CONTROL = re.compile(
    r"\b(BEGIN|COMMIT|ROLLBACK|SAVEPOINT|RELEASE|END)\b", re.IGNORECASE
)

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


def pending(conn: Connection, directory: Path = MIGRATIONS_DIR) -> list[int]:
    """Versions on disk that this database has not applied yet, in order."""
    done = applied(conn)
    return [version for version, _ in available(directory) if version not in done]


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


def _reject_transaction_control(path: Path, text: str) -> None:
    """Refuse a migration that manages its own transaction, before it runs.

    `_apply_one` relies on the migration script never closing the transaction
    it opens on its behalf. A migration that ends with a `COMMIT` (the
    convention most migration tools expect) would make `executescript` commit
    the migration's work before `PRAGMA foreign_key_check` runs, so a later
    `conn.rollback()` would roll back nothing but the `schema_version` insert
    -- reporting a rollback that never happened while real data is destroyed.
    Rejecting the keyword up front means that damage can never start.
    """
    match = _TRANSACTION_CONTROL.search(text)
    if match is not None:
        raise MigrationError(
            f"Migration {path.name} contains {match.group(1)!r}, which is "
            f"transaction control. The runner owns transaction control so "
            f"that the foreign-key check can run before anything commits. "
            f"Remove the statement; migrations must not manage their own "
            f"transactions or pragmas."
        )


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

    That guarantee only holds if the migration itself never closes the
    transaction, so `_reject_transaction_control` refuses the migration
    up front if it contains BEGIN/COMMIT/ROLLBACK/SAVEPOINT/RELEASE/END, and
    `conn.in_transaction` is checked again after `executescript` runs in case
    something slips past that check (a keyword hidden in a string literal, or
    a quoting trick). If the transaction closed early, part of the migration
    may already be permanent -- there is nothing left to roll back.
    """
    text = path.read_text(encoding="utf-8")
    _reject_transaction_control(path, text)

    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.executescript("BEGIN;\n" + text)
        if not conn.in_transaction:
            raise MigrationError(
                f"Migration {path.name} closed its own transaction (it contains a "
                f"COMMIT, ROLLBACK or END). The runner owns transaction control so "
                f"that the foreign-key check can run before anything is committed. "
                f"Remove the transaction statement; part of this migration may "
                f"already be permanent."
            )
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
