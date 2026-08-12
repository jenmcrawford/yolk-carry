# Foundation: Schema, Food Library, and Day Evaluation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the data foundation and macro engine for `yolk`, ending at a passing golden-file test that reproduces a coach-authored meal plan's macro totals from its own ingredients.

**Architecture:** SQLite holds a single `foods` table with an `item`/`recipe` discriminator; recipes compose other foods through `food_components`, so recipes nest. Every food stores macros per 100 g, and all display units (tbsp, scoop, patty) resolve to grams through a per-food `food_units` table. A pure `evaluate()` function aggregates a day plan's entries against a dated macro profile.

**Tech Stack:** Python 3.14, `uv`, stdlib `sqlite3`, `pytest`, `httpx` (USDA client), `python-dotenv`.

## Global Constraints

- Python `>=3.14`, managed by `uv`. Run everything through `uv run`.
- **Portable SQL only:** explicit column types, explicit `INTEGER PRIMARY KEY`, foreign keys declared. Never rely on implicit `rowid`. A later Postgres migration must stay possible.
- **All macros are stored per 100 g.** No exceptions. Servings and display units derive from grams.
- **Never guess a unit conversion.** A missing conversion raises, naming the food and the unit.
- **Never estimate a recipe yield.** A recipe without `cooked_yield_g` refuses to compute per-100 g.
- **Never insert a partial food row.** API failures raise; they do not write.
- Person dimension is present in every person-scoped table. Jen is person 1.
- Tolerance defaults: kcal ±1%, protein ±8 g, fat% and carb% ±3 points. Stored per profile, never hardcoded in logic. (Protein was ±2 g until Task 9 measured the source plan — see Amendment C.)
- Secrets come from `.env` (`USDA_API_KEY`). `.env` is gitignored and must stay that way.
- Commit after every task. Conventional commit prefixes (`feat:`, `test:`, `chore:`).

## Amendments during execution

Two defects were found in this plan's own sample code during the Task 5 review. In both,
the sample code contradicted the Global Constraints above. **The constraints govern** — the
code below is amended accordingly. Recorded here rather than silently edited, so the reason
survives.

**A. `create_recipe` must be atomic (Task 5).** As originally written it called
`conn.commit()` and *then* `recompute_recipe()`, leaving the recompute outside the
transaction. A recipe nesting an existing yield-less recipe raises `MissingYieldError` from
that recompute while the parent row and its components stay committed — a partial write on a
raised call, violating "Never insert a partial food row."

Amended: inside the existing `try`, after the component and unit inserts, compute via
`_macros_resolved(conn, food_id, frozenset())` and write the result with an `UPDATE` before
the single `conn.commit()`. The post-commit `recompute_recipe` call is removed. Both
`create_recipe` and `recompute_recipe` share a private `_write_computed_macros(conn,
food_id, macros)` helper that does not commit; `recompute_recipe` remains public and commits
for standalone use. Covered by a test asserting that a failed nested recompute leaves neither
a `foods` row nor `food_components` rows behind.

**C. Protein tolerance widened from ±2 g to ±8 g (Tasks 1, 7).** Task 9's extraction measured
Keto Plan A's own stated totals against its profile: calories land within 0.17%, but protein
is 197.455 g against a 204.25 g target — a 6.8 g (3.33%) miss. A ±2 g default would classify
a professionally authored plan as out of band, making the tolerance an aspiration rather than
a description of the framework. Owner ruled: protein default becomes ±8 g (~4% with
headroom); calories stay hard at ±1%; fat and carb stay at ±3 percentage points. Changed in
`schema.sql`'s `macro_profiles.protein_tol_g` DEFAULT, `people.py`'s `create_profile`
default, and the assertion in `tests/test_people.py`. No logic reads a hardcoded tolerance —
`evaluate()` sources all three from the profile row, which is what made this a data change.

**D. Final-review fixes (all tasks).** The whole-branch review found no Critical issues but
two Important ones, both fixed before merge. First, the regression test added in Task 4's fix
round to guard `create_item`'s rollback never exercised it — it passed an invalid `source`, so
the food insert failed before the unit insert was reached and the "no orphan row" assertion
was vacuously true. Second, `create_slot` had the same partial-write shape Amendment A
eliminated in `foods.py`: a slot row followed by an unguarded loop of role inserts. Both are
now wrapped and tested, as is `add_unit`. Also applied: three schema guards (profile
percentages must sum to 100; `slot_template_roles.role` takes the same enum CHECK as
`foods.role`; items must carry all four macros, not just calories), `PRAGMA user_version = 1`,
two replaced vacuous tests, and two corrected docstrings.

**Deferred deliberately to the next plan:** seven writers call `conn.commit()` unconditionally
with no rollback, so callers cannot compose two writes atomically. `resolve_flex()` and
`substitute()` are both inherently multi-row and will define the real requirement — that is
the right moment to introduce a `transaction(conn)` context manager and stop the low-level
writers from committing. Also deferred: the response cache's CWD-relative path, unifying the
error taxonomy under `YolkError`, and a person/profile ownership guard on `create_day_plan`.

**B. `macros_per_100g` must refuse uncomputed recipes (Tasks 4 and 5).** It coalesced NULL
macro columns to `0.0`. Harmless for items — `CHECK (kind = 'recipe' OR kcal_100g IS NOT
NULL)` guarantees they have macros — but recipes are allowed NULL macros, so calling
`macros_per_100g` or `portion_macros` on an unweighed recipe returned zeros instead of
raising, violating "Never estimate a recipe yield."

Amended: `macros_per_100g` selects `kind` and raises `MissingYieldError` when the food is a
recipe with NULL `kcal_100g`, naming the recipe and directing the caller to set
`cooked_yield_g` and run `recompute_recipe`. Items are unaffected. `_macros_resolved` calls
`macros_per_100g` only on its `kind='item'` branch, and `recompute_recipe` routes through
`_macros_resolved`, so neither is affected. Covered by tests asserting both functions raise
on an unweighed recipe.

---

### Task 1: Project scaffolding and database schema

