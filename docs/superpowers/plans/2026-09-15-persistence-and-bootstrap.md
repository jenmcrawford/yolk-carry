# Persistence and Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn an empty checkout into a working SQLite database holding Keto Plan A, with forward-only migrations, a deterministic JSON export that is committed to git, and a `yolk` command that drives all of it.

**Architecture:** `schema.sql` becomes the first numbered migration, so a fresh database and every in-memory test database are both built by applying migrations in order. The golden test's plan-building loop moves into a seed module that the test and the CLI share. A snapshot module exports every table to sorted JSON and loads it back into an empty database. A thin argparse CLI ties them together.

**Tech Stack:** Python 3.14, `uv`, stdlib `sqlite3`, stdlib `argparse`, `pytest`. No new runtime dependencies in this slice.

**Spec:** [2026-09-13-local-app-persistence-and-review-design.md](../specs/2026-09-13-local-app-persistence-and-review-design.md), slice 1 (§4). Slices 2 through 6 are not in this plan.

## Global Constraints

- Python `>=3.14`, managed by `uv`. Run everything as `uv run <cmd>`.
- No new runtime dependencies in this slice. `httpx` and `python-dotenv` are the only ones, and `pytest` is the only dev dependency.
- Portable SQL only in schema and queries. No SQLite-only SQL or functions there.
- SQLite pragmas for transaction and foreign-key control are exempt from that rule. Turning foreign keys off around a load or a table rebuild, and running `PRAGMA foreign_key_check` before committing, is plumbing rather than schema: Postgres does the same job with deferrable constraints, and a port replaces those few lines. Keeping the check matters more than avoiding the pragma.
- SQL placeholders stay `?`. Do not convert them.
- Booleans are `INTEGER` with `CHECK (x IN (0, 1))`. Dates are ISO-8601 `TEXT`.
- New code uses `RETURNING id`, never `cursor.lastrowid`.
- New code annotates connections as `yolk.db.Connection`, never `sqlite3.Connection`.
- Migrations are forward only. There are no down migrations.
- Tests use `:memory:` databases and never touch the resolved database path.
- The full suite is `uv run python -m pytest`. It passes at 94 tests before this plan starts, and must pass at the end of every task.
- **Run tools as modules, not as console scripts.** Windows Smart App Control on this machine blocks the small generated launcher executables that a virtual environment puts in `Scripts/`, including `pytest.exe` and any `yolk.exe`. It allows the real interpreter. So `uv run pytest` fails while `uv run python -m pytest` works, and the same rule applies to this project's own command. The virtual environment at `.venv` must be created by `python -m venv` rather than by uv, so that its `python.exe` is a copy of the real interpreter instead of a generated launcher; `uv sync` then respects it.
- Commit at the end of every task.

---

## File Structure

**Created:**

| Path | Responsibility |
|---|---|
| `src/yolk/db/migrations/0001_baseline.sql` | The current schema, as the first migration |
| `src/yolk/db/migrate.py` | Discovering, applying, and recording migrations |
| `src/yolk/config.py` | Resolving the database path |
| `src/yolk/seed.py` | Building Keto Plan A into a database from the fixture |
| `src/yolk/snapshot.py` | Exporting every table to JSON and importing it back |
| `src/yolk/cli.py` | The `yolk` command |
| `src/yolk/__main__.py` | Entry point for `python -m yolk` |
| `tests/test_migrate.py`, `tests/test_config.py`, `tests/test_seed.py`, `tests/test_snapshot.py`, `tests/test_cli.py` | Tests for the above |

**Modified:**

| Path | Change |
|---|---|
| `src/yolk/db/__init__.py` | Gains the `Connection` type alias |
| `src/yolk/db/connection.py` | `create_schema` applies migrations instead of reading `schema.sql` |
| `src/yolk/foods.py`, `src/yolk/people.py`, `src/yolk/planning/evaluate.py`, `src/yolk/units.py`, `src/yolk/sources/usda.py` | `RETURNING id` and the `Connection` alias |
| `tests/test_golden_keto_a.py` | Its loader moves to `seed.py`; the test calls the seed |
| `tests/conftest.py` | `person` fixture uses `RETURNING id` |
| `pyproject.toml` | The `yolk` console script |
| `.gitignore` | Ignores the database file |
| `README.md` | A setup section |

**Deleted:** `src/yolk/db/schema.sql`, moved by `git mv` to the baseline migration.

---

## Task 1: Migration runner and baseline migration