**Files:**
- Modify: `pyproject.toml`
- Create: `src/yolk/__init__.py`
- Create: `src/yolk/db/__init__.py`
- Create: `src/yolk/db/schema.sql`
- Create: `src/yolk/db/connection.py`
- Create: `tests/conftest.py`
- Test: `tests/test_schema.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `connect(path: str | Path) -> sqlite3.Connection`, `create_schema(conn: sqlite3.Connection) -> None`, and the pytest fixture `db` yielding an in-memory connection with the schema applied.

- [ ] **Step 1: Configure the project**

Replace `pyproject.toml` with:

```toml
[project]
name = "yolk-carry"
version = "0.1.0"
description = "Inventory-aware meal planning that keeps you on framework"
readme = "README.md"
requires-python = ">=3.14"
dependencies = [
    "httpx>=0.28",
    "python-dotenv>=1.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/yolk"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

Then run:

```bash
uv sync --extra dev
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_schema.py`:

```python
import sqlite3

import pytest


def test_schema_creates_expected_tables(db):
    rows = db.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
    ).fetchall()
    names = {r["name"] for r in rows}
    expected = {
        "people", "tags", "food_tags", "foods", "food_units", "food_components",
        "protocols", "protocol_rules", "person_protocols",
        "macro_profiles", "slot_templates", "slot_template_roles",
        "day_plans", "day_plan_entries", "inventory",
    }
    assert expected <= names


def test_foreign_keys_are_enforced(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO food_units (food_id, unit, grams) VALUES (9999, 'tbsp', 14.0)"
        )


def test_item_requires_macros(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO foods (kind, name, role, source) "
            "VALUES ('item', 'Mystery', 'protein', 'manual')"
        )
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_schema.py -v`
Expected: FAIL — `fixture 'db' not found`.

- [ ] **Step 4: Write the schema**

Create `src/yolk/db/schema.sql`:

```sql
PRAGMA foreign_keys = ON;

CREATE TABLE people (
    id      INTEGER PRIMARY KEY,
    name    TEXT NOT NULL UNIQUE
);

CREATE TABLE tags (
    id      INTEGER PRIMARY KEY,
    name    TEXT NOT NULL UNIQUE,
    kind    TEXT NOT NULL
            CHECK (kind IN ('allergen', 'ingredient_class', 'diet', 'attribute'))
);

CREATE TABLE foods (
    id              INTEGER PRIMARY KEY,
    kind            TEXT NOT NULL CHECK (kind IN ('item', 'recipe')),
    name            TEXT NOT NULL,
    brand           TEXT NOT NULL DEFAULT '',
    role            TEXT NOT NULL
                    CHECK (role IN ('protein', 'carb', 'fat', 'veg',
                                    'sauce', 'beverage', 'supplement')),
    kcal_100g       REAL,
    protein_g_100g  REAL,
    fat_g_100g      REAL,
    carb_g_100g     REAL,
    fiber_g_100g    REAL,
    cooked_yield_g  REAL CHECK (cooked_yield_g IS NULL OR cooked_yield_g > 0),
    instructions    TEXT,
    source          TEXT NOT NULL
                    CHECK (source IN ('usda', 'off', 'label', 'manual',
                                      'computed', 'cronometer')),
    source_ref      TEXT,
    verified        INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0, 1)),
    verified_on     TEXT,
    computed_at     TEXT,
    notes           TEXT,
    UNIQUE (name, brand),
    -- items must carry macros; recipes may compute them later
    CHECK (kind = 'recipe' OR kcal_100g IS NOT NULL)
);

CREATE TABLE food_tags (
    food_id INTEGER NOT NULL REFERENCES foods(id) ON DELETE CASCADE,
    tag_id  INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (food_id, tag_id)
);

CREATE TABLE food_units (
    id                  INTEGER PRIMARY KEY,
    food_id             INTEGER NOT NULL REFERENCES foods(id) ON DELETE CASCADE,
    unit                TEXT NOT NULL,
    grams               REAL NOT NULL CHECK (grams > 0),
    is_default_display  INTEGER NOT NULL DEFAULT 0 CHECK (is_default_display IN (0, 1)),
    UNIQUE (food_id, unit)
);

CREATE TABLE food_components (
    id              INTEGER PRIMARY KEY,
    parent_food_id  INTEGER NOT NULL REFERENCES foods(id) ON DELETE CASCADE,
    child_food_id   INTEGER NOT NULL REFERENCES foods(id) ON DELETE RESTRICT,
    qty             REAL NOT NULL CHECK (qty > 0),
    unit            TEXT NOT NULL,
    flex            INTEGER NOT NULL DEFAULT 0 CHECK (flex IN (0, 1)),
    flex_min_g      REAL,
    flex_max_g      REAL,
    note            TEXT,
    CHECK (parent_food_id <> child_food_id),
    CHECK (flex = 0 OR (flex_min_g IS NOT NULL
                        AND flex_max_g IS NOT NULL
                        AND flex_min_g <= flex_max_g))
);

CREATE TABLE protocols (
    id                  INTEGER PRIMARY KEY,
    name                TEXT NOT NULL,
    owner_person_id     INTEGER REFERENCES people(id) ON DELETE CASCADE,
    description         TEXT,
    UNIQUE (name, owner_person_id)
);

CREATE TABLE protocol_rules (
    id              INTEGER PRIMARY KEY,
    protocol_id     INTEGER NOT NULL REFERENCES protocols(id) ON DELETE CASCADE,
    rule            TEXT NOT NULL CHECK (rule IN ('exclude', 'limit', 'prefer')),
    target          TEXT NOT NULL CHECK (target IN ('tag', 'food')),
    target_id       INTEGER NOT NULL,
    limit_g_per_day REAL,
    hard_exclude    INTEGER NOT NULL DEFAULT 0 CHECK (hard_exclude IN (0, 1)),
    note            TEXT,
    CHECK (rule <> 'limit' OR limit_g_per_day IS NOT NULL)
);

CREATE TABLE person_protocols (
    id          INTEGER PRIMARY KEY,
    person_id   INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    protocol_id INTEGER NOT NULL REFERENCES protocols(id) ON DELETE CASCADE,
    active      INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    started_on  TEXT,
    ended_on    TEXT
);

CREATE TABLE macro_profiles (
    id              INTEGER PRIMARY KEY,
    person_id       INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    effective_on    TEXT NOT NULL,
    kcal            REAL NOT NULL CHECK (kcal > 0),
    fat_pct         REAL NOT NULL,
    carb_pct        REAL NOT NULL,
    protein_pct     REAL NOT NULL,
    kcal_tol_pct    REAL NOT NULL DEFAULT 1.0,
    protein_tol_g   REAL NOT NULL DEFAULT 2.0,
    macro_pct_tol   REAL NOT NULL DEFAULT 3.0,
    UNIQUE (person_id, name, effective_on)
);

CREATE TABLE slot_templates (
    id          INTEGER PRIMARY KEY,
    person_id   INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    profile_id  INTEGER NOT NULL REFERENCES macro_profiles(id) ON DELETE CASCADE,
    slot_no     INTEGER NOT NULL,
    name        TEXT NOT NULL,
    time_of_day TEXT NOT NULL,
    portable    INTEGER NOT NULL DEFAULT 0 CHECK (portable IN (0, 1)),
    fixed       INTEGER NOT NULL DEFAULT 0 CHECK (fixed IN (0, 1)),
    notes       TEXT,
    UNIQUE (profile_id, slot_no)
);

CREATE TABLE slot_template_roles (
    id                  INTEGER PRIMARY KEY,
    slot_template_id    INTEGER NOT NULL REFERENCES slot_templates(id) ON DELETE CASCADE,
    role                TEXT NOT NULL,
    min_count           INTEGER NOT NULL DEFAULT 1 CHECK (min_count >= 0),
    UNIQUE (slot_template_id, role)
);

CREATE TABLE day_plans (
    id              INTEGER PRIMARY KEY,
    person_id       INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    profile_id      INTEGER NOT NULL REFERENCES macro_profiles(id) ON DELETE RESTRICT,
    name            TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'archived')),
    parent_plan_id  INTEGER REFERENCES day_plans(id) ON DELETE SET NULL,
    created_at      TEXT NOT NULL,
    notes           TEXT,
    UNIQUE (person_id, name)
);

CREATE TABLE day_plan_entries (
    id          INTEGER PRIMARY KEY,
    day_plan_id INTEGER NOT NULL REFERENCES day_plans(id) ON DELETE CASCADE,
    slot_no     INTEGER NOT NULL,
    food_id     INTEGER NOT NULL REFERENCES foods(id) ON DELETE RESTRICT,
    qty         REAL NOT NULL CHECK (qty > 0),
    unit        TEXT NOT NULL,
    flex        INTEGER NOT NULL DEFAULT 0 CHECK (flex IN (0, 1)),
    flex_min_g  REAL,
    flex_max_g  REAL,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    CHECK (flex = 0 OR (flex_min_g IS NOT NULL
                        AND flex_max_g IS NOT NULL
                        AND flex_min_g <= flex_max_g))
);

CREATE TABLE inventory (
    id          INTEGER PRIMARY KEY,
    person_id   INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    food_id     INTEGER NOT NULL REFERENCES foods(id) ON DELETE CASCADE,
    location    TEXT NOT NULL CHECK (location IN ('pantry', 'fridge', 'freezer')),
    qty_g       REAL CHECK (qty_g IS NULL OR qty_g >= 0),
    portions    REAL CHECK (portions IS NULL OR portions >= 0),
    status      TEXT NOT NULL DEFAULT 'have'
                CHECK (status IN ('have', 'low', 'out')),
    updated_at  TEXT NOT NULL,
    note        TEXT,
    UNIQUE (person_id, food_id, location)
);

CREATE INDEX idx_food_components_parent ON food_components(parent_food_id);
CREATE INDEX idx_food_components_child ON food_components(child_food_id);
CREATE INDEX idx_day_plan_entries_plan ON day_plan_entries(day_plan_id);
CREATE INDEX idx_food_units_food ON food_units(food_id);
```

- [ ] **Step 5: Write the connection module**

Create `src/yolk/db/connection.py`:

```python
"""SQLite connection management and schema creation."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def connect(path: str | Path) -> sqlite3.Connection:
    """Open a connection with row access by name and foreign keys enforced."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    """Apply schema.sql to an empty database."""
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    # executescript issues an implicit COMMIT that resets the pragma
    conn.execute("PRAGMA foreign_keys = ON")
    conn.commit()
```

Create empty `src/yolk/__init__.py` and `src/yolk/db/__init__.py`.

- [ ] **Step 6: Write the test fixture**

Create `tests/conftest.py`:

```python
import pytest

from yolk.db.connection import connect, create_schema


@pytest.fixture
def db():
    conn = connect(":memory:")
    create_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def person(db):
    """Person 1, used by every person-scoped test."""
    cur = db.execute("INSERT INTO people (name) VALUES ('Jen')")
    db.commit()
    return cur.lastrowid
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_schema.py -v`
Expected: 3 passed.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock src/yolk tests/conftest.py tests/test_schema.py
git commit -m "feat: add database schema and connection layer"
```

---

### Task 2: Macros value type

**Files:**
- Create: `src/yolk/macros.py`
- Test: `tests/test_macros.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Macros` (frozen dataclass with fields `kcal`, `protein_g`, `fat_g`, `carb_g`, `fiber_g`, all `float`, all defaulting to `0.0`), supporting `+` and `.scale(factor: float) -> Macros`; `Macros.zero() -> Macros`; `profile_targets(kcal: float, fat_pct: float, carb_pct: float, protein_pct: float) -> Macros`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_macros.py`:

```python
import pytest

from yolk.macros import Macros, profile_targets


def test_macros_add():
    a = Macros(kcal=100, protein_g=10, fat_g=5, carb_g=2)
    b = Macros(kcal=50, protein_g=3, fat_g=1, carb_g=8)
    total = a + b
    assert total.kcal == 150
    assert total.protein_g == 13
    assert total.fat_g == 6
    assert total.carb_g == 10


def test_macros_scale():
    per_100g = Macros(kcal=200, protein_g=20, fat_g=10, carb_g=4, fiber_g=2)
    scaled = per_100g.scale(1.5)
    assert scaled.kcal == 300
    assert scaled.protein_g == 30
    assert scaled.fiber_g == 3


def test_macros_sum_of_empty_is_zero():
    assert sum([], Macros.zero()) == Macros.zero()


def test_profile_targets_training_day():
    # 2150 kcal at 34% fat / 28% carb / 38% protein
    t = profile_targets(kcal=2150, fat_pct=34, carb_pct=28, protein_pct=38)
    assert t.kcal == 2150
    assert t.fat_g == pytest.approx(81.22, abs=0.01)
    assert t.carb_g == pytest.approx(150.5, abs=0.01)
    assert t.protein_g == pytest.approx(204.25, abs=0.01)


def test_profile_targets_rest_day():
    # 2115 kcal at 39% fat / 18% carb / 43% protein
    t = profile_targets(kcal=2115, fat_pct=39, carb_pct=18, protein_pct=43)
    assert t.fat_g == pytest.approx(91.65, abs=0.01)
    assert t.carb_g == pytest.approx(95.18, abs=0.01)
    assert t.protein_g == pytest.approx(227.36, abs=0.01)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_macros.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'yolk.macros'`.

- [ ] **Step 3: Write the implementation**

Create `src/yolk/macros.py`:

```python
"""The Macros value type and macro-target arithmetic.

Every food in the database stores macros per 100 g. Macros is the unit of
aggregation: scale it by (grams / 100) to get a portion's contribution.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

KCAL_PER_G_FAT = 9.0
KCAL_PER_G_CARB = 4.0
KCAL_PER_G_PROTEIN = 4.0


@dataclass(frozen=True)
class Macros:
    kcal: float = 0.0
    protein_g: float = 0.0
    fat_g: float = 0.0
    carb_g: float = 0.0
    fiber_g: float = 0.0

    @staticmethod
    def zero() -> "Macros":
        return Macros()

    def __add__(self, other: "Macros") -> "Macros":
        if not isinstance(other, Macros):
            return NotImplemented
        return Macros(
            kcal=self.kcal + other.kcal,
            protein_g=self.protein_g + other.protein_g,
            fat_g=self.fat_g + other.fat_g,
            carb_g=self.carb_g + other.carb_g,
            fiber_g=self.fiber_g + other.fiber_g,
        )

    __radd__ = __add__

    def scale(self, factor: float) -> "Macros":
        return Macros(
            kcal=self.kcal * factor,
            protein_g=self.protein_g * factor,
            fat_g=self.fat_g * factor,
            carb_g=self.carb_g * factor,
            fiber_g=self.fiber_g * factor,
        )

    def replace(self, **kwargs: float) -> "Macros":
        return replace(self, **kwargs)


def profile_targets(
    kcal: float, fat_pct: float, carb_pct: float, protein_pct: float
) -> Macros:
    """Convert a profile's percentage split into gram targets."""
    return Macros(
        kcal=kcal,
        fat_g=kcal * fat_pct / 100.0 / KCAL_PER_G_FAT,
        carb_g=kcal * carb_pct / 100.0 / KCAL_PER_G_CARB,
        protein_g=kcal * protein_pct / 100.0 / KCAL_PER_G_PROTEIN,
    )
```

`Macros.__radd__ = __add__` is what makes `sum(iterable, Macros.zero())` work — without it, `sum` fails when adding `Macros` to the start value from the left.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_macros.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/yolk/macros.py tests/test_macros.py
git commit -m "feat: add Macros value type and profile target computation"
```

---

### Task 3: Unit conversion

**Files:**
- Create: `src/yolk/errors.py`
- Create: `src/yolk/units.py`
- Test: `tests/test_units.py`

**Interfaces:**
- Consumes: `db` fixture from Task 1.
- Produces: `UnknownUnitError`, `MissingYieldError`, `RecipeCycleError` (all subclassing `YolkError`) in `yolk.errors`; `to_grams(conn, food_id: int, qty: float, unit: str) -> float` and `from_grams(conn, food_id: int, grams: float, unit: str) -> float` in `yolk.units`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_units.py`:

```python
import pytest

from yolk.errors import UnknownUnitError
from yolk.units import to_grams


@pytest.fixture
def olive_oil(db):
    cur = db.execute(
        "INSERT INTO foods (kind, name, role, kcal_100g, protein_g_100g, "
        "fat_g_100g, carb_g_100g, source) "
        "VALUES ('item', 'Olive Oil', 'fat', 884, 0, 100, 0, 'usda')"
    )
    food_id = cur.lastrowid
    db.execute(
        "INSERT INTO food_units (food_id, unit, grams, is_default_display) "
        "VALUES (?, 'tbsp', 13.5, 1)",
        (food_id,),
    )
    db.commit()
    return food_id


def test_grams_pass_through(db, olive_oil):
    assert to_grams(db, olive_oil, 25, "g") == 25


def test_kilograms_convert(db, olive_oil):
    assert to_grams(db, olive_oil, 1.5, "kg") == 1500


def test_food_specific_unit(db, olive_oil):
    assert to_grams(db, olive_oil, 2, "tbsp") == pytest.approx(27.0)


def test_fractional_quantity(db, olive_oil):
    assert to_grams(db, olive_oil, 0.25, "tbsp") == pytest.approx(3.375)


def test_unknown_unit_raises_naming_food_and_unit(db, olive_oil):
    with pytest.raises(UnknownUnitError) as exc:
        to_grams(db, olive_oil, 1, "scoop")
    message = str(exc.value)
    assert "Olive Oil" in message
    assert "scoop" in message


def test_unit_is_not_shared_between_foods(db, olive_oil):
    """A tbsp of one food is not a tbsp of another. Conversions are per-food."""
    cur = db.execute(
        "INSERT INTO foods (kind, name, role, kcal_100g, protein_g_100g, "
        "fat_g_100g, carb_g_100g, source) "
        "VALUES ('item', 'Mayo', 'fat', 680, 1, 75, 0, 'label')"
    )
    mayo_id = cur.lastrowid
    db.commit()
    with pytest.raises(UnknownUnitError):
        to_grams(db, mayo_id, 1, "tbsp")


def test_round_trip_grams_to_unit_and_back(db, olive_oil):
    from yolk.units import from_grams

    grams = to_grams(db, olive_oil, 3, "tbsp")
    assert from_grams(db, olive_oil, grams, "tbsp") == pytest.approx(3.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_units.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'yolk.errors'`.

- [ ] **Step 3: Write the errors module**

Create `src/yolk/errors.py`:

```python
"""Exceptions raised by yolk.

Every error here marks a case where a silent default would produce a
plausible but wrong number. Raising is always preferable.
"""


class YolkError(Exception):
    """Base class for all yolk errors."""


class UnknownUnitError(YolkError):
    """No gram conversion is recorded for this food and unit."""


class MissingYieldError(YolkError):
    """A recipe has no cooked_yield_g, so per-100g macros cannot be computed."""


class RecipeCycleError(YolkError):
    """A recipe contains itself, directly or transitively."""
```

- [ ] **Step 4: Write the units module**

Create `src/yolk/units.py`:

```python
"""Resolution of display units to grams.

Conversions are per-food on purpose: a scoop of Karbolyn is not a scoop of
cyclic dextrin, and a tablespoon of oil is not a tablespoon of mayo. Only
mass units are universal.
"""

from __future__ import annotations

import sqlite3

from yolk.errors import UnknownUnitError

MASS_UNITS = {"g": 1.0, "kg": 1000.0, "mg": 0.001, "oz": 28.349523125, "lb": 453.59237}


def _food_name(conn: sqlite3.Connection, food_id: int) -> str:
    row = conn.execute("SELECT name FROM foods WHERE id = ?", (food_id,)).fetchone()
    return row["name"] if row else f"food id {food_id}"


def _grams_per_unit(conn: sqlite3.Connection, food_id: int, unit: str) -> float:
    if unit in MASS_UNITS:
        return MASS_UNITS[unit]
    row = conn.execute(
        "SELECT grams FROM food_units WHERE food_id = ? AND unit = ?",
        (food_id, unit),
    ).fetchone()
    if row is None:
        raise UnknownUnitError(
            f"No gram conversion recorded for unit {unit!r} on "
            f"{_food_name(conn, food_id)!r} (food id {food_id}). "
            f"Add a food_units row before using this unit."
        )
    return row["grams"]


def to_grams(conn: sqlite3.Connection, food_id: int, qty: float, unit: str) -> float:
    """Convert a quantity in some unit to grams for a specific food."""
    return qty * _grams_per_unit(conn, food_id, unit)


def from_grams(conn: sqlite3.Connection, food_id: int, grams: float, unit: str) -> float:
    """Convert grams back into a display unit for a specific food."""
    return grams / _grams_per_unit(conn, food_id, unit)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_units.py -v`
Expected: 7 passed.

- [ ] **Step 6: Commit**

```bash
git add src/yolk/errors.py src/yolk/units.py tests/test_units.py
git commit -m "feat: add per-food unit conversion with loud failures"
```

---

### Task 4: Food creation and retrieval

**Files:**
- Create: `src/yolk/foods.py`
- Test: `tests/test_foods.py`

**Interfaces:**
- Consumes: `Macros` (Task 2), `to_grams` (Task 3).
- Produces: `create_item(conn, *, name, role, macros: Macros, brand="", source="manual", source_ref=None, verified=False, units=None, notes=None) -> int`; `add_unit(conn, food_id, unit, grams, is_default_display=False) -> None`; `macros_per_100g(conn, food_id) -> Macros`; `portion_macros(conn, food_id, qty, unit) -> Macros`.
  `units` is an optional `dict[str, float]` mapping unit name to grams.

- [ ] **Step 1: Write the failing test**

Create `tests/test_foods.py`:

```python
import pytest

from yolk.foods import add_unit, create_item, macros_per_100g, portion_macros
from yolk.macros import Macros


def test_create_item_returns_id_and_round_trips(db):
    food_id = create_item(
        db,
        name="Chicken Breast, raw",
        role="protein",
        macros=Macros(kcal=120, protein_g=22.5, fat_g=2.6, carb_g=0.0),
        source="usda",
        source_ref="171077",
    )
    assert isinstance(food_id, int)
    m = macros_per_100g(db, food_id)
    assert m.kcal == 120
    assert m.protein_g == pytest.approx(22.5)


def test_create_item_with_units(db):
    food_id = create_item(
        db,
        name="Mayonnaise",
        brand="Primal Kitchen",
        role="fat",
        macros=Macros(kcal=680, protein_g=0, fat_g=75, carb_g=0),
        source="label",
        units={"tbsp": 14.0},
    )
    row = db.execute(
        "SELECT grams FROM food_units WHERE food_id = ? AND unit = 'tbsp'", (food_id,)
    ).fetchone()
    assert row["grams"] == 14.0


def test_portion_macros_scales_by_grams(db):
    food_id = create_item(
        db,
        name="Olive Oil",
        role="fat",
        macros=Macros(kcal=884, protein_g=0, fat_g=100, carb_g=0),
        source="usda",
        units={"tbsp": 13.5},
    )
    # 2 tbsp = 27 g = 0.27 x per-100g values
    m = portion_macros(db, food_id, 2, "tbsp")
    assert m.kcal == pytest.approx(238.68, abs=0.01)
    assert m.fat_g == pytest.approx(27.0, abs=0.01)


def test_portion_macros_in_grams_needs_no_unit_row(db):
    food_id = create_item(
        db,
        name="Ground Turkey 93/7",
        role="protein",
        macros=Macros(kcal=170, protein_g=21, fat_g=9.4, carb_g=0),
        source="usda",
    )
    m = portion_macros(db, food_id, 150, "g")
    assert m.kcal == pytest.approx(255.0)
    assert m.protein_g == pytest.approx(31.5)


def test_duplicate_name_and_brand_rejected(db):
    import sqlite3

    create_item(
        db, name="Skyr", brand="Siggi's", role="protein",
        macros=Macros(kcal=63, protein_g=11, fat_g=0.2, carb_g=4), source="label",
    )
    with pytest.raises(sqlite3.IntegrityError):
        create_item(
            db, name="Skyr", brand="Siggi's", role="protein",
            macros=Macros(kcal=99, protein_g=9, fat_g=1, carb_g=5), source="label",
        )


def test_same_name_different_brand_allowed(db):
    a = create_item(
        db, name="Skyr", brand="Siggi's", role="protein",
        macros=Macros(kcal=63, protein_g=11, fat_g=0.2, carb_g=4), source="label",
    )
    b = create_item(
        db, name="Skyr", brand="Icelandic Provisions", role="protein",
        macros=Macros(kcal=70, protein_g=12, fat_g=0.3, carb_g=4), source="label",
    )
    assert a != b


def test_add_unit_sets_default_display(db):
    food_id = create_item(
        db, name="Karbolyn", role="supplement",
        macros=Macros(kcal=380, protein_g=0, fat_g=0, carb_g=95), source="label",
    )
    add_unit(db, food_id, "scoop", 50.0, is_default_display=True)
    row = db.execute(
        "SELECT is_default_display FROM food_units WHERE food_id = ?", (food_id,)
    ).fetchone()
    assert row["is_default_display"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_foods.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'yolk.foods'`.

- [ ] **Step 3: Write the implementation**

Create `src/yolk/foods.py`:

```python
"""Food creation, retrieval, and macro computation.

There is one foods table. kind='item' means purchased; kind='recipe' means
composed from other foods. Both store macros per 100 g, so both can appear
as a component of a recipe or an entry in a plan.
"""

from __future__ import annotations

import sqlite3

from yolk.macros import Macros
from yolk.units import to_grams


def create_item(
    conn: sqlite3.Connection,
    *,
    name: str,
    role: str,
    macros: Macros,
    brand: str = "",
    source: str = "manual",
    source_ref: str | None = None,
    verified: bool = False,
    units: dict[str, float] | None = None,
    notes: str | None = None,
) -> int:
    """Create a purchased food. Macros are per 100 g.

    The food row and its unit conversions are written in one transaction: a
    bad unit must not leave a food behind with no way to measure it.
    """
    try:
        cur = conn.execute(
            "INSERT INTO foods (kind, name, brand, role, kcal_100g, protein_g_100g, "
            "fat_g_100g, carb_g_100g, fiber_g_100g, source, source_ref, verified, "
            "notes) VALUES ('item', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                name, brand, role,
                macros.kcal, macros.protein_g, macros.fat_g,
                macros.carb_g, macros.fiber_g,
                source, source_ref, int(verified), notes,
            ),
        )
        food_id = cur.lastrowid
        for unit, grams in (units or {}).items():
            conn.execute(
                "INSERT INTO food_units (food_id, unit, grams) VALUES (?, ?, ?)",
                (food_id, unit, grams),
            )
    except Exception:
        conn.rollback()
        raise
    conn.commit()
    return food_id


def add_unit(
    conn: sqlite3.Connection,
    food_id: int,
    unit: str,
    grams: float,
    is_default_display: bool = False,
) -> None:
    """Record how many grams one of `unit` weighs for this specific food."""
    conn.execute(
        "INSERT INTO food_units (food_id, unit, grams, is_default_display) "
        "VALUES (?, ?, ?, ?)",
        (food_id, unit, grams, int(is_default_display)),
    )
    conn.commit()


def macros_per_100g(conn: sqlite3.Connection, food_id: int) -> Macros:
    """Return the stored per-100 g macros for a food."""
    row = conn.execute(
        "SELECT kcal_100g, protein_g_100g, fat_g_100g, carb_g_100g, fiber_g_100g "
        "FROM foods WHERE id = ?",
        (food_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"No food with id {food_id}")
    return Macros(
        kcal=row["kcal_100g"] or 0.0,
        protein_g=row["protein_g_100g"] or 0.0,
        fat_g=row["fat_g_100g"] or 0.0,
        carb_g=row["carb_g_100g"] or 0.0,
        fiber_g=row["fiber_g_100g"] or 0.0,
    )


def portion_macros(
    conn: sqlite3.Connection, food_id: int, qty: float, unit: str
) -> Macros:
    """Macros for a given quantity of a food, in any unit it knows."""
    grams = to_grams(conn, food_id, qty, unit)
    return macros_per_100g(conn, food_id).scale(grams / 100.0)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_foods.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/yolk/foods.py tests/test_foods.py
git commit -m "feat: add food creation and portion macro computation"
```

---

### Task 5: Recipe composition with cycle detection

**Files:**
- Modify: `src/yolk/foods.py`
- Test: `tests/test_recipes.py`

**Interfaces:**
- Consumes: everything from Task 4.
- Produces: `create_recipe(conn, *, name, role, components, cooked_yield_g=None, instructions=None, units=None, notes=None) -> int` where `components` is a `list[dict]` with keys `food_id`, `qty`, `unit`, and optional `flex`, `flex_min_g`, `flex_max_g`, `note`; `recompute_recipe(conn, food_id) -> Macros`; `derived_tags(conn, food_id) -> set[str]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_recipes.py`:

```python
import pytest

from yolk.errors import MissingYieldError, RecipeCycleError
from yolk.foods import (
    create_item, create_recipe, derived_tags, macros_per_100g,
    portion_macros, recompute_recipe,
)
from yolk.macros import Macros


@pytest.fixture
def pantry(db):
    """A few items with round numbers, so expected values are checkable by hand."""
    ids = {}
    ids["oil"] = create_item(
        db, name="Olive Oil", role="fat",
        macros=Macros(kcal=884, protein_g=0, fat_g=100, carb_g=0),
        source="usda", units={"tbsp": 13.5},
    )
    ids["garlic"] = create_item(
        db, name="Garlic", role="veg",
        macros=Macros(kcal=149, protein_g=6.4, fat_g=0.5, carb_g=33),
        source="usda", units={"clove": 3.0},
    )
    ids["parsley"] = create_item(
        db, name="Parsley", role="veg",
        macros=Macros(kcal=36, protein_g=3.0, fat_g=0.8, carb_g=6.3),
        source="usda", units={"cup": 60.0},
    )
    ids["steak"] = create_item(
        db, name="Sirloin Steak, raw", role="protein",
        macros=Macros(kcal=201, protein_g=21.6, fat_g=12.7, carb_g=0),
        source="usda",
    )
    return ids


def test_recipe_computes_macros_from_components_and_yield(db, pantry):
    # 100 g oil + 100 g garlic, yielding 200 g of finished sauce.
    # Per 100 g: (884 + 149) / 2 = 516.5 kcal
    recipe_id = create_recipe(
        db, name="Test Sauce", role="sauce", cooked_yield_g=200.0,
        components=[
            {"food_id": pantry["oil"], "qty": 100, "unit": "g"},
            {"food_id": pantry["garlic"], "qty": 100, "unit": "g"},
        ],
    )
    m = macros_per_100g(db, recipe_id)
    assert m.kcal == pytest.approx(516.5, abs=0.01)
    assert m.fat_g == pytest.approx(50.25, abs=0.01)


def test_recipe_yield_smaller_than_input_concentrates_macros(db, pantry):
    """Cooking off water raises macro density. This is why yield weight matters."""
    recipe_id = create_recipe(
        db, name="Reduced Sauce", role="sauce", cooked_yield_g=100.0,
        components=[
            {"food_id": pantry["oil"], "qty": 100, "unit": "g"},
            {"food_id": pantry["garlic"], "qty": 100, "unit": "g"},
        ],
    )
    m = macros_per_100g(db, recipe_id)
    assert m.kcal == pytest.approx(1033.0, abs=0.01)


def test_recipe_without_yield_refuses_to_compute(db, pantry):
    recipe_id = create_recipe(
        db, name="Unyielded", role="sauce",
        components=[{"food_id": pantry["oil"], "qty": 50, "unit": "g"}],
    )
    with pytest.raises(MissingYieldError) as exc:
        recompute_recipe(db, recipe_id)
    assert "Unyielded" in str(exc.value)


def test_recipe_components_accept_display_units(db, pantry):
    # 2 tbsp oil = 27 g; 4 cloves garlic = 12 g; yield 39 g
    recipe_id = create_recipe(
        db, name="Garlic Oil", role="sauce", cooked_yield_g=39.0,
        components=[
            {"food_id": pantry["oil"], "qty": 2, "unit": "tbsp"},
            {"food_id": pantry["garlic"], "qty": 4, "unit": "clove"},
        ],
    )
    m = macros_per_100g(db, recipe_id)
    expected_kcal = (884 * 0.27 + 149 * 0.12) / 39.0 * 100
    assert m.kcal == pytest.approx(expected_kcal, abs=0.01)


def test_recipe_nests_inside_another_recipe(db, pantry):
    sauce_id = create_recipe(
        db, name="Chimichurri", role="sauce", cooked_yield_g=100.0,
        components=[
            {"food_id": pantry["oil"], "qty": 50, "unit": "g"},
            {"food_id": pantry["parsley"], "qty": 50, "unit": "g"},
        ],
    )
    dinner_id = create_recipe(
        db, name="Steak with Chimichurri", role="protein", cooked_yield_g=200.0,
        components=[
            {"food_id": pantry["steak"], "qty": 170, "unit": "g"},
            {"food_id": sauce_id, "qty": 30, "unit": "g"},
        ],
    )
    m = macros_per_100g(db, dinner_id)
    sauce_kcal_100g = (884 * 0.5 + 36 * 0.5)
    expected = (201 * 1.70 + sauce_kcal_100g * 0.30) / 200.0 * 100
    assert m.kcal == pytest.approx(expected, abs=0.01)


def test_direct_self_reference_rejected_by_schema(db, pantry):
    """A recipe containing itself is caught by the CHECK constraint, before
    any Python-level cycle detection is reached."""
    import sqlite3

    recipe_id = create_recipe(
        db, name="Loop", role="sauce", cooked_yield_g=100.0,
        components=[{"food_id": pantry["oil"], "qty": 100, "unit": "g"}],
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO food_components (parent_food_id, child_food_id, qty, unit) "
            "VALUES (?, ?, 1, 'g')",
            (recipe_id, recipe_id),
        )


def test_mutually_recursive_recipes_rejected(db, pantry):
    a_id = create_recipe(
        db, name="A", role="sauce", cooked_yield_g=100.0,
        components=[{"food_id": pantry["oil"], "qty": 100, "unit": "g"}],
    )
    b_id = create_recipe(
        db, name="B", role="sauce", cooked_yield_g=100.0,
        components=[{"food_id": a_id, "qty": 50, "unit": "g"}],
    )
    # Now make A depend on B, closing the loop.
    db.execute(
        "INSERT INTO food_components (parent_food_id, child_food_id, qty, unit) "
        "VALUES (?, ?, 10, 'g')",
        (a_id, b_id),
    )
    db.commit()
    with pytest.raises(RecipeCycleError):
        recompute_recipe(db, a_id)


def test_derived_tags_union_components_including_nested(db, pantry):
    db.execute("INSERT INTO tags (name, kind) VALUES ('allium', 'ingredient_class')")
    db.execute("INSERT INTO tags (name, kind) VALUES ('nightshade', 'ingredient_class')")
    db.commit()
    allium = db.execute("SELECT id FROM tags WHERE name = 'allium'").fetchone()["id"]
    db.execute(
        "INSERT INTO food_tags (food_id, tag_id) VALUES (?, ?)",
        (pantry["garlic"], allium),
    )
    db.commit()

    sauce_id = create_recipe(
        db, name="Allium Sauce", role="sauce", cooked_yield_g=100.0,
        components=[
            {"food_id": pantry["oil"], "qty": 50, "unit": "g"},
            {"food_id": pantry["garlic"], "qty": 50, "unit": "g"},
        ],
    )
    dinner_id = create_recipe(
        db, name="Steak with Allium Sauce", role="protein", cooked_yield_g=200.0,
        components=[
            {"food_id": pantry["steak"], "qty": 170, "unit": "g"},
            {"food_id": sauce_id, "qty": 30, "unit": "g"},
        ],
    )
    # Two levels deep: garlic -> sauce -> dinner
    assert "allium" in derived_tags(db, dinner_id)
    assert "nightshade" not in derived_tags(db, dinner_id)


def test_flex_component_requires_bounds(db, pantry):
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        create_recipe(
            db, name="Bad Flex", role="sauce", cooked_yield_g=100.0,
            components=[
                {"food_id": pantry["oil"], "qty": 50, "unit": "g", "flex": True},
            ],
        )


def test_rejected_component_leaves_no_orphan_recipe(db, pantry):
    """A failed create must roll back the food row, not leave an empty recipe."""
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        create_recipe(
            db, name="Bad Flex 2", role="sauce", cooked_yield_g=100.0,
            components=[
                {"food_id": pantry["oil"], "qty": 50, "unit": "g", "flex": True},
            ],
        )
    row = db.execute(
        "SELECT COUNT(*) AS n FROM foods WHERE name = 'Bad Flex 2'"
    ).fetchone()
    assert row["n"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_recipes.py -v`
Expected: FAIL — `ImportError: cannot import name 'create_recipe' from 'yolk.foods'`.

- [ ] **Step 3: Add recipe functions to `src/yolk/foods.py`**

Append the function definitions below to `src/yolk/foods.py`. **Move the two import
lines to the existing import block at the top of the file** — they are shown here only
so the dependencies are explicit.

```python
from datetime import datetime, timezone

from yolk.errors import MissingYieldError, RecipeCycleError


def create_recipe(
    conn: sqlite3.Connection,
    *,
    name: str,
    role: str,
    components: list[dict],
    cooked_yield_g: float | None = None,
    instructions: str | None = None,
    units: dict[str, float] | None = None,
    notes: str | None = None,
) -> int:
    """Create a composed food. Macros are computed, never supplied.

    Each component dict needs food_id, qty, and unit. Optional keys: flex
    (bool), flex_min_g, flex_max_g, note.

    Recipe, components, and units are one transaction. A rejected component
    must not leave an empty recipe behind.
    """
    try:
        cur = conn.execute(
            "INSERT INTO foods (kind, name, role, cooked_yield_g, instructions, "
            "source, notes) VALUES ('recipe', ?, ?, ?, ?, 'computed', ?)",
            (name, role, cooked_yield_g, instructions, notes),
        )
        food_id = cur.lastrowid
        for c in components:
            conn.execute(
                "INSERT INTO food_components (parent_food_id, child_food_id, qty, "
                "unit, flex, flex_min_g, flex_max_g, note) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    food_id, c["food_id"], c["qty"], c["unit"],
                    int(c.get("flex", False)),
                    c.get("flex_min_g"), c.get("flex_max_g"), c.get("note"),
                ),
            )
        for unit, grams in (units or {}).items():
            conn.execute(
                "INSERT INTO food_units (food_id, unit, grams) VALUES (?, ?, ?)",
                (food_id, unit, grams),
            )
    except Exception:
        conn.rollback()
        raise
    conn.commit()
    if cooked_yield_g is not None:
        recompute_recipe(conn, food_id)
    return food_id


def _components(conn: sqlite3.Connection, food_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT child_food_id, qty, unit FROM food_components "
        "WHERE parent_food_id = ? ORDER BY id",
        (food_id,),
    ).fetchall()


def _macros_resolved(
    conn: sqlite3.Connection, food_id: int, seen: frozenset[int]
) -> Macros:
    """Per-100 g macros, always recursing into nested recipes rather than
    trusting their cached value, so a stale cache cannot propagate.

    `seen` is the ancestor chain, used to detect cycles. Indirect cycles are
    only detectable here: the schema's CHECK catches direct self-reference,
    but a two-recipe loop is closed by an insert that is individually valid.
    """
    if food_id in seen:
        name = conn.execute(
            "SELECT name FROM foods WHERE id = ?", (food_id,)
        ).fetchone()["name"]
        raise RecipeCycleError(
            f"Recipe {name!r} (id {food_id}) contains itself, directly or "
            f"through a nested recipe."
        )

    row = conn.execute(
        "SELECT kind, name, kcal_100g, cooked_yield_g FROM foods WHERE id = ?",
        (food_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"No food with id {food_id}")

    if row["kind"] == "item":
        return macros_per_100g(conn, food_id)

    if row["cooked_yield_g"] is None:
        raise MissingYieldError(
            f"Recipe {row['name']!r} (id {food_id}) has no cooked_yield_g, so its "
            f"per-100 g macros cannot be computed. Weigh the finished dish and "
            f"set cooked_yield_g."
        )

    chain = seen | {food_id}
    total = Macros.zero()
    for c in _components(conn, food_id):
        grams = to_grams(conn, c["child_food_id"], c["qty"], c["unit"])
        child = _macros_resolved(conn, c["child_food_id"], chain)
        total = total + child.scale(grams / 100.0)

    return total.scale(100.0 / row["cooked_yield_g"])


def recompute_recipe(conn: sqlite3.Connection, food_id: int) -> Macros:
    """Recompute and cache a recipe's per-100 g macros."""
    macros = _macros_resolved(conn, food_id, frozenset())
    conn.execute(
        "UPDATE foods SET kcal_100g = ?, protein_g_100g = ?, fat_g_100g = ?, "
        "carb_g_100g = ?, fiber_g_100g = ?, computed_at = ? WHERE id = ?",
        (
            macros.kcal, macros.protein_g, macros.fat_g, macros.carb_g,
            macros.fiber_g, datetime.now(timezone.utc).isoformat(), food_id,
        ),
    )
    conn.commit()
    return macros


def derived_tags(conn: sqlite3.Connection, food_id: int) -> set[str]:
    """Tags on this food, unioned with those of every nested component.

    Only purchased items are tagged by hand. A recipe's tags are derived, so
    a sensitivity buried two levels deep still surfaces.
    """
    return _derived_tags(conn, food_id, frozenset())


def _derived_tags(
    conn: sqlite3.Connection, food_id: int, seen: frozenset[int]
) -> set[str]:
    if food_id in seen:
        raise RecipeCycleError(f"Cycle detected while deriving tags for id {food_id}")
    rows = conn.execute(
        "SELECT t.name FROM food_tags ft JOIN tags t ON t.id = ft.tag_id "
        "WHERE ft.food_id = ?",
        (food_id,),
    ).fetchall()
    tags = {r["name"] for r in rows}
    chain = seen | {food_id}
    for c in _components(conn, food_id):
        tags |= _derived_tags(conn, c["child_food_id"], chain)
    return tags
```

The cycle check lives in `_macros_resolved` rather than at insert time because a
cycle can only be closed by a later insert — as `test_mutually_recursive_recipes_rejected`
shows, neither insert is individually invalid.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_recipes.py -v`
Expected: 10 passed.

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest -v`
Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add src/yolk/foods.py tests/test_recipes.py
git commit -m "feat: add nested recipe composition, cycle detection, derived tags"
```

---

### Task 6: USDA FoodData Central client with on-disk cache

**Files:**
- Create: `src/yolk/sources/__init__.py`
- Create: `src/yolk/sources/cache.py`
- Create: `src/yolk/sources/usda.py`
- Modify: `.gitignore`
- Test: `tests/test_usda.py`

**Interfaces:**
- Consumes: `Macros` (Task 2), `create_item` (Task 4).
- Produces: `search_foods(query: str, *, page_size: int = 10, data_types: tuple[str, ...] = ("Foundation", "SR Legacy")) -> list[dict]`; `get_food(fdc_id: int) -> dict`; `parse_macros(payload: dict) -> Macros`; `import_food(conn, fdc_id: int, *, role: str, units: dict[str, float] | None = None) -> int`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_usda.py`. Network calls are not exercised in tests — `parse_macros`
is tested against a recorded payload, and `import_food` against a monkeypatched fetch.

```python
import pytest

from yolk.macros import Macros
from yolk.sources import usda

# Shape of a FoodData Central /food/{id} response, trimmed to what we read.
SAMPLE_PAYLOAD = {
    "fdcId": 171077,
    "description": "Chicken, broilers or fryers, breast, meat only, raw",
    "dataType": "SR Legacy",
    "foodNutrients": [
        {"nutrient": {"id": 1008, "name": "Energy", "unitName": "KCAL"}, "amount": 120.0},
        {"nutrient": {"id": 1003, "name": "Protein", "unitName": "G"}, "amount": 22.5},
        {"nutrient": {"id": 1004, "name": "Total lipid (fat)", "unitName": "G"}, "amount": 2.62},
        {"nutrient": {"id": 1005, "name": "Carbohydrate", "unitName": "G"}, "amount": 0.0},
        {"nutrient": {"id": 1079, "name": "Fiber", "unitName": "G"}, "amount": 0.0},
        {"nutrient": {"id": 1093, "name": "Sodium", "unitName": "MG"}, "amount": 45.0},
    ],
}


def test_parse_macros_maps_nutrient_ids():
    m = usda.parse_macros(SAMPLE_PAYLOAD)
    assert m.kcal == pytest.approx(120.0)
    assert m.protein_g == pytest.approx(22.5)
    assert m.fat_g == pytest.approx(2.62)
    assert m.carb_g == pytest.approx(0.0)
    assert m.fiber_g == pytest.approx(0.0)


def test_parse_macros_ignores_unmapped_nutrients():
    """Sodium is present in the payload and must not land anywhere."""
    m = usda.parse_macros(SAMPLE_PAYLOAD)
    assert m == Macros(kcal=120.0, protein_g=22.5, fat_g=2.62, carb_g=0.0, fiber_g=0.0)


def test_parse_macros_missing_energy_raises():
    payload = {"fdcId": 1, "description": "Mystery", "foodNutrients": []}
    with pytest.raises(ValueError) as exc:
        usda.parse_macros(payload)
    assert "energy" in str(exc.value).lower()


def test_import_food_creates_item_with_provenance(db, monkeypatch):
    monkeypatch.setattr(usda, "get_food", lambda fdc_id: SAMPLE_PAYLOAD)
    food_id = usda.import_food(db, 171077, role="protein")
    row = db.execute(
        "SELECT name, source, source_ref, verified, kcal_100g FROM foods WHERE id = ?",
        (food_id,),
    ).fetchone()
    assert row["source"] == "usda"
    assert row["source_ref"] == "171077"
    assert row["verified"] == 0
    assert row["kcal_100g"] == pytest.approx(120.0)


def test_import_food_attaches_units(db, monkeypatch):
    monkeypatch.setattr(usda, "get_food", lambda fdc_id: SAMPLE_PAYLOAD)
    food_id = usda.import_food(db, 171077, role="protein", units={"breast": 174.0})
    row = db.execute(
        "SELECT grams FROM food_units WHERE food_id = ? AND unit = 'breast'", (food_id,)
    ).fetchone()
    assert row["grams"] == 174.0


def test_failed_fetch_writes_nothing(db, monkeypatch):
    def boom(fdc_id):
        raise RuntimeError("network down")

    monkeypatch.setattr(usda, "get_food", boom)
    with pytest.raises(RuntimeError):
        usda.import_food(db, 171077, role="protein")
    count = db.execute("SELECT COUNT(*) AS n FROM foods").fetchone()["n"]
    assert count == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_usda.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'yolk.sources'`.

- [ ] **Step 3: Write the cache module**

Create `src/yolk/sources/__init__.py` (empty) and `src/yolk/sources/cache.py`:

```python
"""On-disk cache of raw API responses.

Imports stay reproducible and a network blip never blocks work. Responses
are stored verbatim so a parser change can be re-run against old payloads.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

CACHE_DIR = Path(".cache")


def cached_json(namespace: str, key: str, fetch: Callable[[], Any]) -> Any:
    """Return cached JSON for `key`, calling `fetch` only on a miss."""
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
    path = CACHE_DIR / namespace / f"{digest}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    payload = fetch()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload
```

Append to `.gitignore`:

```
# Cached API responses
.cache/
```

- [ ] **Step 4: Write the USDA client**

Create `src/yolk/sources/usda.py`:

```python
"""USDA FoodData Central client.

Foundation and SR Legacy entries report nutrients per 100 g, which is the
unit yolk stores natively. Branded entries report per serving and are not
handled here.
"""

from __future__ import annotations

import os
import sqlite3

import httpx
from dotenv import load_dotenv

from yolk.foods import create_item
from yolk.macros import Macros
from yolk.sources.cache import cached_json

BASE_URL = "https://api.nal.usda.gov/fdc/v1"

# FoodData Central nutrient IDs. Anything not listed here is ignored.
NUTRIENT_KCAL = 1008
NUTRIENT_PROTEIN = 1003
NUTRIENT_FAT = 1004
NUTRIENT_CARB = 1005
NUTRIENT_FIBER = 1079


def _api_key() -> str:
    load_dotenv()
    key = os.environ.get("USDA_API_KEY")
    if not key:
        raise RuntimeError(
            "USDA_API_KEY is not set. Add it to .env; get a free key at "
            "https://api.data.gov/signup"
        )
    return key


def search_foods(
    query: str,
    *,
    page_size: int = 10,
    data_types: tuple[str, ...] = ("Foundation", "SR Legacy"),
) -> list[dict]:
    """Search FoodData Central. Returns the raw `foods` list."""
    key = f"search:{query}:{page_size}:{','.join(data_types)}"

    def fetch():
        response = httpx.get(
            f"{BASE_URL}/foods/search",
            params={
                "query": query,
                "pageSize": page_size,
                "dataType": ",".join(data_types),
                "api_key": _api_key(),
            },
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json()

    return cached_json("usda", key, fetch).get("foods", [])


def get_food(fdc_id: int) -> dict:
    """Fetch one food by FDC id."""

    def fetch():
        response = httpx.get(
            f"{BASE_URL}/food/{fdc_id}",
            params={"api_key": _api_key()},
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json()

    return cached_json("usda", f"food:{fdc_id}", fetch)


def parse_macros(payload: dict) -> Macros:
    """Extract per-100 g macros from a FoodData Central food payload."""
    by_id: dict[int, float] = {}
    for entry in payload.get("foodNutrients", []):
        nutrient = entry.get("nutrient") or {}
        nutrient_id = nutrient.get("id")
        if nutrient_id is not None and "amount" in entry:
            by_id[nutrient_id] = entry["amount"]

    if NUTRIENT_KCAL not in by_id:
        raise ValueError(
            f"No energy (nutrient {NUTRIENT_KCAL}) in FDC payload for "
            f"{payload.get('description', 'unknown food')!r}. Refusing to import a "
            f"food without calories."
        )

    return Macros(
        kcal=by_id[NUTRIENT_KCAL],
        protein_g=by_id.get(NUTRIENT_PROTEIN, 0.0),
        fat_g=by_id.get(NUTRIENT_FAT, 0.0),
        carb_g=by_id.get(NUTRIENT_CARB, 0.0),
        fiber_g=by_id.get(NUTRIENT_FIBER, 0.0),
    )


def import_food(
    conn: sqlite3.Connection,
    fdc_id: int,
    *,
    role: str,
    units: dict[str, float] | None = None,
) -> int:
    """Fetch a food from FDC and insert it as an item.

    Fetch and parse both happen before any write, so a failure leaves no
    partial row behind.
    """
    payload = get_food(fdc_id)
    macros = parse_macros(payload)
    return create_item(
        conn,
        name=payload["description"],
        role=role,
        macros=macros,
        source="usda",
        source_ref=str(fdc_id),
        verified=False,
        units=units,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_usda.py -v`
Expected: 6 passed.

- [ ] **Step 6: Verify against the live API once, by hand**

Run:

```bash
uv run python -c "from yolk.sources.usda import search_foods; r = search_foods('chicken breast raw', page_size=3); print([(f['fdcId'], f['description']) for f in r])"
```

Expected: three results printed, and a new JSON file under `.cache/usda/`. If this
raises on `USDA_API_KEY`, confirm `.env` exists at the repo root.

- [ ] **Step 7: Commit**

```bash
git add src/yolk/sources tests/test_usda.py .gitignore
git commit -m "feat: add USDA FoodData Central client with response cache"
```

---

### Task 7: Person, profiles, and slot templates

**Files:**
- Create: `src/yolk/people.py`
- Test: `tests/test_people.py`

**Interfaces:**
- Consumes: `Macros`, `profile_targets` (Task 2).
- Produces: `create_person(conn, name) -> int`; `create_profile(conn, person_id, *, name, effective_on, kcal, fat_pct, carb_pct, protein_pct, kcal_tol_pct=1.0, protein_tol_g=8.0, macro_pct_tol=3.0) -> int`; `active_profile(conn, person_id, name, on_date: str) -> sqlite3.Row`; `targets_for_profile(conn, profile_id) -> Macros`; `create_slot(conn, person_id, profile_id, *, slot_no, name, time_of_day, roles=(), portable=False, fixed=False, notes=None) -> int`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_people.py`:

```python
import pytest

from yolk.people import (
    active_profile, create_person, create_profile, create_slot, targets_for_profile,
)


def test_profile_targets_derive_grams(db):
    pid = create_person(db, "Jen")
    profile_id = create_profile(
        db, pid, name="training", effective_on="2026-07-14",
        kcal=2150, fat_pct=34, carb_pct=28, protein_pct=38,
    )
    t = targets_for_profile(db, profile_id)
    assert t.kcal == 2150
    assert t.protein_g == pytest.approx(204.25, abs=0.01)


def test_active_profile_picks_latest_on_or_before_date(db):
    pid = create_person(db, "Jen")
    create_profile(
        db, pid, name="training", effective_on="2026-01-01",
        kcal=2000, fat_pct=34, carb_pct=28, protein_pct=38,
    )
    create_profile(
        db, pid, name="training", effective_on="2026-07-14",
        kcal=2150, fat_pct=34, carb_pct=28, protein_pct=38,
    )
    row = active_profile(db, pid, "training", "2026-08-09")
    assert row["kcal"] == 2150


def test_active_profile_ignores_future_rows(db):
    pid = create_person(db, "Jen")
    create_profile(
        db, pid, name="training", effective_on="2026-01-01",
        kcal=2000, fat_pct=34, carb_pct=28, protein_pct=38,
    )
    create_profile(
        db, pid, name="training", effective_on="2026-12-01",
        kcal=2300, fat_pct=34, carb_pct=28, protein_pct=38,
    )
    row = active_profile(db, pid, "training", "2026-08-09")
    assert row["kcal"] == 2000


def test_active_profile_missing_raises(db):
    pid = create_person(db, "Jen")
    with pytest.raises(LookupError):
        active_profile(db, pid, "training", "2026-08-09")


def test_tolerances_default_to_spec_values(db):
    pid = create_person(db, "Jen")
    profile_id = create_profile(
        db, pid, name="rest", effective_on="2026-07-14",
        kcal=2115, fat_pct=39, carb_pct=18, protein_pct=43,
    )
    row = db.execute(
        "SELECT kcal_tol_pct, protein_tol_g, macro_pct_tol FROM macro_profiles "
        "WHERE id = ?", (profile_id,)
    ).fetchone()
    assert row["kcal_tol_pct"] == 1.0
    assert row["protein_tol_g"] == 2.0
    assert row["macro_pct_tol"] == 3.0


def test_slot_with_roles(db):
    pid = create_person(db, "Jen")
    profile_id = create_profile(
        db, pid, name="training", effective_on="2026-07-14",
        kcal=2150, fat_pct=34, carb_pct=28, protein_pct=38,
    )
    slot_id = create_slot(
        db, pid, profile_id, slot_no=6, name="Dinner", time_of_day="18:00",
        roles=("protein", "veg", "sauce"),
    )
    rows = db.execute(
        "SELECT role FROM slot_template_roles WHERE slot_template_id = ? ORDER BY role",
        (slot_id,),
    ).fetchall()
    assert [r["role"] for r in rows] == ["protein", "sauce", "veg"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_people.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'yolk.people'`.

- [ ] **Step 3: Write the implementation**

Create `src/yolk/people.py`:

```python
"""People, dated macro profiles, and meal slot templates.

Profiles are dated rows rather than constants, so recalculating targets as
body composition changes is a new row and old plans stay interpretable.
"""

from __future__ import annotations

import sqlite3

from yolk.macros import Macros, profile_targets


def create_person(conn: sqlite3.Connection, name: str) -> int:
    cur = conn.execute("INSERT INTO people (name) VALUES (?)", (name,))
    conn.commit()
    return cur.lastrowid


def create_profile(
    conn: sqlite3.Connection,
    person_id: int,
    *,
    name: str,
    effective_on: str,
    kcal: float,
    fat_pct: float,
    carb_pct: float,
    protein_pct: float,
    kcal_tol_pct: float = 1.0,
    protein_tol_g: float = 2.0,
    macro_pct_tol: float = 3.0,
) -> int:
    cur = conn.execute(
        "INSERT INTO macro_profiles (person_id, name, effective_on, kcal, fat_pct, "
        "carb_pct, protein_pct, kcal_tol_pct, protein_tol_g, macro_pct_tol) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            person_id, name, effective_on, kcal, fat_pct, carb_pct, protein_pct,
            kcal_tol_pct, protein_tol_g, macro_pct_tol,
        ),
    )
    conn.commit()
    return cur.lastrowid


def active_profile(
    conn: sqlite3.Connection, person_id: int, name: str, on_date: str
) -> sqlite3.Row:
    """The profile in force on `on_date` — the latest row not in the future."""
    row = conn.execute(
        "SELECT * FROM macro_profiles WHERE person_id = ? AND name = ? "
        "AND effective_on <= ? ORDER BY effective_on DESC LIMIT 1",
        (person_id, name, on_date),
    ).fetchone()
    if row is None:
        raise LookupError(
            f"No {name!r} profile for person {person_id} effective on or before "
            f"{on_date}."
        )
    return row


def targets_for_profile(conn: sqlite3.Connection, profile_id: int) -> Macros:
    row = conn.execute(
        "SELECT kcal, fat_pct, carb_pct, protein_pct FROM macro_profiles WHERE id = ?",
        (profile_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"No macro profile with id {profile_id}")
    return profile_targets(
        kcal=row["kcal"],
        fat_pct=row["fat_pct"],
        carb_pct=row["carb_pct"],
        protein_pct=row["protein_pct"],
    )


def create_slot(
    conn: sqlite3.Connection,
    person_id: int,
    profile_id: int,
    *,
    slot_no: int,
    name: str,
    time_of_day: str,
    roles: tuple[str, ...] = (),
    portable: bool = False,
    fixed: bool = False,
    notes: str | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO slot_templates (person_id, profile_id, slot_no, name, "
        "time_of_day, portable, fixed, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (person_id, profile_id, slot_no, name, time_of_day,
         int(portable), int(fixed), notes),
    )
    slot_id = cur.lastrowid
    for role in roles:
        conn.execute(
            "INSERT INTO slot_template_roles (slot_template_id, role) VALUES (?, ?)",
            (slot_id, role),
        )
    conn.commit()
    return slot_id
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_people.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/yolk/people.py tests/test_people.py
git commit -m "feat: add people, dated macro profiles, and slot templates"
```

---

### Task 8: Day plans and evaluation

**Files:**
- Create: `src/yolk/planning/__init__.py`
- Create: `src/yolk/planning/evaluate.py`
- Test: `tests/test_evaluate.py`

**Interfaces:**
- Consumes: `portion_macros` (Task 4), `targets_for_profile` (Task 7).
- Produces: `create_day_plan(conn, person_id, profile_id, *, name, notes=None, parent_plan_id=None) -> int`; `add_entry(conn, day_plan_id, *, slot_no, food_id, qty, unit, flex=False, flex_min_g=None, flex_max_g=None) -> int`; dataclasses `SlotEvaluation` (fields `slot_no: int`, `totals: Macros`, `entries: list[EntryEvaluation]`), `EntryEvaluation` (fields `entry_id: int`, `food_id: int`, `food_name: str`, `qty: float`, `unit: str`, `grams: float`, `macros: Macros`), `DayEvaluation` (fields `day_plan_id: int`, `plan_name: str`, `totals: Macros`, `target: Macros`, `deltas: Macros`, `within_tolerance: dict[str, bool]`, `slots: list[SlotEvaluation]`, and property `ok: bool`); `evaluate(conn, day_plan_id) -> DayEvaluation`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_evaluate.py`:

```python
import pytest

from yolk.foods import create_item
from yolk.macros import Macros
from yolk.people import create_person, create_profile
from yolk.planning.evaluate import add_entry, create_day_plan, evaluate


@pytest.fixture
def simple_plan(db):
    """A one-slot plan whose totals are trivially checkable by hand."""
    pid = create_person(db, "Jen")
    profile_id = create_profile(
        db, pid, name="training", effective_on="2026-07-14",
        kcal=2150, fat_pct=34, carb_pct=28, protein_pct=38,
    )
    chicken = create_item(
        db, name="Chicken Breast", role="protein",
        macros=Macros(kcal=120, protein_g=22.5, fat_g=2.6, carb_g=0), source="usda",
    )
    rice = create_item(
        db, name="White Rice, cooked", role="carb",
        macros=Macros(kcal=130, protein_g=2.7, fat_g=0.3, carb_g=28), source="usda",
    )
    plan_id = create_day_plan(db, pid, profile_id, name="Test Plan")
    add_entry(db, plan_id, slot_no=4, food_id=chicken, qty=200, unit="g")
    add_entry(db, plan_id, slot_no=4, food_id=rice, qty=150, unit="g")
    return plan_id


def test_evaluate_totals(db, simple_plan):
    result = evaluate(db, simple_plan)
    # 200 g chicken = 240 kcal, 45 g protein; 150 g rice = 195 kcal, 4.05 g protein
    assert result.totals.kcal == pytest.approx(435.0, abs=0.01)
    assert result.totals.protein_g == pytest.approx(49.05, abs=0.01)
    assert result.totals.carb_g == pytest.approx(42.0, abs=0.01)


def test_evaluate_groups_by_slot(db, simple_plan):
    result = evaluate(db, simple_plan)
    assert len(result.slots) == 1
    assert result.slots[0].slot_no == 4
    assert len(result.slots[0].entries) == 2
    assert result.slots[0].totals.kcal == pytest.approx(435.0, abs=0.01)


def test_evaluate_reports_deltas_against_target(db, simple_plan):
    result = evaluate(db, simple_plan)
    assert result.target.kcal == 2150
    # deltas are actual minus target, so a short day is negative
    assert result.deltas.kcal == pytest.approx(435.0 - 2150.0, abs=0.01)


def test_underfed_day_fails_tolerance(db, simple_plan):
    result = evaluate(db, simple_plan)
    assert result.within_tolerance["kcal"] is False
    assert result.within_tolerance["protein_g"] is False
    assert result.ok is False


def test_on_target_day_passes_tolerance(db):
    pid = create_person(db, "Jen")
    profile_id = create_profile(
        db, pid, name="test", effective_on="2026-01-01",
        kcal=1000, fat_pct=36, carb_pct=24, protein_pct=40,
    )
    # Target: 1000 kcal, 40 g fat, 60 g carb, 100 g protein.
    # One synthetic food at exactly those macros per 100 g, eaten 100 g.
    food = create_item(
        db, name="Exactly Target", role="protein",
        macros=Macros(kcal=1000, protein_g=100, fat_g=40, carb_g=60), source="manual",
    )
    plan_id = create_day_plan(db, pid, profile_id, name="Perfect")
    add_entry(db, plan_id, slot_no=1, food_id=food, qty=100, unit="g")

    result = evaluate(db, plan_id)
    assert result.within_tolerance == {
        "kcal": True, "protein_g": True, "fat_pct": True, "carb_pct": True,
    }
    assert result.ok is True


def test_fat_and_carb_judged_as_percentages_not_grams(db):
    """Fat and carb are banded on percent of calories, per the spec."""
    pid = create_person(db, "Jen")
    profile_id = create_profile(
        db, pid, name="test", effective_on="2026-01-01",
        kcal=1000, fat_pct=36, carb_pct=24, protein_pct=40,
    )
    # 1000 kcal, 100 g protein, but fat/carb swapped away from target:
    # 30 g fat (27%) and 87 g carb (34.8%) -> both outside the 3-point band.
    food = create_item(
        db, name="Skewed", role="protein",
        macros=Macros(kcal=1000, protein_g=100, fat_g=30, carb_g=87), source="manual",
    )
    plan_id = create_day_plan(db, pid, profile_id, name="Skewed Day")
    add_entry(db, plan_id, slot_no=1, food_id=food, qty=100, unit="g")

    result = evaluate(db, plan_id)
    assert result.within_tolerance["kcal"] is True
    assert result.within_tolerance["protein_g"] is True
    assert result.within_tolerance["fat_pct"] is False
    assert result.within_tolerance["carb_pct"] is False


def test_evaluate_does_not_mutate(db, simple_plan):
    before = db.execute(
        "SELECT id, qty, unit FROM day_plan_entries WHERE day_plan_id = ? "
        "ORDER BY id", (simple_plan,)
    ).fetchall()
    evaluate(db, simple_plan)
    after = db.execute(
        "SELECT id, qty, unit FROM day_plan_entries WHERE day_plan_id = ? "
        "ORDER BY id", (simple_plan,)
    ).fetchall()
    assert [tuple(r) for r in before] == [tuple(r) for r in after]


def test_evaluate_uses_display_units(db):
    pid = create_person(db, "Jen")
    profile_id = create_profile(
        db, pid, name="test", effective_on="2026-01-01",
        kcal=2000, fat_pct=34, carb_pct=28, protein_pct=38,
    )
    oil = create_item(
        db, name="Olive Oil", role="fat",
        macros=Macros(kcal=884, protein_g=0, fat_g=100, carb_g=0),
        source="usda", units={"tbsp": 13.5},
    )
    plan_id = create_day_plan(db, pid, profile_id, name="Oil Only")
    add_entry(db, plan_id, slot_no=6, food_id=oil, qty=1.5, unit="tbsp")

    result = evaluate(db, plan_id)
    # 1.5 tbsp = 20.25 g -> 179.01 kcal
    assert result.totals.kcal == pytest.approx(179.01, abs=0.01)
    assert result.slots[0].entries[0].grams == pytest.approx(20.25, abs=0.001)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_evaluate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'yolk.planning'`.

- [ ] **Step 3: Write the implementation**

Create `src/yolk/planning/__init__.py` (empty) and `src/yolk/planning/evaluate.py`:

```python
"""Day plan construction and evaluation.

evaluate() is pure: it reads, computes, and returns. Nothing in this module
writes to a plan. Every other planning operation is built on top of it, so
keeping it side-effect free is what makes the rest testable.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone

from yolk.foods import portion_macros
from yolk.macros import KCAL_PER_G_CARB, KCAL_PER_G_FAT, Macros
from yolk.people import targets_for_profile
from yolk.units import to_grams


def create_day_plan(
    conn: sqlite3.Connection,
    person_id: int,
    profile_id: int,
    *,
    name: str,
    notes: str | None = None,
    parent_plan_id: int | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO day_plans (person_id, profile_id, name, parent_plan_id, "
        "created_at, notes) VALUES (?, ?, ?, ?, ?, ?)",
        (
            person_id, profile_id, name, parent_plan_id,
            datetime.now(timezone.utc).isoformat(), notes,
        ),
    )
    conn.commit()
    return cur.lastrowid


def add_entry(
    conn: sqlite3.Connection,
    day_plan_id: int,
    *,
    slot_no: int,
    food_id: int,
    qty: float,
    unit: str,
    flex: bool = False,
    flex_min_g: float | None = None,
    flex_max_g: float | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO day_plan_entries (day_plan_id, slot_no, food_id, qty, unit, "
        "flex, flex_min_g, flex_max_g) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (day_plan_id, slot_no, food_id, qty, unit,
         int(flex), flex_min_g, flex_max_g),
    )
    conn.commit()
    return cur.lastrowid


@dataclass(frozen=True)
class EntryEvaluation:
    entry_id: int
    food_id: int
    food_name: str
    qty: float
    unit: str
    grams: float
    macros: Macros


@dataclass(frozen=True)
class SlotEvaluation:
    slot_no: int
    totals: Macros
    entries: list[EntryEvaluation] = field(default_factory=list)


@dataclass(frozen=True)
class DayEvaluation:
    day_plan_id: int
    plan_name: str
    totals: Macros
    target: Macros
    deltas: Macros
    within_tolerance: dict[str, bool]
    slots: list[SlotEvaluation] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(self.within_tolerance.values())


def _pct_of_kcal(grams: float, kcal_per_g: float, total_kcal: float) -> float:
    if total_kcal == 0:
        return 0.0
    return grams * kcal_per_g / total_kcal * 100.0


def evaluate(conn: sqlite3.Connection, day_plan_id: int) -> DayEvaluation:
    """Aggregate a day plan and compare it against its profile's targets."""
    plan = conn.execute(
        "SELECT name, profile_id FROM day_plans WHERE id = ?", (day_plan_id,)
    ).fetchone()
    if plan is None:
        raise LookupError(f"No day plan with id {day_plan_id}")

    rows = conn.execute(
        "SELECT e.id, e.slot_no, e.food_id, e.qty, e.unit, f.name AS food_name "
        "FROM day_plan_entries e JOIN foods f ON f.id = e.food_id "
        "WHERE e.day_plan_id = ? ORDER BY e.slot_no, e.sort_order, e.id",
        (day_plan_id,),
    ).fetchall()

    by_slot: dict[int, list[EntryEvaluation]] = {}
    for row in rows:
        grams = to_grams(conn, row["food_id"], row["qty"], row["unit"])
        macros = portion_macros(conn, row["food_id"], row["qty"], row["unit"])
        by_slot.setdefault(row["slot_no"], []).append(
            EntryEvaluation(
                entry_id=row["id"],
                food_id=row["food_id"],
                food_name=row["food_name"],
                qty=row["qty"],
                unit=row["unit"],
                grams=grams,
                macros=macros,
            )
        )

    slots = [
        SlotEvaluation(
            slot_no=slot_no,
            totals=sum((e.macros for e in entries), Macros.zero()),
            entries=entries,
        )
        for slot_no, entries in sorted(by_slot.items())
    ]
    totals = sum((s.totals for s in slots), Macros.zero())

    target = targets_for_profile(conn, plan["profile_id"])
    profile = conn.execute(
        "SELECT fat_pct, carb_pct, kcal_tol_pct, protein_tol_g, macro_pct_tol "
        "FROM macro_profiles WHERE id = ?",
        (plan["profile_id"],),
    ).fetchone()

    deltas = Macros(
        kcal=totals.kcal - target.kcal,
        protein_g=totals.protein_g - target.protein_g,
        fat_g=totals.fat_g - target.fat_g,
        carb_g=totals.carb_g - target.carb_g,
        fiber_g=totals.fiber_g - target.fiber_g,
    )

    actual_fat_pct = _pct_of_kcal(totals.fat_g, KCAL_PER_G_FAT, totals.kcal)
    actual_carb_pct = _pct_of_kcal(totals.carb_g, KCAL_PER_G_CARB, totals.kcal)

    within_tolerance = {
        "kcal": abs(deltas.kcal) <= target.kcal * profile["kcal_tol_pct"] / 100.0,
        "protein_g": abs(deltas.protein_g) <= profile["protein_tol_g"],
        "fat_pct": abs(actual_fat_pct - profile["fat_pct"]) <= profile["macro_pct_tol"],
        "carb_pct": abs(actual_carb_pct - profile["carb_pct"])
        <= profile["macro_pct_tol"],
    }

    return DayEvaluation(
        day_plan_id=day_plan_id,
        plan_name=plan["name"],
        totals=totals,
        target=target,
        deltas=deltas,
        within_tolerance=within_tolerance,
        slots=slots,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_evaluate.py -v`
Expected: 8 passed.

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest -v`
Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add src/yolk/planning tests/test_evaluate.py
git commit -m "feat: add day plans and pure evaluate() against profile targets"
```

---

### Task 9: Extract Keto Plan A from the source PDF

**Files:**
- Create: `scripts/extract_plan_pdf.py`
- Create: `tests/fixtures/keto_plan_a.json`

**Interfaces:**
- Consumes: nothing from earlier tasks — this is a data extraction step.
- Produces: `tests/fixtures/keto_plan_a.json`, consumed by Task 10.

**This task produces data, not code paths.** The exact ingredient names, quantities,
units, and macro totals are in the PDF and are not reproduced here — extract them,
then verify them by eye against the source before moving on.

- [ ] **Step 1: Write the extraction script**

Create `scripts/extract_plan_pdf.py`:

```python
"""Dump the text of a coach-authored meal plan PDF for manual transcription.

Usage:
    uv run --with pdfplumber python scripts/extract_plan_pdf.py examples/<file>.pdf
"""

import sys
from pathlib import Path

import pdfplumber


def main(path: str) -> None:
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            print(f"\n{'=' * 70}\nPAGE {i}\n{'=' * 70}")
            print(page.extract_text() or "(no text layer)")
            for j, table in enumerate(page.extract_tables(), start=1):
                print(f"\n--- page {i} table {j} ---")
                for row in table:
                    print(row)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: extract_plan_pdf.py <path-to-pdf>")
    main(str(Path(sys.argv[1])))
```

- [ ] **Step 2: Run it against Keto Plan A**

Run:

```bash
uv run --with pdfplumber python scripts/extract_plan_pdf.py "examples/Jen_Crawford_Keto_Meal_Plan_A_7_14_26_xlsx___Nutrition_pdf.pdf"
```

Expected: the plan's text, including per-meal ingredient rows and the macro
summary. If the output is empty, the PDF has no text layer and needs OCR — stop
and report that, do not guess values.

- [ ] **Step 3: Transcribe into a fixture**

Create `tests/fixtures/keto_plan_a.json` in this shape, filling every value from
the PDF output:

```json
{
  "plan_name": "Keto Meal Plan A",
  "profile": {
    "name": "training",
    "effective_on": "2026-07-14",
    "kcal": 2150,
    "fat_pct": 34,
    "carb_pct": 28,
    "protein_pct": 38
  },
  "reported_totals": {
    "kcal": 0,
    "protein_g": 0,
    "fat_g": 0,
    "carb_g": 0
  },
  "slots": [
    {
      "slot_no": 1,
      "name": "Meal 1",
      "entries": [
        {
          "food": "",
          "qty": 0,
          "unit": "g",
          "role": "protein",
          "macros_100g": {"kcal": 0, "protein_g": 0, "fat_g": 0, "carb_g": 0},
          "units": {},
          "source": "label",
          "source_note": ""
        }
      ]
    }
  ]
}
```

Rules while transcribing:

- `reported_totals` are the macro numbers the PDF itself states. These are the
  comparison target.
- `macros_100g` is per 100 g. If the PDF gives per-serving values, convert using
  the serving weight and record that weight in `units`.
- Where the PDF gives a unit like `tbsp`, `scoop`, or `packet`, add its gram
  weight to that entry's `units` map. If the gram weight is not in the PDF, look
  it up from the product label and note the source in `source_note`.
- If a value genuinely cannot be determined, stop and report it. Do not estimate.

- [ ] **Step 4: Verify the fixture by hand**

Open the PDF and check the fixture line by line against it. Confirm every slot,
every ingredient, every quantity, and the reported totals.

- [ ] **Step 5: Commit**

```bash
git add scripts/extract_plan_pdf.py tests/fixtures/keto_plan_a.json
git commit -m "test: add Keto Plan A fixture extracted from source PDF"
```

---

### Task 10: Golden-file test — reproduce Keto Plan A

**Files:**
- Create: `tests/test_golden_keto_a.py`
- Test: `tests/test_golden_keto_a.py`

**Interfaces:**
- Consumes: `create_item`, `add_unit` (Task 4), `create_person`, `create_profile` (Task 7), `create_day_plan`, `add_entry`, `evaluate` (Task 8), and `tests/fixtures/keto_plan_a.json` (Task 9).
- Produces: nothing consumed downstream. This is the checkpoint.

**This is the gate for the whole plan.** If the engine cannot reproduce a
hand-authored plan's totals from its own ingredients, something upstream is wrong
in units, normalization, or aggregation — and building the solver on top would
bury it.

- [ ] **Step 1: Write the golden test**

Create `tests/test_golden_keto_a.py`:

```python
"""Golden-file test: reproduce a coach-authored plan from its own ingredients.

This validates the whole chain — unit conversion, per-100 g normalization, and
aggregation — against known-good hand-authored output.
"""

import json
from pathlib import Path

import pytest

from yolk.foods import create_item
from yolk.macros import Macros
from yolk.people import create_person, create_profile
from yolk.planning.evaluate import add_entry, create_day_plan, evaluate

FIXTURE = Path(__file__).parent / "fixtures" / "keto_plan_a.json"


@pytest.fixture
def keto_a(db):
    """Build the plan described by the fixture and return its id."""
    spec = json.loads(FIXTURE.read_text(encoding="utf-8"))

    person_id = create_person(db, "Jen")
    profile_id = create_profile(
        db, person_id,
        name=spec["profile"]["name"],
        effective_on=spec["profile"]["effective_on"],
        kcal=spec["profile"]["kcal"],
        fat_pct=spec["profile"]["fat_pct"],
        carb_pct=spec["profile"]["carb_pct"],
        protein_pct=spec["profile"]["protein_pct"],
    )
    plan_id = create_day_plan(db, person_id, profile_id, name=spec["plan_name"])

    food_ids: dict[str, int] = {}
    for slot in spec["slots"]:
        for entry in slot["entries"]:
            name = entry["food"]
            if name not in food_ids:
                m = entry["macros_100g"]
                food_ids[name] = create_item(
                    db,
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
                )
            add_entry(
                db, plan_id,
                slot_no=slot["slot_no"],
                food_id=food_ids[name],
                qty=entry["qty"],
                unit=entry["unit"],
            )
    return plan_id, spec


def test_golden_plan_reproduces_reported_calories(db, keto_a):
    plan_id, spec = keto_a
    result = evaluate(db, plan_id)
    reported = spec["reported_totals"]["kcal"]
    # 1% of the day's calories, matching the profile's kcal tolerance
    assert result.totals.kcal == pytest.approx(reported, rel=0.01)


def test_golden_plan_reproduces_reported_protein(db, keto_a):
    plan_id, spec = keto_a
    result = evaluate(db, plan_id)
    assert result.totals.protein_g == pytest.approx(
        spec["reported_totals"]["protein_g"], abs=2.0
    )


def test_golden_plan_reproduces_reported_fat_and_carb(db, keto_a):
    plan_id, spec = keto_a
    result = evaluate(db, plan_id)
    assert result.totals.fat_g == pytest.approx(
        spec["reported_totals"]["fat_g"], rel=0.03
    )
    assert result.totals.carb_g == pytest.approx(
        spec["reported_totals"]["carb_g"], rel=0.03
    )


def test_golden_plan_has_every_slot_from_the_source(db, keto_a):
    plan_id, spec = keto_a
    result = evaluate(db, plan_id)
    assert [s.slot_no for s in result.slots] == [s["slot_no"] for s in spec["slots"]]


def test_golden_plan_lands_within_profile_tolerance(db, keto_a):
    """The coach's own plan should pass the tolerances we chose."""
    plan_id, _ = keto_a
    result = evaluate(db, plan_id)
    assert result.ok, (
        f"Coach-authored plan failed our tolerances: {result.within_tolerance}. "
        f"Totals {result.totals}, target {result.target}."
    )
```

- [ ] **Step 2: Run the golden test**

Run: `uv run pytest tests/test_golden_keto_a.py -v`
Expected: 5 passed.

If a test fails, **do not loosen the tolerance to make it pass.** Diagnose in this
order: (1) a wrong gram conversion in the fixture's `units`, (2) per-serving values
transcribed as per-100 g, (3) a missing ingredient, (4) a genuine engine bug. Report
which one it was.

- [ ] **Step 3: Run the whole suite**

Run: `uv run pytest -v`
Expected: all passing.

- [ ] **Step 4: Commit**

```bash
git add tests/test_golden_keto_a.py
git commit -m "test: add golden-file test reproducing Keto Plan A totals"
```

---

### Task 11: Cronometer recipe CSV import — NOT IMPLEMENTED

> **Status:** deferred at the project owner's request during execution. Tasks 1–10 are
> complete; this task was never started. It is independent of the checkpoint and its sample
> CSVs are already committed in `examples/`, so it can be picked up at any time — either as
> the first task of the next plan or on its own. Recorded here explicitly so it does not fall
> between plans.


**Files:**
- Create: `src/yolk/sources/cronometer.py`
- Test: `tests/test_cronometer.py`

**Interfaces:**
- Consumes: `Macros` (Task 2), `create_item` (Task 4).
- Produces: frozen dataclass `CronometerRow` (fields `food_id: str`, `name: str`, `serving_label: str`, `serving_g: float`, `macros: Macros` — macros already normalized to per 100 g); `parse_amount(text: str) -> tuple[str, float]`; `parse_file(path: Path) -> list[CronometerRow]`; `import_file(conn, path: Path, *, role: str) -> list[int]`.

**Independent of the checkpoint.** This task does not block Tasks 9–10 and can be done
before or after them.

The export is a flattened CSV: one row per recipe, roughly a hundred nutrient columns,
**no ingredient breakdown**. Rows therefore import as `kind='item'` — a finished dish
with known macros and a known portion weight behaves exactly like a purchased item.
Recipes whose composition matters still go through `create_recipe`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_cronometer.py`:

```python
from pathlib import Path

import pytest

from yolk.sources import cronometer

EXAMPLES = Path(__file__).parent.parent / "examples"
BARS_CSV = EXAMPLES / "cronometer_recipe_1.csv"
PITAS_CSV = EXAMPLES / "cronometer_recipe_2.csv"


def test_parse_amount_splits_label_and_grams():
    label, grams = cronometer.parse_amount("servings  — 169g")
    assert label == "servings"
    assert grams == pytest.approx(169.0)


def test_parse_amount_handles_multiword_label():
    label, grams = cronometer.parse_amount("pita quarter  — 54g")
    assert label == "pita quarter"
    assert grams == pytest.approx(54.0)


def test_parse_amount_rejects_unparseable():
    with pytest.raises(ValueError):
        cronometer.parse_amount("2 servings")


def test_parse_file_normalizes_to_per_100g():
    rows = cronometer.parse_file(BARS_CSV)
    assert len(rows) == 1
    row = rows[0]
    assert row.name == "Baked Vanilla Protein Oatmeal Breakfast Bars"
    assert row.serving_g == pytest.approx(169.0)
    # 316.75 kcal per 169 g
    assert row.macros.kcal == pytest.approx(187.43, abs=0.01)
    assert row.macros.protein_g == pytest.approx(11.67, abs=0.01)
    assert row.macros.fat_g == pytest.approx(4.49, abs=0.01)
    assert row.macros.carb_g == pytest.approx(25.34, abs=0.01)
    assert row.macros.fiber_g == pytest.approx(4.10, abs=0.01)


def test_parse_file_second_sample():
    rows = cronometer.parse_file(PITAS_CSV)
    row = rows[0]
    assert row.name == "Lebanese Meat Stuffed Pitas (Arayes)"
    assert row.serving_g == pytest.approx(54.0)
    assert row.macros.kcal == pytest.approx(210.33, abs=0.01)
    assert row.macros.protein_g == pytest.approx(17.56, abs=0.01)


def test_parse_file_skips_trailing_blank_rows():
    """Both sample files end with an empty line."""
    assert len(cronometer.parse_file(PITAS_CSV)) == 1


def test_columns_are_read_by_header_not_position():
    """Guards the failure mode: reading Fat off the wrong offset gives 43.09."""
    row = cronometer.parse_file(BARS_CSV)[0]
    fat_per_serving = row.macros.fat_g * row.serving_g / 100.0
    assert fat_per_serving == pytest.approx(7.59, abs=0.01)


def test_import_file_creates_item_with_serving_unit(db):
    ids = cronometer.import_file(db, BARS_CSV, role="carb")
    assert len(ids) == 1
    row = db.execute(
        "SELECT kind, name, source, source_ref, kcal_100g FROM foods WHERE id = ?",
        (ids[0],),
    ).fetchone()
    assert row["kind"] == "item"
    assert row["source"] == "cronometer"
    assert row["source_ref"] == "71976045"
    assert row["kcal_100g"] == pytest.approx(187.43, abs=0.01)

    unit = db.execute(
        "SELECT unit, grams FROM food_units WHERE food_id = ?", (ids[0],)
    ).fetchone()
    assert unit["unit"] == "servings"
    assert unit["grams"] == pytest.approx(169.0)


def test_imported_portion_macros_round_trip(db):
    """One serving must reproduce the CSV's own per-serving numbers."""
    from yolk.foods import portion_macros

    ids = cronometer.import_file(db, PITAS_CSV, role="protein")
    m = portion_macros(db, ids[0], 1, "pita quarter")
    assert m.kcal == pytest.approx(113.58, abs=0.01)
    assert m.protein_g == pytest.approx(9.48, abs=0.01)
    assert m.fat_g == pytest.approx(4.04, abs=0.01)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cronometer.py -v`
Expected: FAIL — `ImportError: cannot import name 'cronometer' from 'yolk.sources'`.

- [ ] **Step 3: Write the implementation**

Create `src/yolk/sources/cronometer.py`:

```python
"""Cronometer recipe CSV import.

The export is one row per recipe with roughly a hundred nutrient columns and
no ingredient breakdown, so rows become items rather than recipes. The Amount
column carries both the serving label and its gram weight, which gives us the
per-100 g normalization and a food_units row in a single parse.

Columns are addressed by header name. Positional parsing on a file this wide
produces plausible-looking garbage — the Fat column sits next to a run of
amino acid columns with similar magnitudes.
"""

from __future__ import annotations

import csv
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from yolk.foods import create_item
from yolk.macros import Macros

# label, then an em dash / en dash / hyphen, then a gram weight
AMOUNT_RE = re.compile(r"^\s*(?P<label>.*?)\s*[—–-]\s*(?P<grams>[\d.]+)\s*g\s*$")

COL_KCAL = "Energy (kcal)"
COL_PROTEIN = "Protein (g)"
COL_FAT = "Fat (g)"
COL_CARB = "Carbs (g)"
COL_FIBER = "Fiber (g)"


@dataclass(frozen=True)
class CronometerRow:
    food_id: str
    name: str
    serving_label: str
    serving_g: float
    macros: Macros  # already per 100 g


def parse_amount(text: str) -> tuple[str, float]:
    """Split an Amount cell into its serving label and gram weight.

    >>> parse_amount("servings  — 169g")
    ('servings', 169.0)
    """
    match = AMOUNT_RE.match(text)
    if not match:
        raise ValueError(
            f"Cannot parse serving weight from Amount cell {text!r}. Expected "
            f"something like 'servings — 169g'."
        )
    return match.group("label").strip(), float(match.group("grams"))


def _float(row: dict[str, str], column: str) -> float:
    value = (row.get(column) or "").strip()
    return float(value) if value else 0.0


def parse_file(path: Path) -> list[CronometerRow]:
    """Parse a Cronometer recipe CSV into per-100 g rows."""
    out: list[CronometerRow] = []
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            food_id = (raw.get("Food ID") or "").strip()
            if not food_id:
                continue  # trailing blank line

            label, serving_g = parse_amount(raw["Amount"])
            if serving_g <= 0:
                raise ValueError(
                    f"Non-positive serving weight for {raw.get('Food Name')!r}"
                )

            factor = 100.0 / serving_g
            out.append(
                CronometerRow(
                    food_id=food_id,
                    name=(raw.get("Food Name") or "").strip(),
                    serving_label=label,
                    serving_g=serving_g,
                    macros=Macros(
                        kcal=_float(raw, COL_KCAL),
                        protein_g=_float(raw, COL_PROTEIN),
                        fat_g=_float(raw, COL_FAT),
                        carb_g=_float(raw, COL_CARB),
                        fiber_g=_float(raw, COL_FIBER),
                    ).scale(factor),
                )
            )
    return out


def import_file(conn: sqlite3.Connection, path: Path, *, role: str) -> list[int]:
    """Import every recipe row in a CSV as an item, returning the new food ids."""
    ids: list[int] = []
    for row in parse_file(path):
        ids.append(
            create_item(
                conn,
                name=row.name,
                role=role,
                macros=row.macros,
                source="cronometer",
                source_ref=row.food_id,
                verified=False,
                units={row.serving_label: row.serving_g},
            )
        )
    return ids
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cronometer.py -v`
Expected: 9 passed.

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest -v`
Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add src/yolk/sources/cronometer.py tests/test_cronometer.py
git commit -m "feat: import Cronometer recipe CSVs as items with serving units"
```

---

## Deferred: the curated USDA starter set

Spec §10 step 4 pairs the USDA client with seeding a curated starter set of 60–80
whole foods. This plan builds the client (Task 6) but does not seed.

That is deliberate. Which foods belong in the starter set is answerable only after
Task 9 extracts what the coach's plans actually contain — seeding a guessed list
first would produce a library that overlaps the real one by accident and leaves the
golden test importing its foods from the fixture regardless. Once Keto Plan A, the
two other Keto plans, and the three Emergency plans are transcribed, the starter set
is simply the union of their ingredients, which is a better-grounded list than any
list assembled up front.

Seed it as the first task of the next plan, when that list exists.

---

## What this plan does not cover

Each of these gets its own plan, in this order, after the checkpoint holds:

1. `resolve_flex()` — bounded least-squares over flex entries, plus snapping to
   kitchen-realistic increments. Adds `scipy`.
2. `substitute()` and `fit()` — variant derivation and the grocery-find valve.
3. Protocols — rule resolution and violation reporting, extending `DayEvaluation`
   with a `violations` field.
4. Inventory and `gap_list()`.
5. Excel export via `openpyxl`.
6. Open Food Facts barcode import.