**Files:**
- Create: `src/yolk/db/migrate.py`
- Create: `src/yolk/db/migrations/0001_baseline.sql` (by `git mv` from `src/yolk/db/schema.sql`)
- Modify: `src/yolk/db/__init__.py`
- Modify: `src/yolk/db/connection.py`
- Test: `tests/test_migrate.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `yolk.db.Connection` — a type alias for `sqlite3.Connection`.
  - `yolk.db.migrate.MIGRATIONS_DIR: Path`
  - `yolk.db.migrate.MigrationError(YolkError)`
  - `yolk.db.migrate.available(directory: Path = MIGRATIONS_DIR) -> list[tuple[int, Path]]`
  - `yolk.db.migrate.applied(conn: Connection) -> set[int]`
  - `yolk.db.migrate.latest_version(directory: Path = MIGRATIONS_DIR) -> int`
  - `yolk.db.migrate.apply_migrations(conn: Connection, directory: Path = MIGRATIONS_DIR) -> list[int]` — returns the versions applied by this call, in order.
  - `yolk.db.connection.create_schema(conn)` keeps its name and signature.

- [ ] **Step 1: Move the schema into a migrations directory**

```bash
mkdir src/yolk/db/migrations
git mv src/yolk/db/schema.sql src/yolk/db/migrations/0001_baseline.sql
```

- [ ] **Step 2: Strip the pragma lines from the baseline**

Delete the first two lines of `src/yolk/db/migrations/0001_baseline.sql`:

```sql
PRAGMA foreign_keys = ON;
PRAGMA user_version = 2;
```

The runner owns both. `PRAGMA user_version` is SQLite-only and is replaced by the `schema_version` table, and two competing version markers would drift. The file now starts with `CREATE TABLE people (`.

- [ ] **Step 3: Add the Connection alias**

Write `src/yolk/db/__init__.py`:

```python
"""Database access for yolk.

`Connection` is an alias rather than `sqlite3.Connection` used directly, so
that a later move to Postgres changes one line instead of every annotation in
the package.
"""

from __future__ import annotations

import sqlite3

Connection = sqlite3.Connection

__all__ = ["Connection"]
```

- [ ] **Step 4: Write the failing tests**

Create `tests/test_migrate.py`:

```python
import pytest

from yolk.db.connection import connect, create_schema
from yolk.db.migrate import (
    MIGRATIONS_DIR,
    apply_migrations,
    available,
    latest_version,
)


def test_baseline_is_discovered():
    versions = [version for version, _ in available()]
    assert versions == sorted(versions)
    assert versions[0] == 1


def test_latest_version_matches_the_highest_file():
    assert latest_version() == max(v for v, _ in available())


def test_migrations_create_every_table():
    conn = connect(":memory:")
    apply_migrations(conn)
    names = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    expected = {
        "people", "tags", "food_tags", "foods", "food_units", "food_components",
        "protocols", "protocol_rules", "person_protocols",
        "macro_profiles", "slot_templates", "slot_template_roles",
        "day_plans", "day_plan_entries", "inventory",
    }
    assert expected <= names
    conn.close()


def test_migrations_record_what_they_applied():
    conn = connect(":memory:")
    applied_now = apply_migrations(conn)
    assert applied_now == [version for version, _ in available()]
    recorded = {
        row["version"] for row in conn.execute("SELECT version FROM schema_version")
    }
    assert recorded == set(applied_now)
    conn.close()


def test_applying_twice_is_a_no_op():
    conn = connect(":memory:")
    apply_migrations(conn)
    assert apply_migrations(conn) == []
    conn.close()


def test_badly_named_migration_is_rejected(tmp_path):
    (tmp_path / "nope.sql").write_text("CREATE TABLE t (id INTEGER PRIMARY KEY);")
    with pytest.raises(ValueError, match="0001_name.sql"):
        available(tmp_path)


def test_create_schema_still_builds_a_usable_database(db):
    """The existing conftest fixture must keep working unchanged."""
    db.execute("INSERT INTO people (name) VALUES ('Jen')")
    assert db.execute("SELECT count(*) AS n FROM people").fetchone()["n"] == 1
```

- [ ] **Step 5: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_migrate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yolk.db.migrate'`

- [ ] **Step 6: Write the migration runner**

Create `src/yolk/db/migrate.py`:

```python
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
```

- [ ] **Step 7: Point create_schema at the runner**

Replace the whole body of `src/yolk/db/connection.py`:

```python
"""SQLite connection management and schema creation."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from yolk.db import Connection
from yolk.db.migrate import apply_migrations


def connect(path: str | Path) -> Connection:
    """Open a connection with row access by name and foreign keys enforced."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_schema(conn: Connection) -> None:
    """Bring a database up to the latest schema by applying every migration."""
    apply_migrations(conn)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.commit()
```

- [ ] **Step 8: Run the new tests**

Run: `uv run python -m pytest tests/test_migrate.py -v`
Expected: PASS, 7 tests

- [ ] **Step 9: Run the whole suite**

Run: `uv run python -m pytest`
Expected: PASS, 101 tests. `tests/test_schema.py` must still pass untouched, because it asserts `expected <= names` and the new `schema_version` table is an addition.

- [ ] **Step 10: Commit**

```bash
git add src/yolk/db tests/test_migrate.py
git commit -m "feat: apply the schema through forward-only migrations

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 2: Prove the runner is safe for table rebuilds

SQLite cannot alter a CHECK constraint, so slice 3 will have to rebuild `day_plans`. That is the migration most likely to silently destroy data. This task proves the runner handles it before anything depends on it.

**Files:**
- Test: `tests/test_migrate.py` (add to it)

**Interfaces:**
- Consumes: `apply_migrations(conn, directory)` and `MigrationError` from Task 1.
- Produces: nothing new. This task adds tests only.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_migrate.py`:

```python
REBUILD_SQL = """
CREATE TABLE parent_new (
    id      INTEGER PRIMARY KEY,
    label   TEXT NOT NULL CHECK (label IN ('a', 'b', 'c'))
);
INSERT INTO parent_new (id, label) SELECT id, label FROM parent;
DROP TABLE parent;
ALTER TABLE parent_new RENAME TO parent;
"""


def _two_table_database(tmp_path):
    """A parent and a child, one row each, built by migration 0001."""
    (tmp_path / "0001_baseline.sql").write_text(
        "CREATE TABLE parent (\n"
        "    id    INTEGER PRIMARY KEY,\n"
        "    label TEXT NOT NULL CHECK (label IN ('a', 'b'))\n"
        ");\n"
        "CREATE TABLE child (\n"
        "    id        INTEGER PRIMARY KEY,\n"
        "    parent_id INTEGER NOT NULL REFERENCES parent(id) ON DELETE CASCADE\n"
        ");\n",
        encoding="utf-8",
    )
    conn = connect(":memory:")
    apply_migrations(conn, tmp_path)
    conn.execute("INSERT INTO parent (id, label) VALUES (1, 'a')")
    conn.execute("INSERT INTO child (id, parent_id) VALUES (1, 1)")
    conn.commit()
    return conn


def test_rebuild_keeps_every_row_in_the_rebuilt_table(tmp_path):
    conn = _two_table_database(tmp_path)
    (tmp_path / "0002_widen_label.sql").write_text(REBUILD_SQL, encoding="utf-8")

    assert apply_migrations(conn, tmp_path) == [2]

    assert conn.execute("SELECT label FROM parent WHERE id = 1").fetchone()["label"] == "a"
    conn.execute("INSERT INTO parent (id, label) VALUES (2, 'c')")
    conn.close()


def test_rebuild_does_not_cascade_delete_the_children(tmp_path):
    """Dropping the old parent table must not take the child rows with it."""
    conn = _two_table_database(tmp_path)
    (tmp_path / "0002_widen_label.sql").write_text(REBUILD_SQL, encoding="utf-8")

    apply_migrations(conn, tmp_path)

    assert conn.execute("SELECT count(*) AS n FROM child").fetchone()["n"] == 1
    conn.close()


def test_a_migration_that_orphans_rows_is_rolled_back(tmp_path):
    """Losing a parent row leaves the child dangling, so nothing may commit."""
    conn = _two_table_database(tmp_path)
    (tmp_path / "0002_drop_a_row.sql").write_text(
        "DELETE FROM parent WHERE id = 1;", encoding="utf-8"
    )

    with pytest.raises(MigrationError, match="rolled back"):
        apply_migrations(conn, tmp_path)

    assert conn.execute("SELECT count(*) AS n FROM parent").fetchone()["n"] == 1
    versions = {row["version"] for row in conn.execute("SELECT version FROM schema_version")}
    assert versions == {1}
    conn.close()


def test_foreign_keys_are_enforced_again_after_a_migration(tmp_path):
    conn = _two_table_database(tmp_path)
    (tmp_path / "0002_widen_label.sql").write_text(REBUILD_SQL, encoding="utf-8")

    apply_migrations(conn, tmp_path)

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO child (id, parent_id) VALUES (2, 999)")
    conn.close()
```

Add `import sqlite3` and `from yolk.db.migrate import MigrationError` to the imports at the top of the file.

- [ ] **Step 2: Run the tests**

Run: `uv run python -m pytest tests/test_migrate.py -v`
Expected: PASS. If `test_rebuild_does_not_cascade_delete_the_children` fails, the runner is turning foreign keys off in the wrong place. The pragma must be executed after `conn.commit()` and before `executescript`, never inside the transaction.

- [ ] **Step 3: Run the whole suite**

Run: `uv run python -m pytest`
Expected: PASS, 105 tests

- [ ] **Step 4: Commit**

```bash
git add tests/test_migrate.py
git commit -m "test: prove migrations survive a foreign-key table rebuild

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 3: Replace lastrowid with RETURNING, and annotate with the Connection alias

Both changes exist to make a later Postgres port mechanical. `lastrowid` has no Postgres equivalent; `RETURNING id` works in both, and SQLite has supported it since 3.35.

**Files:**
- Modify: `src/yolk/foods.py:48`, `src/yolk/foods.py:194`
- Modify: `src/yolk/people.py:17`, `src/yolk/people.py:44`, `src/yolk/people.py:99`
- Modify: `src/yolk/planning/evaluate.py:38`, `src/yolk/planning/evaluate.py:60`
- Modify: `src/yolk/units.py`, `src/yolk/sources/usda.py` (annotations only)
- Modify: `tests/conftest.py`

**Interfaces:**
- Consumes: `yolk.db.Connection` from Task 1.
- Produces: no signature changes. Every function keeps its name, parameters, and return type. Only the annotation text and the id-fetching mechanism change.

- [ ] **Step 1: Confirm the existing tests cover every call site**

Run: `uv run python -m pytest tests/test_foods.py tests/test_people.py tests/test_recipes.py tests/test_evaluate.py -v`
Expected: PASS. These create foods, recipes, people, profiles, slots, plans, and entries, so they exercise all seven sites. They are the safety net for this task; no new tests are needed.

- [ ] **Step 2: Change the two sites in foods.py**

At `src/yolk/foods.py:38-48`, the insert currently ends `... VALUES ('item', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",` and is followed by `food_id = cur.lastrowid`. Append `RETURNING id` to the SQL string and read the row:

```python
        row = conn.execute(
            "INSERT INTO foods (kind, name, brand, role, kcal_100g, protein_g_100g, "
            "fat_g_100g, carb_g_100g, fiber_g_100g, source, source_ref, verified, "
            "notes) VALUES ('item', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
            (
                name, brand, role,
                macros.kcal, macros.protein_g, macros.fat_g,
                macros.carb_g, macros.fiber_g,
                source, source_ref, int(verified), notes,
            ),
        ).fetchone()
        food_id = row["id"]
```

Apply the same shape at `src/yolk/foods.py:194` (the `create_recipe` insert): append ` RETURNING id` to its SQL, bind the result to `row`, and set `food_id = row["id"]`.

- [ ] **Step 3: Change the three sites in people.py**

`create_person` becomes:

```python
    row = conn.execute(
        "INSERT INTO people (name) VALUES (?) RETURNING id", (name,)
    ).fetchone()
    conn.commit()
    return row["id"]
```

Do the same for the `macro_profiles` insert in `create_profile` (line 44) and the `slot_templates` insert in `create_slot` (line 99), where the id is bound to `slot_id` and used for the role inserts that follow.

- [ ] **Step 4: Change the two sites in evaluate.py**

`create_day_plan` (line 38) and `add_entry` (line 60): append ` RETURNING id` to each insert and return `row["id"]`.

- [ ] **Step 5: Swap the annotations**

In `src/yolk/foods.py`, `src/yolk/people.py`, `src/yolk/units.py`, `src/yolk/planning/evaluate.py`, and `src/yolk/sources/usda.py`:

- Replace `import sqlite3` with `from yolk.db import Connection`, unless the module uses `sqlite3` for something else. `usda.py` uses it only for the annotation.
- Replace every `conn: sqlite3.Connection` with `conn: Connection`.

Do not change `src/yolk/db/connection.py`, which legitimately uses `sqlite3` to open the connection.

- [ ] **Step 6: Update the conftest fixture**

In `tests/conftest.py`, the `person` fixture becomes:

```python
@pytest.fixture
def person(db):
    """Person 1, used by every person-scoped test."""
    row = db.execute(
        "INSERT INTO people (name) VALUES ('Jen') RETURNING id"
    ).fetchone()
    db.commit()
    return row["id"]
```

- [ ] **Step 7: Verify no call sites remain**

Run:

```bash
grep -rn "lastrowid" src tests
grep -rn "sqlite3.Connection" src
```

Expected: no output from either. If `grep` prints anything, a site was missed.

- [ ] **Step 8: Run the whole suite**

Run: `uv run python -m pytest`
Expected: PASS, 105 tests

- [ ] **Step 9: Commit**

```bash
git add src tests/conftest.py
git commit -m "refactor: use RETURNING id and a Connection alias for portability

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 4: Resolve the database path

**Files:**
- Create: `src/yolk/config.py`
- Modify: `.gitignore`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `yolk.config.REPO_ROOT: Path`
  - `yolk.config.DEFAULT_DB_NAME: str` — `"yolk.db"`
  - `yolk.config.database_path() -> Path`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_config.py`:

```python
from pathlib import Path

from yolk.config import DEFAULT_DB_NAME, REPO_ROOT, database_path


def test_default_path_is_the_repo_root(monkeypatch):
    monkeypatch.delenv("YOLK_DB", raising=False)
    assert database_path() == REPO_ROOT / DEFAULT_DB_NAME


def test_repo_root_contains_the_project_file():
    assert (REPO_ROOT / "pyproject.toml").is_file()


def test_environment_variable_wins(monkeypatch, tmp_path):
    target = tmp_path / "elsewhere.db"
    monkeypatch.setenv("YOLK_DB", str(target))
    assert database_path() == target


def test_a_user_path_is_expanded(monkeypatch):
    monkeypatch.setenv("YOLK_DB", "~/yolk.db")
    resolved = database_path()
    assert "~" not in str(resolved)
    assert resolved == Path.home() / "yolk.db"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yolk.config'`

- [ ] **Step 3: Write the module**

Create `src/yolk/config.py`:

```python
"""Where things live on disk.

One function owns the database path so that nothing else has to guess, and so
that pointing at a copy is an environment change rather than a code change.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# src/yolk/config.py -> src/yolk -> src -> the repository root
REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_DB_NAME = "yolk.db"


def database_path() -> Path:
    """The SQLite file to use: $YOLK_DB if set, otherwise yolk.db in the repo."""
    load_dotenv()
    configured = os.environ.get("YOLK_DB")
    if configured:
        return Path(configured).expanduser()
    return REPO_ROOT / DEFAULT_DB_NAME
```

- [ ] **Step 4: Run the tests**

Run: `uv run python -m pytest tests/test_config.py -v`
Expected: PASS, 4 tests

- [ ] **Step 5: Ignore the database file**

Append to `.gitignore`:

```
# yolk's local database. The committed export in data/ is the durable copy.
yolk.db
yolk.db-journal
yolk.db-wal
yolk.db-shm
```

- [ ] **Step 6: Confirm the export directory is not ignored**

Run: `git check-ignore -v data/foods.json`
Expected: no output and exit status 1, meaning `data/` is tracked normally. If it prints a rule, remove or narrow that rule.

- [ ] **Step 7: Run the whole suite and commit**

Run: `uv run python -m pytest`
Expected: PASS, 109 tests

```bash
git add src/yolk/config.py tests/test_config.py .gitignore
git commit -m "feat: resolve the database path from YOLK_DB or the repo root

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 5: Seed module

The plan-building loop currently lives in the golden test. It moves to `src/yolk/seed.py` so the test and the CLI share one code path and cannot drift. The seed also adds what the test never needed: slot templates, source notes, and approved review state.

**Files:**
- Create: `src/yolk/seed.py`
- Modify: `src/yolk/foods.py` (`create_item` gains `verified_on`)
- Modify: `tests/test_golden_keto_a.py`
- Test: `tests/test_seed.py`

**Interfaces:**
- Consumes: `create_item`, `create_person`, `create_profile`, `create_slot`, `create_day_plan`, `add_entry`, `Macros`, `yolk.config.REPO_ROOT`.
- Produces:
  - `yolk.seed.FIXTURE_PATH: Path` — `REPO_ROOT / "tests" / "fixtures" / "keto_plan_a.json"`
  - `yolk.seed.parse_time_of_day(slot_name: str) -> str` — `"Meal 1 - 6:30am Wake Up"` gives `"06:30"`. Raises `ValueError` when there is no time.
  - `yolk.seed.seed_keto_plan_a(conn: Connection, fixture_path: Path = FIXTURE_PATH) -> tuple[int, dict]` — returns the new plan's id and the parsed fixture.
  - `yolk.foods.create_item(..., verified_on: str | None = None)` — a new keyword-only parameter, defaulting to `None`. When `verified` is true and `verified_on` is `None`, today's date is recorded.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_seed.py`:

```python
import sqlite3

import pytest

from yolk.planning.evaluate import evaluate
from yolk.seed import parse_time_of_day, seed_keto_plan_a


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Meal 1 - 6:30am Wake Up", "06:30"),
        ("Meal 2 - 8:30am Breakfast - Yogurt + granola", "08:30"),
        ("Meal 4 - 2:00pm Lunch - Salad", "14:00"),
        ("Meal 6 - 6:00pm Dinner - Pasta", "18:00"),
        ("Meal 7 - 12:00am Midnight", "00:00"),
        ("Meal 8 - 12:00pm Noon", "12:00"),
    ],
)
def test_time_of_day_is_parsed_from_the_slot_name(name, expected):
    assert parse_time_of_day(name) == expected


def test_a_slot_name_without_a_time_raises():
    with pytest.raises(ValueError, match="no time"):
        parse_time_of_day("Meal 9 - whenever")


def test_seed_creates_one_slot_template_per_slot(db):
    plan_id, spec = seed_keto_plan_a(db)
    rows = db.execute(
        "SELECT slot_no, name, time_of_day FROM slot_templates ORDER BY slot_no"
    ).fetchall()
    assert [r["slot_no"] for r in rows] == [s["slot_no"] for s in spec["slots"]]
    assert [r["name"] for r in rows] == [s["name"] for s in spec["slots"]]
    assert rows[0]["time_of_day"] == "06:30"


def test_seeded_foods_are_approved_with_their_source_note(db):
    seed_keto_plan_a(db)
    row = db.execute(
        "SELECT verified, verified_on, notes FROM foods WHERE name = ?",
        ("Buff Chick Coffee",),
    ).fetchone()
    assert row["verified"] == 1
    assert row["verified_on"] is not None
    assert "22 g" in row["notes"]


def test_seed_reproduces_the_reported_calories(db):
    plan_id, spec = seed_keto_plan_a(db)
    result = evaluate(db, plan_id)
    assert result.totals.kcal == pytest.approx(spec["reported_totals"]["kcal"], rel=0.01)


def test_seeding_twice_raises_rather_than_duplicating(db):
    """The second Jen violates people.name's UNIQUE constraint."""
    seed_keto_plan_a(db)
    with pytest.raises(sqlite3.IntegrityError):
        seed_keto_plan_a(db)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_seed.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yolk.seed'`

- [ ] **Step 3: Let create_item record a verification date**

In `src/yolk/foods.py`, add `verified_on: str | None = None` to `create_item`'s keyword-only parameters, immediately after `verified: bool = False`. Before the insert, add:

```python
    if verified and verified_on is None:
        verified_on = date.today().isoformat()
```

Add `verified_on` to the insert's column list and `verified_on` to its parameter tuple, directly after `verified`. The module already imports `datetime`; add `date` to that import if it is not there.

- [ ] **Step 4: Write the seed module**

Create `src/yolk/seed.py`:

```python
"""Build the Keto Plan A fixture into a database.

The golden test and `yolk init --seed` both call this, so a change to how the
plan is built cannot make the test and the real database disagree. The fixture
lives under tests/ and is not packaged: seeding is a development and first-run
convenience, not a runtime feature.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from yolk.config import REPO_ROOT
from yolk.db import Connection
from yolk.foods import create_item
from yolk.macros import Macros
from yolk.people import create_person, create_profile, create_slot
from yolk.planning.evaluate import add_entry, create_day_plan

FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "keto_plan_a.json"

_TIME = re.compile(r"(\d{1,2}):(\d{2})\s*(am|pm)", re.IGNORECASE)


def parse_time_of_day(slot_name: str) -> str:
    """Pull `06:30` out of `"Meal 1 - 6:30am Wake Up"`.

    Raises rather than guessing: a slot with no stated time is a fixture
    problem, and a made-up time would be a plausible wrong answer.
    """
    match = _TIME.search(slot_name)
    if match is None:
        raise ValueError(
            f"Slot name {slot_name!r} has no time in it, so time_of_day cannot "
            f"be derived. Expected something like '6:30am'."
        )
    hour, minute, meridiem = int(match.group(1)), match.group(2), match.group(3).lower()
    if meridiem == "am":
        hour = 0 if hour == 12 else hour
    else:
        hour = 12 if hour == 12 else hour + 12
    return f"{hour:02d}:{minute}"


def seed_keto_plan_a(
    conn: Connection, fixture_path: Path = FIXTURE_PATH
) -> tuple[int, dict]:
    """Create the person, profile, slots, foods, and plan from the fixture.

    Foods are marked verified: every fixture entry's source_note cites a
    product label or a USDA id, and was checked when the fixture was built.
    """
    spec = json.loads(fixture_path.read_text(encoding="utf-8"))
    today = date.today().isoformat()

    person_id = create_person(conn, "Jen")
    profile_id = create_profile(
        conn, person_id,
        name=spec["profile"]["name"],
        effective_on=spec["profile"]["effective_on"],
        kcal=spec["profile"]["kcal"],
        fat_pct=spec["profile"]["fat_pct"],
        carb_pct=spec["profile"]["carb_pct"],
        protein_pct=spec["profile"]["protein_pct"],
    )
    plan_id = create_day_plan(conn, person_id, profile_id, name=spec["plan_name"])

    food_ids: dict[str, int] = {}
    for slot in spec["slots"]:
        create_slot(
            conn, person_id, profile_id,
            slot_no=slot["slot_no"],
            name=slot["name"],
            time_of_day=parse_time_of_day(slot["name"]),
            roles=tuple(dict.fromkeys(e["role"] for e in slot["entries"])),
        )
        for entry in slot["entries"]:
            name = entry["food"]
            if name not in food_ids:
                m = entry["macros_100g"]
                food_ids[name] = create_item(
                    conn,
                    name=name,
                    role=entry["role"],
                    macros=Macros(
                        kcal=m["kcal"],
                        protein_g=m["protein_g"],
                        fat_g=m["fat_g"],
                        carb_g=m["carb_g"],
                    ),
                    source=entry.get("source", "manual"),
                    units=entry.get("units") or None,
                    notes=entry.get("source_note"),
                    verified=True,
                    verified_on=today,
                )
            add_entry(
                conn, plan_id,
                slot_no=slot["slot_no"],
                food_id=food_ids[name],
                qty=entry["qty"],
                unit=entry["unit"],
            )
    return plan_id, spec
```

`roles` uses `dict.fromkeys` rather than `set` so the order is the order the entries appear, which keeps the inserted rows deterministic.

- [ ] **Step 5: Point the golden test at the seed**

In `tests/test_golden_keto_a.py`, delete the body of the `keto_a` fixture and the now-unused imports (`json`, `Path`, `create_item`, `Macros`, `create_person`, `create_profile`, `add_entry`, `create_day_plan`, and the `FIXTURE` constant). The fixture becomes:

```python
import pytest

from yolk.planning.evaluate import evaluate
from yolk.seed import seed_keto_plan_a


@pytest.fixture
def keto_a(db):
    """Build the plan described by the fixture and return its id."""
    return seed_keto_plan_a(db)
```

Leave the module docstring and every test below it untouched. They already unpack `plan_id, spec`, which is what the seed returns.

- [ ] **Step 6: Run the seed and golden tests**

Run: `uv run python -m pytest tests/test_seed.py tests/test_golden_keto_a.py -v`
Expected: PASS. The golden tests must still assert the same totals, unchanged.

- [ ] **Step 7: Run the whole suite and commit**

Run: `uv run python -m pytest`
Expected: PASS, 120 tests

```bash
git add src/yolk/seed.py src/yolk/foods.py tests/test_seed.py tests/test_golden_keto_a.py
git commit -m "feat: seed Keto Plan A from the fixture the golden test uses

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 6: Export and import

**Files:**
- Create: `src/yolk/snapshot.py`
- Test: `tests/test_snapshot.py`

**Interfaces:**
- Consumes: `apply_migrations`, `latest_version`, `MigrationError`, `connect`, `seed_keto_plan_a`.
- Produces:
  - `yolk.snapshot.TABLES: tuple[str, ...]` — every data table, in foreign-key dependency order.
  - `yolk.snapshot.DEFAULT_DIR: Path` — `REPO_ROOT / "data"`
  - `yolk.snapshot.SnapshotError(YolkError)`
  - `yolk.snapshot.export_database(conn: Connection, out_dir: Path = DEFAULT_DIR) -> list[Path]`
  - `yolk.snapshot.import_database(conn: Connection, in_dir: Path = DEFAULT_DIR) -> dict[str, int]` — table name to row count.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_snapshot.py`:

```python
import json

import pytest

from yolk.db.connection import connect, create_schema
from yolk.seed import seed_keto_plan_a
from yolk.snapshot import (
    SnapshotError,
    export_database,
    import_database,
)


@pytest.fixture
def seeded(db):
    seed_keto_plan_a(db)
    return db


def _fresh():
    conn = connect(":memory:")
    create_schema(conn)
    return conn


def test_export_writes_one_file_per_table(seeded, tmp_path):
    written = export_database(seeded, tmp_path)
    names = {path.name for path in written}
    assert "foods.json" in names
    assert "day_plans.json" in names
    assert "schema_version.json" in names


def test_export_is_sorted_and_indented(seeded, tmp_path):
    export_database(seeded, tmp_path)
    text = (tmp_path / "people.json").read_text(encoding="utf-8")
    assert text.endswith("\n")
    rows = json.loads(text)
    assert rows[0] == {"id": 1, "name": "Jen"}
    assert list(rows[0]) == sorted(rows[0])


def test_export_is_deterministic(seeded, tmp_path):
    export_database(seeded, tmp_path)
    first = (tmp_path / "foods.json").read_text(encoding="utf-8")
    export_database(seeded, tmp_path)
    assert (tmp_path / "foods.json").read_text(encoding="utf-8") == first


def test_round_trip_is_byte_identical(seeded, tmp_path):
    out_a, out_b = tmp_path / "a", tmp_path / "b"
    export_database(seeded, out_a)

    restored = _fresh()
    import_database(restored, out_a)
    export_database(restored, out_b)

    for path in sorted(out_a.glob("*.json")):
        assert path.read_bytes() == (out_b / path.name).read_bytes(), path.name
    restored.close()


def test_import_restores_the_plan(seeded, tmp_path):
    export_database(seeded, tmp_path)
    restored = _fresh()
    counts = import_database(restored, tmp_path)

    assert counts["foods"] > 0
    original = seeded.execute("SELECT count(*) AS n FROM day_plan_entries").fetchone()["n"]
    assert restored.execute(
        "SELECT count(*) AS n FROM day_plan_entries"
    ).fetchone()["n"] == original
    restored.close()


def test_import_refuses_a_database_with_rows(seeded, tmp_path):
    export_database(seeded, tmp_path)
    with pytest.raises(SnapshotError, match="already has data"):
        import_database(seeded, tmp_path)


def test_import_refuses_a_version_mismatch(seeded, tmp_path):
    export_database(seeded, tmp_path)
    (tmp_path / "schema_version.json").write_text(
        json.dumps([{"applied_on": "2026-01-01", "version": 99}], indent=2) + "\n",
        encoding="utf-8",
    )
    restored = _fresh()
    with pytest.raises(SnapshotError, match="version"):
        import_database(restored, tmp_path)
    restored.close()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_snapshot.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yolk.snapshot'`

- [ ] **Step 3: Write the module**

Create `src/yolk/snapshot.py`:

```python
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
from yolk.db.migrate import latest_version
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
```

- [ ] **Step 4: Run the tests**

Run: `uv run python -m pytest tests/test_snapshot.py -v`
Expected: PASS, 7 tests

- [ ] **Step 5: Run the whole suite and commit**

Run: `uv run python -m pytest`
Expected: PASS, 127 tests

```bash
git add src/yolk/snapshot.py tests/test_snapshot.py
git commit -m "feat: export the database to deterministic JSON and back

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 7: The yolk command

`yolk serve` belongs to slice 2 and is deliberately not built here. Adding it now would mean a subcommand that cannot work.

**Files:**
- Create: `src/yolk/cli.py`
- Create: `src/yolk/__main__.py`
- Modify: `pyproject.toml`
- Modify: `README.md`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `connect`, `apply_migrations`, `seed_keto_plan_a`, `export_database`, `import_database`, `database_path`, `DEFAULT_DIR`.
- Produces:
  - `yolk.cli.main(argv: list[str] | None = None) -> int` — the console script entry point. Returns 0 on success and 1 on a handled error, after printing the message to stderr.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cli.py`:

```python
import pytest

from yolk.cli import main
from yolk.db.connection import connect


@pytest.fixture
def db_path(monkeypatch, tmp_path):
    path = tmp_path / "yolk.db"
    monkeypatch.setenv("YOLK_DB", str(path))
    return path


def test_init_creates_a_migrated_database(db_path, capsys):
    assert main(["init"]) == 0
    assert db_path.is_file()

    conn = connect(db_path)
    names = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert "foods" in names
    assert "schema_version" in names
    conn.close()


def test_init_twice_is_a_no_op(db_path):
    assert main(["init"]) == 0
    assert main(["init"]) == 0


def test_init_with_seed_creates_the_plan(db_path):
    assert main(["init", "--seed"]) == 0
    conn = connect(db_path)
    row = conn.execute("SELECT name FROM day_plans").fetchone()
    assert row["name"] == "Keto Meal Plan A"
    conn.close()


def test_seeding_an_already_seeded_database_is_refused(db_path, capsys):
    main(["init", "--seed"])
    assert main(["init", "--seed"]) == 1
    assert "already has" in capsys.readouterr().err


def test_export_then_import_into_a_fresh_database(db_path, tmp_path, monkeypatch):
    main(["init", "--seed"])
    out = tmp_path / "export"
    assert main(["export", "--out", str(out)]) == 0
    assert (out / "foods.json").is_file()

    second = tmp_path / "second.db"
    monkeypatch.setenv("YOLK_DB", str(second))
    assert main(["init"]) == 0
    assert main(["import", "--from", str(out)]) == 0

    conn = connect(second)
    assert conn.execute("SELECT count(*) AS n FROM foods").fetchone()["n"] > 0
    conn.close()


def test_a_command_on_a_missing_database_explains_itself(db_path, capsys):
    assert main(["export"]) == 1
    assert "yolk init" in capsys.readouterr().err
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yolk.cli'`

- [ ] **Step 3: Write the CLI**

Create `src/yolk/cli.py`:

```python
"""The `yolk` command: create, migrate, export, and import the database."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from yolk.config import database_path
from yolk.db.connection import connect
from yolk.db.migrate import apply_migrations
from yolk.errors import YolkError
from yolk.seed import seed_keto_plan_a
from yolk.snapshot import DEFAULT_DIR, export_database, import_database


def _require_existing_database() -> Path:
    path = database_path()
    if not path.is_file():
        raise YolkError(
            f"No database at {path}. Run `yolk init` first, or set YOLK_DB to "
            f"point at an existing one."
        )
    return path


def _cmd_init(args: argparse.Namespace) -> int:
    path = database_path()
    existed = path.is_file()
    conn = connect(path)
    try:
        applied = apply_migrations(conn)
        if not existed:
            print(f"Created {path}")
        print(
            f"Applied migrations: {', '.join(str(v) for v in applied)}"
            if applied
            else "Already up to date."
        )
        if args.seed:
            if conn.execute("SELECT count(*) AS n FROM day_plans").fetchone()["n"]:
                raise YolkError(
                    f"{path} already has plans in it, so seeding would duplicate "
                    f"them. Seed only an empty database."
                )
            plan_id, _ = seed_keto_plan_a(conn)
            print(f"Seeded Keto Plan A as plan {plan_id}.")
    finally:
        conn.close()
    return 0


def _cmd_migrate(args: argparse.Namespace) -> int:
    conn = connect(_require_existing_database())
    try:
        applied = apply_migrations(conn)
        print(
            f"Applied migrations: {', '.join(str(v) for v in applied)}"
            if applied
            else "Already up to date."
        )
    finally:
        conn.close()
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    conn = connect(_require_existing_database())
    try:
        written = export_database(conn, Path(args.out))
        print(f"Wrote {len(written)} file(s) to {args.out}")
    finally:
        conn.close()
    return 0


def _cmd_import(args: argparse.Namespace) -> int:
    conn = connect(_require_existing_database())
    try:
        counts = import_database(conn, Path(getattr(args, "from")))
        print(f"Loaded {sum(counts.values())} row(s) from {getattr(args, 'from')}")
    finally:
        conn.close()
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="yolk", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="create the database and apply migrations")
    init.add_argument(
        "--seed", action="store_true", help="also load the Keto Plan A fixture"
    )
    init.set_defaults(func=_cmd_init)

    migrate = sub.add_parser("migrate", help="apply pending migrations")
    migrate.set_defaults(func=_cmd_migrate)

    export = sub.add_parser("export", help="write every table to JSON")
    export.add_argument("--out", default=str(DEFAULT_DIR))
    export.set_defaults(func=_cmd_export)

    load = sub.add_parser("import", help="load JSON into an empty database")
    load.add_argument("--from", dest="from", default=str(DEFAULT_DIR))
    load.set_defaults(func=_cmd_import)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return args.func(args)
    except YolkError as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Register the console script and the module entry point**

In `pyproject.toml`, add after the `[project.optional-dependencies]` block:

```toml
[project.scripts]
yolk = "yolk.cli:main"
```

Then create `src/yolk/__main__.py`, so the command can be run as a module:

```python
"""Entry point for `python -m yolk`.

The console script above generates a small launcher executable in the
virtual environment's Scripts directory. Windows Smart App Control blocks
those, because a launcher stamped out locally has no reputation, while the
interpreter it wraps does. Running the module skips the launcher entirely,
so this is the invocation the documentation uses.
"""

from yolk.cli import main

raise SystemExit(main())
```

- [ ] **Step 5: Run the tests**

Run: `uv run python -m pytest tests/test_cli.py -v`
Expected: PASS, 6 tests

- [ ] **Step 6: Run it for real**

```bash
uv run python -m yolk init --seed
```

Expected: prints the created path, the applied migration, and the seeded plan id. Then confirm the file is ignored:

```bash
git status --short
```

Expected: `yolk.db` does not appear.

- [ ] **Step 7: Take the first export and look at it**

```bash
uv run python -m yolk export
git status --short
```

Expected: `data/` appears as untracked. Open `data/foods.json` and read it. **Before committing it, decide deliberately whether this repository should hold your plans and profiles**, per the spec's note in §4.2. If the answer is no, stop and say so rather than committing `data/`.

- [ ] **Step 8: Document setup in the README**

Append to `README.md`:

```markdown
## Setup

Requires Python 3.14 and [uv](https://docs.astral.sh/uv/).

```bash
python -m venv .venv
uv sync --extra dev
cp .env.example .env   # then add your USDA key
uv run python -m yolk init --seed
```

Create the virtual environment with `python -m venv`, not with uv. Windows
Smart App Control blocks the small launcher executables a tool generates
inside `Scripts/`, and uv's environments use one; a stdlib environment copies
the real interpreter instead. For the same reason, run everything as a module:
`uv run python -m pytest`, not `uv run pytest`.

`yolk init` creates the database and applies every migration. `--seed` loads
Keto Plan A so there is something real to look at. Get a free USDA key at
https://api.data.gov/signup.

The database file itself is not committed. `uv run python -m yolk export` writes every
table to `data/` as JSON, and that is what git tracks. `uv run python -m yolk import`
loads it back into an empty database.

| Command | Does |
|---|---|
| `uv run python -m yolk init [--seed]` | Create the database, apply migrations, optionally seed |
| `uv run python -m yolk migrate` | Apply pending migrations |
| `uv run python -m yolk export [--out DIR]` | Write every table to JSON |
| `uv run python -m yolk import [--from DIR]` | Load JSON into an empty database |

Set `YOLK_DB` to use a database somewhere other than `yolk.db` in the repo root.
```

- [ ] **Step 9: Add the env example file**

Create `.env.example`:

```
USDA_API_KEY=
```

The README tells a new person to copy it, and `.env` itself stays ignored.

- [ ] **Step 10: Run the whole suite and commit**

Run: `uv run python -m pytest`
Expected: PASS, 133 tests

```bash
git add src/yolk/cli.py src/yolk/__main__.py tests/test_cli.py pyproject.toml README.md .env.example
git commit -m "feat: add the yolk command for init, migrate, export, and import

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Done when

- `uv run python -m pytest` passes, at 133 tests.
- `uv run python -m yolk init --seed` on a fresh checkout produces a database whose Keto Plan A evaluation matches the golden test's totals.
- `grep -rn "lastrowid\|sqlite3.Connection" src` prints nothing.
- `git status --short` never shows `yolk.db`.
- Export, import into a fresh database, and export again produce identical files.

Slice 2 (reading a plan in the browser) gets its own plan, and adds `yolk serve`.
