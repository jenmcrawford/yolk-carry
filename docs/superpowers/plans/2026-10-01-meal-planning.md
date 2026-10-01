# Meal Planning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Plan meals in the browser. Start a new day plan from blank or open a draft of an existing one, change amounts and units, add, swap, and remove foods, and then save over the original, save as new, or discard. A saved plan never changes until a draft is saved over it.

**Architecture:**
- **Drafts.** A draft is a `day_plans` row with `status = 'draft'`, added by migration `0002`. All editing goes through a new library module, `planning/drafts.py`, which refuses to touch a saved plan's entries.
- **Error tolerance.** `evaluate()` gains an opt-in `partial=True`, so one unmeasurable entry shows on its own row instead of hiding the plan.
- **Display helpers.** `plan_slots`, `compare`, `units_for` and `default_portion` let the web layer stay free of SQL and arithmetic.
- **Web.** It gains a guard against cross-site posts, HTML error pages, and per-person ownership checks. On top of those it adds draft pages whose edits use htmx (vendored, so the app works offline) to swap one slot and the day totals in place. Every form still works as a plain post.

**Tech Stack:** Python 3.14, `uv`, FastAPI 0.142, Starlette 1.7, Jinja2, htmx 2.0.11 (vendored), stdlib `sqlite3`, `pytest` with FastAPI's `TestClient`.

**Spec:** [2026-10-01-plan-and-search-design.md](../specs/2026-10-01-plan-and-search-design.md), Part B (§4–§6). Part A (Foods page and egg icon) is built and merged.

## Global Constraints

- Python `>=3.14`, managed by `uv`.
- **Run tools as modules, not as console scripts.** Windows Smart App Control blocks the generated launchers in `.venv/Scripts/`. `uv run python -m pytest` works and `uv run pytest` does not.
- No new Python dependencies. htmx is a vendored static file, not a package.
- **The web layer does no arithmetic and no SQL.** No `conn.execute` anywhere under `src/yolk/web/`. Formatting a number in a template is display, and is allowed. Parsing a typed amount is done by the library (`drafts.parse_amount`), not by the route.
- **Templates consume library dataclasses directly.** No view-model layer.
- **Every fragment is a partial, and full pages include the same partials.**
- **Every form works without JavaScript.** htmx adds in-place updates on top; a plain POST gets a 303 redirect back to the page.
- **Portable SQL only.** It must also run on Postgres. Placeholders stay `?`. New code uses `RETURNING id` and annotates connections as `yolk.db.Connection`. Partial indexes and `coalesce` are portable; `INSERT OR REPLACE` and SQLite-only functions are not.
- **Migration files must not contain the words BEGIN, COMMIT, ROLLBACK, SAVEPOINT, RELEASE or END anywhere, comments included.** The runner rejects a migration containing any of them as a whole word, in any case, because it owns transaction control.
- **Every library function in `planning/drafts.py` commits on success and rolls back on failure.**
- Library tests use the `db` fixture (`:memory:`). Web tests use the `seeded` and `client` fixtures in `tests/conftest.py`, which build a seeded file under pytest's `tmp_path`. Any other `TestClient` passes `base_url="http://127.0.0.1"`, because `TrustedHostMiddleware` refuses the default `testserver` host. From Task 5 on, `client` also sends `Origin: http://127.0.0.1`, because POSTs without a same-machine Origin or Referer are refused. No test touches the repository's `yolk.db`.
- Starlette 1.x: `templates.TemplateResponse(request, "name.html", {...}, status_code=...)`, with the request first.
- Every page template receives `viewer`, so the header's person picker keeps working.
- A form field that may arrive empty is declared `Annotated[str, Form()] = ""` and validated by the library, so an empty field gives an inline message rather than FastAPI's 422.
- The full suite is `uv run python -m pytest`. It passes at 194 tests with one known warning (`StarletteDeprecationWarning` about `httpx2`) before this plan starts. It must pass at the end of every task with no new warnings.
- Commit at the end of every task. Every commit message has its subject line, a blank line, then exactly `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` on its own line.

---

## File Structure

**Created:**

| Path | Responsibility |
|---|---|
| `src/yolk/db/migrations/0002_draft_status.sql` | Adds `'draft'` to the plan status values; one open draft per plan |
| `src/yolk/planning/drafts.py` | Starting, editing, saving and discarding drafts |
| `src/yolk/web/routes/drafts.py` | Draft pages and every edit endpoint |
| `src/yolk/web/templates/drafts/detail.html` | The draft page |
| `src/yolk/web/templates/drafts/_changed.html` | The htmx answer to one edit: a slot plus the totals |
| `src/yolk/web/templates/foods/_picker.html` | The inline food picker under a slot |
| `src/yolk/web/templates/foods/pick.html` | The picker as a full page, for the no-JavaScript path |
| `src/yolk/web/static/htmx.min.js` | htmx 2.0.11, vendored |
| `tests/test_migration_0002.py`, `tests/test_drafts.py`, `tests/test_web_safety.py`, `tests/test_web_drafts.py`, `tests/test_web_editing.py` | Tests |

**Modified:**

| Path | Change |
|---|---|
| `src/yolk/errors.py` | `NotADraftError`, `DuplicatePlanNameError` |
| `src/yolk/planning/evaluate.py` | `evaluate(..., partial=False)`; `EntryEvaluation.error`; `DayEvaluation.excluded` |
| `src/yolk/planning/plans.py` | `PlanHeader.parent_plan_id`, `PlanSlot`, `plan_slots`, `compare`, `draft_summaries`, `entry_units` |
| `src/yolk/units.py` | `units_for`, `default_portion` |
| `src/yolk/people.py` | `ProfileChoice`, `current_profiles` |
| `src/yolk/web/app.py` | Cross-site guard, HTML error handlers, drafts router |
| `src/yolk/web/deps.py` | `owned_plan`, `is_htmx` |
| `src/yolk/web/routes/plans.py` | Ownership, partial evaluation, New plan, Edit or copy |
| `src/yolk/web/routes/foods.py` | The picker route |
| `src/yolk/web/templates/base.html` | Loads htmx |
| `src/yolk/web/templates/error.html` | Explicit title |
| `src/yolk/web/templates/plans/list.html`, `detail.html`, `_slot.html`, `_totals.html` | Drafts, empty slots, error rows, editing controls |
| `src/yolk/web/templates/foods/_results.html` | Optional per-row `pick` button |
| `src/yolk/web/static/app.css` | Buttons, inputs, error rows, draft actions, picker |
| `tests/conftest.py` | `client` sends a same-machine Origin |
| `tests/test_evaluate.py`, `tests/test_plans.py`, `tests/test_units.py`, `tests/test_people.py`, `tests/test_web_plans.py` | New tests |
| `README.md` | How to plan meals; run `migrate` once |

---

## Task 1: Migration 0002, draft status

**Files:**
- Create: `src/yolk/db/migrations/0002_draft_status.sql`
- Test: `tests/test_migration_0002.py` (create)

**Interfaces:**
- Consumes: `yolk.db.migrate.apply_migrations(conn, directory=MIGRATIONS_DIR) -> list[int]`, `MIGRATIONS_DIR`; `yolk.seed.seed_keto_plan_a(conn) -> (plan_id, spec)`; `yolk.planning.evaluate.evaluate`.
- Produces: the `day_plans.status` CHECK allows `'active'`, `'archived'`, `'draft'`. The unique partial index `idx_one_draft_per_plan ON day_plans (parent_plan_id) WHERE status = 'draft'`. Every other column, constraint and row is unchanged.

**How the rebuild works:** SQLite cannot alter a CHECK, so the table is rebuilt. The migration creates `day_plans_new` with the new CHECK and the same columns in the same order, copies every row, drops `day_plans`, renames the new table, and adds the index. The runner (`yolk.db.migrate`) turns foreign keys off around the script. That way dropping `day_plans` does not cascade into `day_plan_entries`. The runner also checks every foreign key before anything is kept. `day_plan_entries` refers to `day_plans` by name, so after the rename its references point at the rebuilt table.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_migration_0002.py`:

```python
import shutil
import sqlite3

import pytest

from yolk.db.connection import connect
from yolk.db.migrate import MIGRATIONS_DIR, apply_migrations
from yolk.planning.evaluate import evaluate
from yolk.seed import seed_keto_plan_a


def _rows(conn, table):
    return [tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY id")]


def _insert_draft(db, plan_id, name, parent):
    plan = db.execute(
        "SELECT person_id, profile_id FROM day_plans WHERE id = ?", (plan_id,)
    ).fetchone()
    db.execute(
        "INSERT INTO day_plans (person_id, profile_id, name, status, parent_plan_id, "
        "created_at) VALUES (?, ?, ?, 'draft', ?, '2026-10-01')",
        (plan["person_id"], plan["profile_id"], name, parent),
    )


def test_0002_keeps_every_plan_and_entry(tmp_path):
    """Build a database at version 1, fill it, then upgrade it in place."""
    shutil.copy(MIGRATIONS_DIR / "0001_baseline.sql", tmp_path / "0001_baseline.sql")
    conn = connect(":memory:")
    apply_migrations(conn, tmp_path)
    plan_id, _ = seed_keto_plan_a(conn)
    plans, entries = _rows(conn, "day_plans"), _rows(conn, "day_plan_entries")
    totals = evaluate(conn, plan_id).totals

    assert 2 in apply_migrations(conn)

    assert _rows(conn, "day_plans") == plans
    assert _rows(conn, "day_plan_entries") == entries
    assert evaluate(conn, plan_id).totals == totals
    conn.close()


def test_a_plan_may_be_a_draft(db):
    plan_id, _ = seed_keto_plan_a(db)
    _insert_draft(db, plan_id, "Draft one", plan_id)
    db.commit()
    count = db.execute(
        "SELECT count(*) AS n FROM day_plans WHERE status = 'draft'"
    ).fetchone()["n"]
    assert count == 1


def test_an_unknown_status_is_still_rejected(db):
    plan_id, _ = seed_keto_plan_a(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE day_plans SET status = 'bogus' WHERE id = ?", (plan_id,))


def test_a_saved_plan_may_have_only_one_open_draft(db):
    plan_id, _ = seed_keto_plan_a(db)
    _insert_draft(db, plan_id, "Draft one", plan_id)
    with pytest.raises(sqlite3.IntegrityError):
        _insert_draft(db, plan_id, "Draft two", plan_id)


def test_several_blank_drafts_may_coexist(db):
    plan_id, _ = seed_keto_plan_a(db)
    _insert_draft(db, plan_id, "Blank one", None)
    _insert_draft(db, plan_id, "Blank two", None)
    db.commit()
    count = db.execute(
        "SELECT count(*) AS n FROM day_plans WHERE status = 'draft'"
    ).fetchone()["n"]
    assert count == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_migration_0002.py -q`
Expected: FAIL. `test_0002_keeps_every_plan_and_entry` fails on `assert 2 in []`. The draft tests fail with `sqlite3.IntegrityError: CHECK constraint failed`. `test_a_saved_plan_may_have_only_one_open_draft` fails on the first insert, which is outside the `raises` block. `test_an_unknown_status_is_still_rejected` already passes.

- [ ] **Step 3: Write the migration**

Create `src/yolk/db/migrations/0002_draft_status.sql`, exactly:

```sql
-- A draft is a day plan with status 'draft'. Changing a CHECK means rebuilding
-- the table: the runner switches foreign keys off around this script and
-- checks them all afterwards, so day_plan_entries keeps every row.
CREATE TABLE day_plans_new (
    id              INTEGER PRIMARY KEY,
    person_id       INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    profile_id      INTEGER NOT NULL REFERENCES macro_profiles(id) ON DELETE RESTRICT,
    name            TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'archived', 'draft')),
    parent_plan_id  INTEGER REFERENCES day_plans(id) ON DELETE SET NULL,
    created_at      TEXT NOT NULL,
    notes           TEXT,
    UNIQUE (person_id, name)
);

INSERT INTO day_plans_new
    (id, person_id, profile_id, name, status, parent_plan_id, created_at, notes)
SELECT id, person_id, profile_id, name, status, parent_plan_id, created_at, notes
FROM day_plans;

DROP TABLE day_plans;

ALTER TABLE day_plans_new RENAME TO day_plans;

-- At most one open draft per saved plan. A blank draft has no parent, and
-- unique indexes allow repeated NULLs, so several blank drafts may coexist.
CREATE UNIQUE INDEX idx_one_draft_per_plan
    ON day_plans (parent_plan_id) WHERE status = 'draft';
```

Do not reword the comments with any of the transaction-control words listed in the Global Constraints. The runner would reject the file.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_migration_0002.py tests/test_migrate.py -q`
Expected: PASS

- [ ] **Step 5: Run the whole suite and commit**

Run: `uv run python -m pytest -q`
Expected: PASS, 199 tests, the one known warning

```bash
git add src/yolk/db/migrations/0002_draft_status.sql tests/test_migration_0002.py
git commit -m "feat: let a day plan be a draft, one open draft per plan" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 2: Partial evaluation

**Files:**
- Modify: `src/yolk/planning/evaluate.py`
- Test: `tests/test_evaluate.py`

**Interfaces:**
- Consumes: `yolk.errors.UnknownUnitError`, `MissingYieldError`; `to_grams`, `portion_macros`.
- Produces:
  - `evaluate(conn, day_plan_id, *, partial: bool = False) -> DayEvaluation`
  - `EntryEvaluation.grams: float | None`, `EntryEvaluation.macros: Macros | None`, `EntryEvaluation.error: str | None = None`
  - `DayEvaluation.excluded: int = 0`, the number of entries left out
  - `DayEvaluation.ok` is `False` whenever `excluded > 0`

**Behaviour:** With the default `partial=False`, nothing changes: the first entry that cannot be measured raises `UnknownUnitError` or `MissingYieldError`. With `partial=True`, such an entry comes back with `error` set to the exception's message and `grams` and `macros` set to `None`. It is left out of its slot's totals and the day's totals, and it is counted in `excluded`. No other exception is caught.

- [ ] **Step 1: Write the failing tests**

Add `from yolk.errors import UnknownUnitError` to the imports of `tests/test_evaluate.py`, then append:

```python
def _bad_entry(db, plan_id, unit="handful"):
    food_id = db.execute(
        "SELECT food_id FROM day_plan_entries WHERE day_plan_id = ? ORDER BY id",
        (plan_id,),
    ).fetchone()["food_id"]
    return add_entry(db, plan_id, slot_no=4, food_id=food_id, qty=1, unit=unit)


def test_partial_evaluation_flags_only_the_bad_entry_and_leaves_it_out(db, simple_plan):
    clean = evaluate(db, simple_plan)
    bad_id = _bad_entry(db, simple_plan)
    result = evaluate(db, simple_plan, partial=True)
    [bad] = [e for s in result.slots for e in s.entries if e.error]
    assert bad.entry_id == bad_id
    assert "handful" in bad.error
    assert (bad.grams, bad.macros) == (None, None)
    assert result.totals == clean.totals
    assert result.excluded == 1
    assert not result.ok


def test_default_evaluation_still_raises_on_a_bad_entry(db, simple_plan):
    _bad_entry(db, simple_plan)
    with pytest.raises(UnknownUnitError, match="handful"):
        evaluate(db, simple_plan)


def test_partial_evaluation_of_a_clean_plan_matches_the_default(db, simple_plan):
    assert evaluate(db, simple_plan, partial=True) == evaluate(db, simple_plan)


def test_a_recipe_without_macros_is_excluded_not_raised(db, simple_plan):
    recipe = db.execute(
        "INSERT INTO foods (kind, name, role, source) "
        "VALUES ('recipe', 'Chili', 'protein', 'computed') RETURNING id"
    ).fetchone()["id"]
    db.commit()
    add_entry(db, simple_plan, slot_no=6, food_id=recipe, qty=300, unit="g")
    result = evaluate(db, simple_plan, partial=True)
    assert result.excluded == 1
    [bad] = [e for s in result.slots for e in s.entries if e.error]
    assert "Chili" in bad.error
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_evaluate.py -q`
Expected: FAIL with `TypeError: evaluate() got an unexpected keyword argument 'partial'`. `test_default_evaluation_still_raises_on_a_bad_entry` already passes.

- [ ] **Step 3: Implement**

In `src/yolk/planning/evaluate.py`:

Add to the imports:

```python
from yolk.errors import MissingYieldError, UnknownUnitError
```

Replace the `EntryEvaluation` dataclass with:

```python
@dataclass(frozen=True)
class EntryEvaluation:
    entry_id: int
    food_id: int
    food_name: str
    qty: float
    unit: str
    # None exactly when `error` is set: the entry could not be measured.
    grams: float | None
    macros: Macros | None
    error: str | None = None
```

Replace the `DayEvaluation` dataclass with:

```python
@dataclass(frozen=True)
class DayEvaluation:
    day_plan_id: int
    plan_name: str
    totals: Macros
    target: Macros
    deltas: Macros
    within_tolerance: dict[str, bool]
    slots: list[SlotEvaluation] = field(default_factory=list)
    # Entries left out of every total because they could not be measured.
    excluded: int = 0

    @property
    def ok(self) -> bool:
        return self.excluded == 0 and all(self.within_tolerance.values())
```

Replace the start of `evaluate`, from its `def` line through the line `totals = sum((s.totals for s in slots), Macros.zero())`, with:

```python
def evaluate(
    conn: Connection, day_plan_id: int, *, partial: bool = False
) -> DayEvaluation:
    """Aggregate a day plan and compare it against its profile's targets.

    By default the first entry that cannot be measured raises, naming the food
    and unit. With partial=True that entry comes back with `error` set, is
    left out of every total, and is counted in `excluded`; the day is then
    never ok. The draft page uses this so one bad entry shows on its own row
    instead of hiding the whole plan.
    """
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
        try:
            grams = to_grams(conn, row["food_id"], row["qty"], row["unit"])
            macros = portion_macros(conn, row["food_id"], row["qty"], row["unit"])
            error = None
        except (UnknownUnitError, MissingYieldError) as exc:
            if not partial:
                raise
            grams, macros, error = None, None, str(exc)
        by_slot.setdefault(row["slot_no"], []).append(
            EntryEvaluation(
                entry_id=row["id"],
                food_id=row["food_id"],
                food_name=row["food_name"],
                qty=row["qty"],
                unit=row["unit"],
                grams=grams,
                macros=macros,
                error=error,
            )
        )

    slots = [
        SlotEvaluation(
            slot_no=slot_no,
            totals=sum(
                (e.macros for e in entries if e.macros is not None), Macros.zero()
            ),
            entries=entries,
        )
        for slot_no, entries in sorted(by_slot.items())
    ]
    totals = sum((s.totals for s in slots), Macros.zero())
    excluded = sum(1 for s in slots for e in s.entries if e.error is not None)
```

At the end of `evaluate`, add `excluded=excluded,` to the `DayEvaluation(...)` call, after `slots=slots,`. Leave the rest of the function (targets, deltas, tolerances) unchanged.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_evaluate.py tests/test_golden_keto_a.py -q`
Expected: PASS

- [ ] **Step 5: Run the whole suite and commit**

Run: `uv run python -m pytest -q`
Expected: PASS, 203 tests, the one known warning

```bash
git add src/yolk/planning/evaluate.py tests/test_evaluate.py
git commit -m "feat: evaluate a plan around entries that cannot be measured" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 3: The drafts library

**Files:**
- Modify: `src/yolk/errors.py`
- Create: `src/yolk/planning/drafts.py`
- Test: `tests/test_drafts.py` (create)

**Interfaces:**
- Consumes: migration 0002 (Task 1); `yolk.foods.portion_macros(conn, food_id, qty, unit) -> Macros`, which raises `UnknownUnitError`/`MissingYieldError` naming the food and unit.
- Produces, in `yolk.errors`:
  - `NotADraftError(YolkError)`
  - `DuplicatePlanNameError(YolkError)`
- Produces, in `yolk.planning.drafts`:
  - `DRAFT_SUFFIX = " (draft)"`
  - `EntryLocation`, a frozen dataclass: `plan_id: int`, `slot_no: int`
  - `parse_amount(text: str) -> float`. It raises `ValueError` "Amount must be a number, not '…'." or "Amount must be greater than 0."
  - `locate_entry(conn, entry_id) -> EntryLocation`, raising `LookupError`
  - `start_draft(conn, plan_id) -> int`
  - `start_blank_draft(conn, person_id, profile_id, name) -> int`
  - `add_entry_to_draft(conn, draft_id, *, slot_no, food_id, qty, unit) -> int`
  - `update_entry(conn, entry_id, *, qty, unit) -> None`
  - `replace_entry_food(conn, entry_id, food_id, *, qty, unit) -> None`
  - `remove_entry(conn, entry_id) -> None`
  - `save_over(conn, draft_id) -> None`
  - `save_as_new(conn, draft_id, *, name) -> int`
  - `discard_draft(conn, draft_id) -> None`

**Behaviour (spec §4.2):**
- **Starting a draft.**
  - `start_draft` copies a plan and its entries into a draft named `"<name> (draft)"`, with `parent_plan_id` set to the plan.
  - If the plan already has an open draft, it returns that draft's id.
  - It raises `ValueError` "… is already a draft." when given a draft.
- **Starting a blank draft.** `start_blank_draft` checks the profile belongs to the person, and raises `LookupError` if not. It strips the name; an empty name raises `ValueError` "A plan needs a name." A name the person already uses raises `DuplicatePlanNameError` "You already have a plan called '…'."
- **Edits.** The four edit functions raise `NotADraftError` when the target plan is not a draft. A quantity that is not a finite number greater than 0 raises `ValueError` before any write.
- **Adding a food.** `add_entry_to_draft` places the new entry after every existing entry in its slot.
- **Saving.**
  - `save_over` and `save_as_new` first measure every entry with `portion_macros`, so an unmeasurable draft raises and nothing is saved.
  - `save_over` raises `ValueError` "… so save it as new." for a draft with no parent.
  - `save_as_new` may keep the draft's own name: `ignore_id` lets a blank draft keep the name it was started with.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_drafts.py`:

```python
import pytest

from yolk.errors import DuplicatePlanNameError, NotADraftError, UnknownUnitError
from yolk.people import create_person
from yolk.planning import drafts
from yolk.planning.evaluate import evaluate
from yolk.seed import seed_keto_plan_a


@pytest.fixture
def keto(db):
    plan_id, _ = seed_keto_plan_a(db)
    return plan_id


def _entries(db, plan_id):
    return [
        tuple(row)
        for row in db.execute(
            "SELECT slot_no, food_id, qty, unit FROM day_plan_entries "
            "WHERE day_plan_id = ? ORDER BY slot_no, sort_order, id",
            (plan_id,),
        )
    ]


def _first_entry(db, plan_id):
    return db.execute(
        "SELECT id, food_id, qty, unit, slot_no FROM day_plan_entries "
        "WHERE day_plan_id = ? ORDER BY slot_no, sort_order, id",
        (plan_id,),
    ).fetchone()


def _plan(db, plan_id):
    return db.execute("SELECT * FROM day_plans WHERE id = ?", (plan_id,)).fetchone()


def _person_and_profile(db, plan_id):
    row = _plan(db, plan_id)
    return row["person_id"], row["profile_id"]


def _food(db, name):
    return db.execute("SELECT id FROM foods WHERE name = ?", (name,)).fetchone()["id"]


def _slot(db, plan_id, slot_no):
    [slot] = [s for s in evaluate(db, plan_id).slots if s.slot_no == slot_no]
    return slot


def test_editing_a_draft_never_changes_the_saved_plan(db, keto):
    """The most important test in this design."""
    saved_totals, saved_entries = evaluate(db, keto).totals, _entries(db, keto)
    draft = drafts.start_draft(db, keto)
    first = _first_entry(db, draft)
    drafts.update_entry(db, first["id"], qty=first["qty"] * 3, unit=first["unit"])
    drafts.add_entry_to_draft(
        db, draft, slot_no=1, food_id=_food(db, "Pork Rinds"), qty=50, unit="g"
    )
    drafts.remove_entry(db, _slot(db, draft, 2).entries[0].entry_id)

    assert evaluate(db, keto).totals == saved_totals
    assert _entries(db, keto) == saved_entries
    assert evaluate(db, draft).totals != saved_totals


def test_a_draft_copies_every_entry_in_order(db, keto):
    draft = drafts.start_draft(db, keto)
    row = _plan(db, draft)
    assert (row["name"], row["status"], row["parent_plan_id"]) == (
        "Keto Meal Plan A (draft)", "draft", keto
    )
    assert _entries(db, draft) == _entries(db, keto)


def test_starting_a_draft_twice_returns_the_same_draft(db, keto):
    assert drafts.start_draft(db, keto) == drafts.start_draft(db, keto)


def test_a_draft_of_a_draft_is_refused(db, keto):
    draft = drafts.start_draft(db, keto)
    with pytest.raises(ValueError, match="already a draft"):
        drafts.start_draft(db, draft)


def test_entries_of_a_saved_plan_cannot_be_edited(db, keto):
    entry = _first_entry(db, keto)
    with pytest.raises(NotADraftError):
        drafts.update_entry(db, entry["id"], qty=2, unit=entry["unit"])
    with pytest.raises(NotADraftError):
        drafts.replace_entry_food(
            db, entry["id"], entry["food_id"], qty=2, unit=entry["unit"]
        )
    with pytest.raises(NotADraftError):
        drafts.remove_entry(db, entry["id"])
    with pytest.raises(NotADraftError):
        drafts.add_entry_to_draft(
            db, keto, slot_no=1, food_id=entry["food_id"], qty=1, unit="g"
        )
    assert _first_entry(db, keto)["qty"] == entry["qty"]


def test_a_non_positive_amount_is_refused_before_anything_changes(db, keto):
    draft = drafts.start_draft(db, keto)
    entry = _first_entry(db, draft)
    for bad in (0, -1, float("nan")):
        with pytest.raises(ValueError, match="greater than 0"):
            drafts.update_entry(db, entry["id"], qty=bad, unit=entry["unit"])
    assert _first_entry(db, draft)["qty"] == entry["qty"]


def test_parse_amount_reads_a_typed_number():
    assert drafts.parse_amount(" 1.5 ") == 1.5
    cases = [
        ("abc", "must be a number"),
        ("", "must be a number"),
        ("0", "greater than 0"),
        ("-2", "greater than 0"),
        ("inf", "greater than 0"),
        ("nan", "greater than 0"),
    ]
    for text, message in cases:
        with pytest.raises(ValueError, match=message):
            drafts.parse_amount(text)


def test_new_entries_go_to_the_end_of_their_slot(db, keto):
    draft = drafts.start_draft(db, keto)
    pork, coffee = _food(db, "Pork Rinds"), _food(db, "Buff Chick Coffee")
    drafts.add_entry_to_draft(db, draft, slot_no=2, food_id=pork, qty=10, unit="g")
    drafts.add_entry_to_draft(db, draft, slot_no=2, food_id=coffee, qty=1, unit="packet")
    assert [e.food_id for e in _slot(db, draft, 2).entries][-2:] == [pork, coffee]


def test_replacing_a_food_keeps_the_entry_in_place(db, keto):
    draft = drafts.start_draft(db, keto)
    first = _slot(db, draft, 2).entries[0]
    pork = _food(db, "Pork Rinds")
    drafts.replace_entry_food(db, first.entry_id, pork, qty=30, unit="g")
    now = _slot(db, draft, 2).entries[0]
    assert (now.entry_id, now.food_id, now.qty, now.unit) == (first.entry_id, pork, 30, "g")


def test_locate_entry_names_its_plan_and_slot(db, keto):
    entry = _first_entry(db, keto)
    where = drafts.locate_entry(db, entry["id"])
    assert (where.plan_id, where.slot_no) == (keto, entry["slot_no"])
    with pytest.raises(LookupError):
        drafts.locate_entry(db, 999_999)


def test_save_over_makes_the_parent_match_the_draft_and_removes_it(db, keto):
    draft = drafts.start_draft(db, keto)
    entry = _first_entry(db, draft)
    drafts.update_entry(db, entry["id"], qty=entry["qty"] * 2, unit=entry["unit"])
    draft_entries, draft_totals = _entries(db, draft), evaluate(db, draft).totals

    drafts.save_over(db, draft)

    assert _entries(db, keto) == draft_entries
    assert evaluate(db, keto).totals == draft_totals
    assert _plan(db, draft) is None


def test_save_over_needs_a_draft_with_a_parent(db, keto):
    person, profile = _person_and_profile(db, keto)
    blank = drafts.start_blank_draft(db, person, profile, "Rest day")
    with pytest.raises(ValueError, match="save it as new"):
        drafts.save_over(db, blank)


def test_save_as_new_keeps_lineage_and_leaves_the_parent_alone(db, keto):
    saved_totals = evaluate(db, keto).totals
    draft = drafts.start_draft(db, keto)
    entry = _first_entry(db, draft)
    drafts.update_entry(db, entry["id"], qty=entry["qty"] * 2, unit=entry["unit"])

    assert drafts.save_as_new(db, draft, name="Keto Meal Plan B") == draft

    row = _plan(db, draft)
    assert (row["name"], row["status"], row["parent_plan_id"]) == (
        "Keto Meal Plan B", "active", keto
    )
    assert evaluate(db, keto).totals == saved_totals


def test_save_as_new_refuses_a_name_already_in_use(db, keto):
    draft = drafts.start_draft(db, keto)
    with pytest.raises(DuplicatePlanNameError, match="Keto Meal Plan A"):
        drafts.save_as_new(db, draft, name="Keto Meal Plan A")
    assert _plan(db, draft)["status"] == "draft"


def test_a_draft_that_cannot_be_measured_cannot_be_saved(db, keto):
    saved_entries = _entries(db, keto)
    draft = drafts.start_draft(db, keto)
    drafts.add_entry_to_draft(
        db, draft, slot_no=1, food_id=_food(db, "Pork Rinds"), qty=1, unit="handful"
    )
    with pytest.raises(UnknownUnitError, match="handful"):
        drafts.save_over(db, draft)
    with pytest.raises(UnknownUnitError, match="handful"):
        drafts.save_as_new(db, draft, name="Keto Meal Plan B")
    assert _entries(db, keto) == saved_entries
    assert _plan(db, draft)["status"] == "draft"


def test_discard_removes_the_draft_and_its_entries(db, keto):
    saved_entries = _entries(db, keto)
    draft = drafts.start_draft(db, keto)
    drafts.discard_draft(db, draft)
    assert _plan(db, draft) is None
    assert _entries(db, draft) == []
    assert _entries(db, keto) == saved_entries


def test_a_blank_draft_has_its_name_and_no_entries(db, keto):
    person, profile = _person_and_profile(db, keto)
    blank = drafts.start_blank_draft(db, person, profile, "  Rest day ")
    row = _plan(db, blank)
    assert (row["name"], row["status"], row["parent_plan_id"], row["profile_id"]) == (
        "Rest day", "draft", None, profile
    )
    assert _entries(db, blank) == []


def test_a_blank_draft_refuses_a_taken_or_empty_name(db, keto):
    person, profile = _person_and_profile(db, keto)
    with pytest.raises(DuplicatePlanNameError):
        drafts.start_blank_draft(db, person, profile, "Keto Meal Plan A")
    with pytest.raises(ValueError, match="needs a name"):
        drafts.start_blank_draft(db, person, profile, "   ")


def test_a_blank_draft_refuses_another_persons_profile(db, keto):
    _, profile = _person_and_profile(db, keto)
    sam = create_person(db, "Sam")
    with pytest.raises(LookupError):
        drafts.start_blank_draft(db, sam, profile, "Sam plan")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_drafts.py -q`
Expected: FAIL at import with `ImportError: cannot import name 'DuplicatePlanNameError' from 'yolk.errors'`

- [ ] **Step 3: Add the errors**

Append to `src/yolk/errors.py`:

```python


class NotADraftError(YolkError):
    """A saved plan's entries were edited. Only a draft's entries change."""


class DuplicatePlanNameError(YolkError):
    """This person already has a plan with that name."""
```

- [ ] **Step 4: Write the module**

Create `src/yolk/planning/drafts.py`:

```python
"""Drafts: the only way a plan's entries change.

A draft is a day_plans row with status 'draft'. Edits land on the draft, and a
saved plan changes only when a draft is saved over it, so a half-finished idea
can never leak into a plan in use. Every function here commits on success and
rolls back on failure.
"""

from __future__ import annotations

import math
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone

from yolk.db import Connection
from yolk.errors import DuplicatePlanNameError, NotADraftError
from yolk.foods import portion_macros

DRAFT_SUFFIX = " (draft)"


@dataclass(frozen=True)
class EntryLocation:
    plan_id: int
    slot_no: int


@contextmanager
def _unit_of_work(conn: Connection) -> Iterator[None]:
    """Commit what the block wrote, or roll all of it back if it raised."""
    try:
        yield
    except Exception:
        conn.rollback()
        raise
    conn.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_positive(qty: float) -> None:
    # Written as a positive test so that NaN, which compares false to
    # everything, is refused too.
    if not (math.isfinite(qty) and qty > 0):
        raise ValueError("Amount must be greater than 0.")


def parse_amount(text: str) -> float:
    """A typed amount as a number greater than 0, or ValueError saying what is wrong."""
    cleaned = text.strip()
    try:
        value = float(cleaned)
    except ValueError:
        raise ValueError(f"Amount must be a number, not {cleaned!r}.") from None
    _require_positive(value)
    return value


def _plan(conn: Connection, plan_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT id, person_id, profile_id, name, status, parent_plan_id, notes "
        "FROM day_plans WHERE id = ?",
        (plan_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"No day plan with id {plan_id}")
    return row


def _draft(conn: Connection, plan_id: int) -> sqlite3.Row:
    row = _plan(conn, plan_id)
    if row["status"] != "draft":
        raise NotADraftError(
            f"{row['name']!r} is a saved plan, not a draft. Start a draft to "
            f"change it."
        )
    return row


def locate_entry(conn: Connection, entry_id: int) -> EntryLocation:
    """Which plan and slot an entry belongs to."""
    row = conn.execute(
        "SELECT day_plan_id, slot_no FROM day_plan_entries WHERE id = ?",
        (entry_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"No plan entry with id {entry_id}")
    return EntryLocation(plan_id=row["day_plan_id"], slot_no=row["slot_no"])


def _free_name(
    conn: Connection, person_id: int, name: str, *, ignore_id: int | None = None
) -> str:
    """The name, stripped, once it is known to be non-empty and unused."""
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("A plan needs a name.")
    row = conn.execute(
        "SELECT id FROM day_plans WHERE person_id = ? AND name = ?",
        (person_id, cleaned),
    ).fetchone()
    if row is not None and row["id"] != ignore_id:
        raise DuplicatePlanNameError(f"You already have a plan called {cleaned!r}.")
    return cleaned


def _copy_entries(conn: Connection, from_plan: int, to_plan: int) -> None:
    conn.execute(
        "INSERT INTO day_plan_entries (day_plan_id, slot_no, food_id, qty, unit, "
        "flex, flex_min_g, flex_max_g, sort_order) "
        "SELECT ?, slot_no, food_id, qty, unit, flex, flex_min_g, flex_max_g, "
        "sort_order FROM day_plan_entries WHERE day_plan_id = ? "
        "ORDER BY slot_no, sort_order, id",
        (to_plan, from_plan),
    )


def _require_measurable(conn: Connection, plan_id: int) -> None:
    """Raise, naming the food and unit, if any entry cannot become macros."""
    for row in conn.execute(
        "SELECT food_id, qty, unit FROM day_plan_entries WHERE day_plan_id = ?",
        (plan_id,),
    ).fetchall():
        portion_macros(conn, row["food_id"], row["qty"], row["unit"])


def start_draft(conn: Connection, plan_id: int) -> int:
    """Open a draft of a saved plan, or return the draft already open for it."""
    plan = _plan(conn, plan_id)
    if plan["status"] == "draft":
        raise ValueError(f"{plan['name']!r} is already a draft.")
    existing = conn.execute(
        "SELECT id FROM day_plans WHERE parent_plan_id = ? AND status = 'draft'",
        (plan_id,),
    ).fetchone()
    if existing is not None:
        return existing["id"]
    name = _free_name(conn, plan["person_id"], plan["name"] + DRAFT_SUFFIX)
    with _unit_of_work(conn):
        draft_id = conn.execute(
            "INSERT INTO day_plans (person_id, profile_id, name, status, "
            "parent_plan_id, created_at, notes) "
            "VALUES (?, ?, ?, 'draft', ?, ?, ?) RETURNING id",
            (plan["person_id"], plan["profile_id"], name, plan_id, _now(),
             plan["notes"]),
        ).fetchone()["id"]
        _copy_entries(conn, plan_id, draft_id)
    return draft_id


def start_blank_draft(
    conn: Connection, person_id: int, profile_id: int, name: str
) -> int:
    """A new, empty plan to fill in, as a draft with no parent."""
    profile = conn.execute(
        "SELECT person_id FROM macro_profiles WHERE id = ?", (profile_id,)
    ).fetchone()
    if profile is None or profile["person_id"] != person_id:
        raise LookupError(f"Person {person_id} has no macro profile {profile_id}.")
    cleaned = _free_name(conn, person_id, name)
    with _unit_of_work(conn):
        draft_id = conn.execute(
            "INSERT INTO day_plans (person_id, profile_id, name, status, created_at) "
            "VALUES (?, ?, ?, 'draft', ?) RETURNING id",
            (person_id, profile_id, cleaned, _now()),
        ).fetchone()["id"]
    return draft_id


def add_entry_to_draft(
    conn: Connection,
    draft_id: int,
    *,
    slot_no: int,
    food_id: int,
    qty: float,
    unit: str,
) -> int:
    """Add a food at the end of a slot."""
    _require_positive(qty)
    _draft(conn, draft_id)
    with _unit_of_work(conn):
        entry_id = conn.execute(
            "INSERT INTO day_plan_entries (day_plan_id, slot_no, food_id, qty, unit, "
            "sort_order) "
            "SELECT ?, ?, ?, ?, ?, coalesce(max(sort_order), -1) + 1 "
            "FROM day_plan_entries WHERE day_plan_id = ? AND slot_no = ? "
            "RETURNING id",
            (draft_id, slot_no, food_id, qty, unit, draft_id, slot_no),
        ).fetchone()["id"]
    return entry_id


def update_entry(conn: Connection, entry_id: int, *, qty: float, unit: str) -> None:
    _require_positive(qty)
    _draft(conn, locate_entry(conn, entry_id).plan_id)
    with _unit_of_work(conn):
        conn.execute(
            "UPDATE day_plan_entries SET qty = ?, unit = ? WHERE id = ?",
            (qty, unit, entry_id),
        )


def replace_entry_food(
    conn: Connection, entry_id: int, food_id: int, *, qty: float, unit: str
) -> None:
    """Swap the food on an entry, keeping its slot and position."""
    _require_positive(qty)
    _draft(conn, locate_entry(conn, entry_id).plan_id)
    with _unit_of_work(conn):
        conn.execute(
            "UPDATE day_plan_entries SET food_id = ?, qty = ?, unit = ? WHERE id = ?",
            (food_id, qty, unit, entry_id),
        )


def remove_entry(conn: Connection, entry_id: int) -> None:
    _draft(conn, locate_entry(conn, entry_id).plan_id)
    with _unit_of_work(conn):
        conn.execute("DELETE FROM day_plan_entries WHERE id = ?", (entry_id,))


def save_over(conn: Connection, draft_id: int) -> None:
    """Replace the parent plan's entries with the draft's, then drop the draft."""
    draft = _draft(conn, draft_id)
    parent_id = draft["parent_plan_id"]
    if parent_id is None:
        raise ValueError(
            "This draft is a new plan, not a copy of one, so save it as new."
        )
    _require_measurable(conn, draft_id)
    with _unit_of_work(conn):
        conn.execute("DELETE FROM day_plan_entries WHERE day_plan_id = ?", (parent_id,))
        _copy_entries(conn, draft_id, parent_id)
        # The draft's own entries go with it: ON DELETE CASCADE.
        conn.execute("DELETE FROM day_plans WHERE id = ?", (draft_id,))


def save_as_new(conn: Connection, draft_id: int, *, name: str) -> int:
    """Make the draft a saved plan under `name`, keeping its parent as lineage."""
    draft = _draft(conn, draft_id)
    cleaned = _free_name(conn, draft["person_id"], name, ignore_id=draft_id)
    _require_measurable(conn, draft_id)
    with _unit_of_work(conn):
        conn.execute(
            "UPDATE day_plans SET name = ?, status = 'active', created_at = ? "
            "WHERE id = ?",
            (cleaned, _now(), draft_id),
        )
    return draft_id


def discard_draft(conn: Connection, draft_id: int) -> None:
    _draft(conn, draft_id)
    with _unit_of_work(conn):
        conn.execute("DELETE FROM day_plans WHERE id = ?", (draft_id,))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_drafts.py -q`
Expected: PASS, 19 tests

- [ ] **Step 6: Run the whole suite and commit**

Run: `uv run python -m pytest -q`
Expected: PASS, 222 tests, the one known warning

```bash
git add src/yolk/errors.py src/yolk/planning/drafts.py tests/test_drafts.py
git commit -m "feat: start, edit, save, and discard plan drafts" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 4: Display helpers

**Files:**
- Modify: `src/yolk/planning/plans.py` (full replacement below)
- Modify: `src/yolk/units.py`, `src/yolk/people.py`
- Test: `tests/test_plans.py`, `tests/test_units.py`, `tests/test_people.py`

**Interfaces:**
- Consumes: `evaluate` and `DayEvaluation`/`SlotEvaluation` (Task 2); `drafts.start_draft`, `drafts.start_blank_draft` (Task 3, in tests only); `slot_names(conn, profile_id)` from `yolk.people`.
- Produces:
  - `PlanHeader` gains `parent_plan_id: int | None = None`.
  - `PlanSlot`, a frozen dataclass: `slot_no: int`, `name: str`, `slot: SlotEvaluation | None`.
  - `plan_slots(conn, plan_id, evaluation) -> list[PlanSlot]`
  - `compare(draft: DayEvaluation, saved: DayEvaluation) -> Macros`
  - `draft_summaries(conn, person_id) -> list[PlanSummary]`. `plan_summaries` is unchanged in behaviour.
  - `entry_units(conn, evaluation) -> dict[int, list[str]]`, keyed by food id.
  - `yolk.units.DISPLAY_MASS_UNITS = ("g", "oz", "lb", "kg")`
  - `yolk.units.units_for(conn, food_id) -> list[str]`: the food's own units (default display unit first, then by name), then any `DISPLAY_MASS_UNITS` not already listed.
  - `yolk.units.default_portion(conn, food_id) -> tuple[float, str]`: `(1.0, first own unit)`, or `(100.0, "g")` when the food has none.
  - `yolk.people.ProfileChoice`, a frozen dataclass: `id: int`, `name: str`, `kcal: float`.
  - `yolk.people.current_profiles(conn, person_id, on_date) -> list[ProfileChoice]`: for each profile name, the row in force on `on_date`, ordered by name.

- [ ] **Step 1: Write the failing tests**

In `tests/test_plans.py`, add `from yolk.macros import Macros`, `from yolk.planning import drafts`, and `from yolk.planning.evaluate import DayEvaluation, evaluate`. Extend the `yolk.planning.plans` import to `compare, draft_summaries, entry_units, get_plan, plan_slots, plan_summaries`. Then append:

```python
def test_a_blank_draft_shows_every_slot_template_empty(db):
    plan_id, spec = seed_keto_plan_a(db)
    header = get_plan(db, plan_id)
    blank = drafts.start_blank_draft(db, header.person_id, header.profile_id, "Rest day")
    slots = plan_slots(db, blank, evaluate(db, blank, partial=True))
    assert [(s.slot_no, s.name) for s in slots] == [
        (s["slot_no"], s["name"]) for s in spec["slots"]
    ]
    assert all(s.slot is None for s in slots)


def test_a_slot_with_entries_but_no_template_is_named_by_number(db):
    plan_id, _ = seed_keto_plan_a(db)
    add_entry(db, plan_id, slot_no=7, food_id=_first_food_id(db, plan_id), qty=10, unit="g")
    slots = plan_slots(db, plan_id, evaluate(db, plan_id))
    assert (slots[-1].slot_no, slots[-1].name) == (7, "Slot 7")
    assert slots[-1].slot is not None


def test_compare_subtracts_the_saved_totals_from_the_drafts():
    def day(totals):
        return DayEvaluation(
            day_plan_id=1, plan_name="p", totals=totals, target=Macros(),
            deltas=Macros(), within_tolerance={},
        )

    diff = compare(
        day(Macros(kcal=2300, protein_g=190, fat_g=90, carb_g=160)),
        day(Macros(kcal=2150, protein_g=200, fat_g=80, carb_g=160)),
    )
    assert diff == Macros(kcal=150, protein_g=-10, fat_g=10, carb_g=0)


def test_drafts_are_listed_apart_from_saved_plans(db):
    plan_id, _ = seed_keto_plan_a(db)
    person = get_plan(db, plan_id).person_id
    draft = drafts.start_draft(db, plan_id)
    assert [s.id for s in plan_summaries(db, person)] == [plan_id]
    assert [s.id for s in draft_summaries(db, person)] == [draft]


def test_get_plan_reports_a_drafts_parent(db):
    plan_id, _ = seed_keto_plan_a(db)
    draft = drafts.start_draft(db, plan_id)
    assert get_plan(db, draft).parent_plan_id == plan_id
    assert get_plan(db, plan_id).parent_plan_id is None


def test_entry_units_covers_every_food_in_the_plan(db):
    plan_id, _ = seed_keto_plan_a(db)
    evaluation = evaluate(db, plan_id)
    units = entry_units(db, evaluation)
    assert set(units) == {e.food_id for s in evaluation.slots for e in s.entries}
    coffee = db.execute(
        "SELECT id FROM foods WHERE name = 'Buff Chick Coffee'"
    ).fetchone()["id"]
    assert units[coffee][0] == "packet"
```

`_first_food_id`, `seed_keto_plan_a` and `add_entry` already exist in `tests/test_plans.py`.

Append to `tests/test_units.py`. Add the imports it lacks: `from yolk.foods import add_unit, create_item`, `from yolk.macros import Macros`, and `from yolk.units import default_portion, units_for`.

```python
SOME = Macros(kcal=100, protein_g=10, fat_g=5, carb_g=2)


def test_units_for_lists_the_foods_own_units_then_mass_units(db):
    food = create_item(
        db, name="Karbolyn", role="carb", macros=SOME, units={"scoop": 50.0, "cup": 120.0}
    )
    assert units_for(db, food) == ["cup", "scoop", "g", "oz", "lb", "kg"]


def test_the_default_display_unit_comes_first(db):
    food = create_item(db, name="Whey", role="protein", macros=SOME, units={"cup": 120.0})
    add_unit(db, food, "scoop", 50.0, is_default_display=True)
    assert units_for(db, food)[0] == "scoop"
    assert default_portion(db, food) == (1.0, "scoop")


def test_default_portion_falls_back_to_100_grams(db):
    with_units = create_item(db, name="Rice", role="carb", macros=SOME, units={"cup": 158.0})
    bare = create_item(db, name="Chicken", role="protein", macros=SOME)
    assert default_portion(db, with_units) == (1.0, "cup")
    assert default_portion(db, bare) == (100.0, "g")
```

Append to `tests/test_people.py`, adding `current_profiles` to its `yolk.people` import:

```python
def test_current_profiles_lists_each_profile_as_it_stands_on_a_date(db):
    pid = create_person(db, "Jen")
    for name, effective_on, kcal in [
        ("training", "2026-01-01", 2000),
        ("training", "2026-07-14", 2150),
        ("training", "2026-12-01", 2300),
        ("rest", "2026-07-14", 2115),
    ]:
        create_profile(
            db, pid, name=name, effective_on=effective_on, kcal=kcal,
            fat_pct=34, carb_pct=28, protein_pct=38,
        )
    choices = current_profiles(db, pid, "2026-08-09")
    assert [(c.name, c.kcal) for c in choices] == [("rest", 2115), ("training", 2150)]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_plans.py tests/test_units.py tests/test_people.py -q`
Expected: FAIL at import (`cannot import name 'compare'`, `'default_portion'`, `'current_profiles'`).

- [ ] **Step 3: Implement the units helpers**

Append to `src/yolk/units.py`:

```python
# Mass units offered for every food, after its own units.
DISPLAY_MASS_UNITS = ("g", "oz", "lb", "kg")


def _own_units(conn: Connection, food_id: int) -> list[str]:
    rows = conn.execute(
        "SELECT unit FROM food_units WHERE food_id = ? "
        "ORDER BY is_default_display DESC, unit",
        (food_id,),
    ).fetchall()
    return [row["unit"] for row in rows]


def units_for(conn: Connection, food_id: int) -> list[str]:
    """Units this food can be measured in: its own first, then mass units."""
    own = _own_units(conn, food_id)
    return own + [unit for unit in DISPLAY_MASS_UNITS if unit not in own]


def default_portion(conn: Connection, food_id: int) -> tuple[float, str]:
    """One of the food's usual unit, or 100 g when it has none."""
    own = _own_units(conn, food_id)
    return (1.0, own[0]) if own else (100.0, "g")
```

- [ ] **Step 4: Implement the profile choices**

In `src/yolk/people.py`, add after the `Person` dataclass:

```python
@dataclass(frozen=True)
class ProfileChoice:
    id: int
    name: str
    kcal: float
```

and at the end of the file:

```python
def current_profiles(
    conn: Connection, person_id: int, on_date: str
) -> list[ProfileChoice]:
    """Each of the person's profiles as it stands on `on_date`, ordered by name."""
    rows = conn.execute(
        "SELECT id, name, kcal FROM macro_profiles m "
        "WHERE person_id = ? AND effective_on = ("
        "    SELECT max(effective_on) FROM macro_profiles "
        "    WHERE person_id = m.person_id AND name = m.name AND effective_on <= ?"
        ") ORDER BY name",
        (person_id, on_date),
    ).fetchall()
    return [ProfileChoice(id=row["id"], name=row["name"], kcal=row["kcal"]) for row in rows]
```

- [ ] **Step 5: Replace `src/yolk/planning/plans.py`**

```python
"""Reading plans for display: headers, lists, slots, and comparisons.

These exist so the web layer can show plans without running SQL itself.
"""

from __future__ import annotations

from dataclasses import dataclass

from yolk.db import Connection
from yolk.errors import YolkError
from yolk.macros import Macros
from yolk.people import slot_names
from yolk.planning.evaluate import DayEvaluation, SlotEvaluation, evaluate
from yolk.units import units_for


@dataclass(frozen=True)
class PlanHeader:
    id: int
    person_id: int
    profile_id: int
    profile_name: str
    name: str
    status: str
    # Set for a draft started from a saved plan, and kept as lineage after
    # the draft is saved as new.
    parent_plan_id: int | None = None


@dataclass(frozen=True)
class PlanSummary:
    id: int
    name: str
    profile_name: str
    # None exactly when the plan could not be evaluated; `error` then says why.
    ok: bool | None
    error: str | None


@dataclass(frozen=True)
class PlanSlot:
    slot_no: int
    name: str
    # None when nothing is planned in this slot yet.
    slot: SlotEvaluation | None


def get_plan(conn: Connection, plan_id: int) -> PlanHeader:
    row = conn.execute(
        "SELECT p.id, p.person_id, p.profile_id, p.name, p.status, "
        "p.parent_plan_id, m.name AS profile_name "
        "FROM day_plans p JOIN macro_profiles m ON m.id = p.profile_id "
        "WHERE p.id = ?",
        (plan_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"No day plan with id {plan_id}")
    return PlanHeader(
        id=row["id"],
        person_id=row["person_id"],
        profile_id=row["profile_id"],
        profile_name=row["profile_name"],
        name=row["name"],
        status=row["status"],
        parent_plan_id=row["parent_plan_id"],
    )


def _summaries(conn: Connection, person_id: int, status: str) -> list[PlanSummary]:
    rows = conn.execute(
        "SELECT p.id, p.name, m.name AS profile_name "
        "FROM day_plans p JOIN macro_profiles m ON m.id = p.profile_id "
        "WHERE p.person_id = ? AND p.status = ? ORDER BY p.name, p.id",
        (person_id, status),
    ).fetchall()
    summaries: list[PlanSummary] = []
    for row in rows:
        try:
            ok, error = evaluate(conn, row["id"]).ok, None
        except YolkError as exc:
            ok, error = None, str(exc)
        summaries.append(
            PlanSummary(
                id=row["id"],
                name=row["name"],
                profile_name=row["profile_name"],
                ok=ok,
                error=error,
            )
        )
    return summaries


def plan_summaries(conn: Connection, person_id: int) -> list[PlanSummary]:
    """A person's active plans, each marked within tolerance or not.

    A plan that cannot be evaluated is still listed, carrying the error, so
    one bad entry cannot hide every other plan.
    """
    return _summaries(conn, person_id, "active")


def draft_summaries(conn: Connection, person_id: int) -> list[PlanSummary]:
    """A person's open drafts, so unfinished work can be picked up again."""
    return _summaries(conn, person_id, "draft")


def plan_slots(
    conn: Connection, plan_id: int, evaluation: DayEvaluation
) -> list[PlanSlot]:
    """Every slot to show for a plan, in order.

    That is each slot template of the plan's profile, filled or empty, plus
    any slot number holding entries without a template, named "Slot N".
    """
    names = slot_names(conn, get_plan(conn, plan_id).profile_id)
    evaluated = {slot.slot_no: slot for slot in evaluation.slots}
    return [
        PlanSlot(
            slot_no=slot_no,
            name=names.get(slot_no, f"Slot {slot_no}"),
            slot=evaluated.get(slot_no),
        )
        for slot_no in sorted(names.keys() | evaluated.keys())
    ]


def compare(draft: DayEvaluation, saved: DayEvaluation) -> Macros:
    """How much each day total changed from the saved plan to the draft."""
    return Macros(
        kcal=draft.totals.kcal - saved.totals.kcal,
        protein_g=draft.totals.protein_g - saved.totals.protein_g,
        fat_g=draft.totals.fat_g - saved.totals.fat_g,
        carb_g=draft.totals.carb_g - saved.totals.carb_g,
        fiber_g=draft.totals.fiber_g - saved.totals.fiber_g,
    )


def entry_units(conn: Connection, evaluation: DayEvaluation) -> dict[int, list[str]]:
    """The units each food in the plan can be measured in, keyed by food id."""
    return {
        entry.food_id: units_for(conn, entry.food_id)
        for slot in evaluation.slots
        for entry in slot.entries
    }
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_plans.py tests/test_units.py tests/test_people.py -q`
Expected: PASS

- [ ] **Step 7: Run the whole suite and commit**

Run: `uv run python -m pytest -q`
Expected: PASS, 232 tests, the one known warning

```bash
git add src/yolk/planning/plans.py src/yolk/units.py src/yolk/people.py tests/test_plans.py tests/test_units.py tests/test_people.py
git commit -m "feat: add slot, comparison, unit, and profile helpers for planning pages" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 5: Request guards and HTML error pages

**Files:**
- Modify: `src/yolk/web/app.py` (full replacement below)
- Modify: `src/yolk/web/deps.py`, `src/yolk/web/routes/plans.py`, `src/yolk/web/templates/error.html`
- Modify: `tests/conftest.py`
- Test: `tests/test_web_safety.py` (create)

**Interfaces:**
- Consumes: `get_plan`, `PlanHeader` (Task 4).
- Produces:
  - `yolk.web.app.SAFE_METHODS`
  - `yolk.web.deps.owned_plan(conn, viewer, plan_id, *, status: str | None = None) -> PlanHeader`. It raises `HTTPException(404, "There is no plan N.")` unless the plan exists, belongs to `viewer.person`, and has `status` when one is given.
  - `yolk.web.deps.is_htmx(request) -> bool`
  - `error.html` takes `title` and `message`. With no `title`, it renders the unexpected-error text.
  - The `client` fixture sends `Origin: http://127.0.0.1` on every request.

**Rules (spec §5):**
- Every POST, PUT, PATCH and DELETE must carry an `Origin`, or failing that a `Referer`, whose host is `127.0.0.1` or `localhost`. Anything else gets 403 and the HTML error page titled "Refused".
- Any `HTTPException` renders `error.html` with the status phrase as the title (for example "Not Found"). The detail is shown when it differs from the phrase.
- A request that fails validation (for example `/plans/abc`) renders `error.html` with 422.
- A plan belonging to someone else gets 404.

- [ ] **Step 1: Make the test client send a same-machine Origin**

In `tests/conftest.py`, change the `client` fixture's return to:

```python
    return TestClient(
        create_app(seeded[0]),
        base_url="http://127.0.0.1",
        headers={"origin": "http://127.0.0.1"},
    )
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_web_safety.py`:

```python
from fastapi.testclient import TestClient

from yolk.db.connection import connect
from yolk.people import create_person, create_profile
from yolk.planning.evaluate import create_day_plan
from yolk.web.app import create_app


def _bare_client(path):
    return TestClient(create_app(path), base_url="http://127.0.0.1")


def test_a_post_from_another_site_is_refused(client):
    response = client.post(
        "/person", data={"person_id": 1},
        headers={"origin": "http://evil.example"}, follow_redirects=False,
    )
    assert response.status_code == 403
    assert "Refused" in response.text
    assert "set-cookie" not in response.headers


def test_a_post_with_neither_origin_nor_referer_is_refused(seeded):
    response = _bare_client(seeded[0]).post(
        "/person", data={"person_id": 1}, follow_redirects=False
    )
    assert response.status_code == 403


def test_a_post_with_a_same_machine_referer_is_allowed(seeded):
    response = _bare_client(seeded[0]).post(
        "/person", data={"person_id": 1},
        headers={"referer": "http://localhost:8000/plans"}, follow_redirects=False,
    )
    assert response.status_code == 303


def test_an_unknown_address_gets_the_html_error_page(client):
    response = client.get("/no-such-page")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/html")
    assert "Not Found" in response.text


def test_a_malformed_plan_id_gets_the_html_error_page(client):
    response = client.get("/plans/not-a-number")
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("text/html")


def test_another_persons_plan_is_not_found(client, seeded):
    conn = connect(seeded[0])
    sam = create_person(conn, "Sam")
    profile = create_profile(
        conn, sam, name="rest", effective_on="2026-07-14",
        kcal=2000, fat_pct=40, carb_pct=20, protein_pct=40,
    )
    sam_plan = create_day_plan(conn, sam, profile, name="Sam plan")
    conn.close()
    assert client.get(f"/plans/{sam_plan}").status_code == 404
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_web_safety.py -q`
Expected: FAIL. The foreign-Origin and no-Origin POSTs return 303, the error pages are JSON, and Sam's plan returns 200.

- [ ] **Step 4: Add the dependencies helpers**

In `src/yolk/web/deps.py`, change `from fastapi import Depends, Request` to `from fastapi import Depends, HTTPException, Request`. Add `from yolk.planning.plans import PlanHeader, get_plan` to the imports, then append:

```python
def owned_plan(
    conn: Connection, viewer: Viewer, plan_id: int, *, status: str | None = None
) -> PlanHeader:
    """The plan, if it exists, is the viewer's, and has `status` when given.

    Anything else is a 404, so one person's address can never open another
    person's plan.
    """
    try:
        plan = get_plan(conn, plan_id)
    except LookupError:
        plan = None
    if (
        plan is None
        or plan.person_id != viewer.person.id
        or (status is not None and plan.status != status)
    ):
        raise HTTPException(status_code=404, detail=f"There is no plan {plan_id}.")
    return plan


def is_htmx(request: Request) -> bool:
    """Whether htmx sent this request, and so wants a fragment back."""
    return request.headers.get("hx-request") == "true"
```

- [ ] **Step 5: Use it on the plan page**

In `src/yolk/web/routes/plans.py`, change the import line `from yolk.planning.plans import get_plan, plan_summaries` to `from yolk.planning.plans import plan_summaries`, and `from yolk.web.deps import ConnDep, ViewerDep` to `from yolk.web.deps import ConnDep, ViewerDep, owned_plan`. In `plan_detail`, replace the whole first `try`/`except LookupError` block, from `try:` through its `return templates.TemplateResponse(... status_code=404,)`, with:

```python
    plan = owned_plan(conn, viewer, plan_id)
```

- [ ] **Step 6: Give the error page an explicit title**

Replace `src/yolk/web/templates/error.html` with:

```html
{% extends "base.html" %}
{% block title %}{{ title or "Error" }} · yolk{% endblock %}
{% block content %}
<section class="notice">
  {% if title %}
  <h1>{{ title }}</h1>
  {% if message %}<p>{{ message }}</p>{% endif %}
  {% else %}
  <h1>Something went wrong</h1>
  <p>The details are in the terminal running <code>yolk serve</code>.</p>
  {% endif %}
  <p><a href="/plans">Back to plans</a></p>
</section>
{% endblock %}
```

- [ ] **Step 7: Replace `src/yolk/web/app.py`**

```python
"""The local web app.

create_app() wires routes, static files, the request guards, and the pages
that replace a normal response: "run this command" when the database is not
ready, and the HTML error page for everything else that goes wrong.
"""

from __future__ import annotations

from http import HTTPStatus
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from yolk.config import database_path
from yolk.web.deps import SetupRequired
from yolk.web.routes import foods, people, plans
from yolk.web.templating import templates

STATIC_DIR = Path(__file__).parent / "static"

# Only this machine: refuses other Host headers, which stops DNS rebinding.
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _from_this_app(request: Request) -> bool:
    """Whether a request that changes something came from this app's pages.

    Browsers send Origin with every POST and usually Referer too. A request
    carrying neither is refused rather than trusted.
    """
    source = request.headers.get("origin") or request.headers.get("referer")
    return source is not None and urlsplit(source).hostname in ALLOWED_HOSTS


def create_app(db_path: Path | None = None) -> FastAPI:
    app = FastAPI(title="yolk", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.db_path = db_path if db_path is not None else database_path()
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)

    @app.middleware("http")
    async def refuse_cross_site_changes(request: Request, call_next):
        # Any website can make a browser post to 127.0.0.1. Only this app's
        # own pages may change anything.
        if request.method not in SAFE_METHODS and not _from_this_app(request):
            return templates.TemplateResponse(
                request,
                "error.html",
                {
                    "title": "Refused",
                    "message": "That change did not come from this app, so it "
                    "was refused.",
                },
                status_code=403,
            )
        return await call_next(request)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(plans.router)
    app.include_router(people.router)
    app.include_router(foods.router)

    @app.get("/", include_in_schema=False)
    def home() -> RedirectResponse:
        return RedirectResponse("/plans", status_code=303)

    @app.exception_handler(SetupRequired)
    async def setup_required(request: Request, exc: SetupRequired):
        return templates.TemplateResponse(
            request,
            "setup.html",
            {"message": exc.message, "command": exc.command},
            status_code=503,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        title = HTTPStatus(exc.status_code).phrase
        return templates.TemplateResponse(
            request,
            "error.html",
            {"title": title, "message": None if exc.detail == title else exc.detail},
            status_code=exc.status_code,
        )

    @app.exception_handler(RequestValidationError)
    async def bad_request(request: Request, exc: RequestValidationError):
        return templates.TemplateResponse(
            request,
            "error.html",
            {
                "title": "That didn't make sense",
                "message": "Something in the address or the form wasn't valid.",
            },
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception):
        # Starlette re-raises after this handler responds, so uvicorn still
        # logs the traceback to the console. The page never shows it.
        return templates.TemplateResponse(request, "error.html", {}, status_code=500)

    return app
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_web_safety.py tests/test_web.py tests/test_web_plans.py tests/test_web_people.py -q`
Expected: PASS. `test_an_unknown_plan_is_a_404` still finds "There is no plan 999", which now arrives as the HTTPException's detail.

- [ ] **Step 9: Run the whole suite and commit**

Run: `uv run python -m pytest -q`
Expected: PASS, 238 tests, the one known warning. `grep -rn "execute(" src/yolk/web` prints nothing.

```bash
git add src/yolk/web/app.py src/yolk/web/deps.py src/yolk/web/routes/plans.py src/yolk/web/templates/error.html tests/conftest.py tests/test_web_safety.py
git commit -m "feat: refuse cross-site changes and show HTML error pages" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 6: The plan page shows every slot and bad rows inline

**Files:**
- Modify: `src/yolk/web/routes/plans.py`
- Modify: `src/yolk/web/templates/plans/detail.html`, `plans/_slot.html`, `plans/_totals.html`
- Modify: `src/yolk/web/static/app.css`
- Test: `tests/test_web_plans.py`

**Interfaces:**
- Consumes: `evaluate(..., partial=True)` (Task 2); `plan_slots`, `PlanSlot` (Task 4); `owned_plan` (Task 5); `drafts.start_draft` (Task 3, in tests).
- Produces:
  - `plans/_slot.html` takes `ps` (a `PlanSlot`) in place of `slot`. An entry with `error` shows its message across the five measurement columns, and an empty slot shows "Nothing planned for this meal."
  - `plans/_totals.html` shows "Incomplete: N entry/entries excluded, so these totals are too low." when `evaluation.excluded` is not 0.
  - `GET /plans/{id}` for a draft redirects (303) to `/drafts/{id}`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_web_plans.py`, add `from yolk.people import create_slot` and `from yolk.planning import drafts` to the imports, then append:

```python
def test_an_unknown_unit_shows_on_its_own_row_and_the_rest_still_renders(client, seeded):
    path, plan_id, spec = seeded
    _add_entry_to_seeded_plan(path, plan_id, slot_no=1, unit="handful")
    text = client.get(f"/plans/{plan_id}").text
    assert "handful" in text
    assert spec["slots"][1]["entries"][0]["food"] in text
    assert "Day totals" in text
    assert "Incomplete: 1 entry excluded" in text


def test_an_empty_slot_template_shows_as_nothing_planned(client, seeded):
    path, plan_id, _ = seeded
    conn = connect(path)
    plan = conn.execute(
        "SELECT person_id, profile_id FROM day_plans WHERE id = ?", (plan_id,)
    ).fetchone()
    create_slot(
        conn, plan["person_id"], plan["profile_id"],
        slot_no=7, name="Late snack", time_of_day="21:00",
    )
    conn.close()
    text = client.get(f"/plans/{plan_id}").text
    assert "Late snack" in text
    assert "Nothing planned for this meal." in text


def test_a_draft_opened_as_a_plan_redirects_to_the_draft(client, seeded):
    path, plan_id, _ = seeded
    conn = connect(path)
    draft = drafts.start_draft(conn, plan_id)
    conn.close()
    response = client.get(f"/plans/{draft}", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == f"/drafts/{draft}"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_web_plans.py -q`
Expected: the three new tests FAIL. The page still swaps everything for one error panel, never shows empty templates, and renders drafts.

- [ ] **Step 3: Update the route**

In `src/yolk/web/routes/plans.py`:
- Change the `fastapi.responses` import to `from fastapi.responses import HTMLResponse, RedirectResponse`.
- Change the `yolk.planning.plans` import to `from yolk.planning.plans import plan_slots, plan_summaries`.
- Delete the now-unused imports `from yolk.errors import YolkError` and `from yolk.people import slot_names`.

Replace the whole `plan_detail` function with:

```python
@router.get("/plans/{plan_id}", response_class=HTMLResponse)
def plan_detail(plan_id: int, request: Request, conn: ConnDep, viewer: ViewerDep):
    plan = owned_plan(conn, viewer, plan_id)
    if plan.status == "draft":
        return RedirectResponse(f"/drafts/{plan.id}", status_code=303)
    # partial=True: an entry that cannot be measured shows on its own row,
    # naming the food and unit, instead of hiding the whole plan.
    evaluation = evaluate(conn, plan.id, partial=True)
    return templates.TemplateResponse(
        request,
        "plans/detail.html",
        {
            "viewer": viewer,
            "plan": plan,
            "evaluation": evaluation,
            "slots": plan_slots(conn, plan.id, evaluation),
        },
    )
```

- [ ] **Step 4: Update the templates**

Replace `src/yolk/web/templates/plans/detail.html` with:

```html
{% extends "base.html" %}
{% block title %}{{ plan.name }} · yolk{% endblock %}
{% block content %}
<h1>{{ plan.name }}</h1>
<p class="muted">Profile: {{ plan.profile_name }}</p>
{% include "plans/_totals.html" %}
{% for ps in slots %}
{% include "plans/_slot.html" %}
{% endfor %}
{% endblock %}
```

Replace `src/yolk/web/templates/plans/_slot.html` with:

```html
{# Needs: ps (PlanSlot). #}
<section class="slot" id="slot-{{ ps.slot_no }}">
  <h2>{{ ps.name }}</h2>
  {% if ps.slot and ps.slot.entries %}
  <table>
    <thead>
      <tr>
        <th>Food</th><th class="num">Amount</th><th class="num">Grams</th>
        <th class="num">kcal</th><th class="num">Protein</th>
        <th class="num">Fat</th><th class="num">Carbs</th>
      </tr>
    </thead>
    <tbody>
    {% for entry in ps.slot.entries %}
      <tr{% if entry.error %} class="has-error"{% endif %}>
        <td>{{ entry.food_name }}</td>
        <td class="num">{{ "%g"|format(entry.qty) }} {{ entry.unit }}</td>
        {% if entry.error %}
        <td colspan="5" class="entry-error">{{ entry.error }}</td>
        {% else %}
        <td class="num">{{ "%.0f"|format(entry.grams) }}</td>
        <td class="num">{{ "%.0f"|format(entry.macros.kcal) }}</td>
        <td class="num">{{ "%.1f"|format(entry.macros.protein_g) }}</td>
        <td class="num">{{ "%.1f"|format(entry.macros.fat_g) }}</td>
        <td class="num">{{ "%.1f"|format(entry.macros.carb_g) }}</td>
        {% endif %}
      </tr>
    {% endfor %}
    </tbody>
    <tfoot>
      <tr>
        <td colspan="3">Slot total</td>
        <td class="num">{{ "%.0f"|format(ps.slot.totals.kcal) }}</td>
        <td class="num">{{ "%.1f"|format(ps.slot.totals.protein_g) }}</td>
        <td class="num">{{ "%.1f"|format(ps.slot.totals.fat_g) }}</td>
        <td class="num">{{ "%.1f"|format(ps.slot.totals.carb_g) }}</td>
      </tr>
    </tfoot>
  </table>
  {% else %}
  <p class="muted">Nothing planned for this meal.</p>
  {% endif %}
</section>
```

In `src/yolk/web/templates/plans/_totals.html`, insert directly after the line `<h2>Day totals</h2>`:

```html
  {% if evaluation.excluded %}
  <p class="entry-error">Incomplete: {{ evaluation.excluded }} {{ "entry" if evaluation.excluded == 1 else "entries" }} excluded, so these totals are too low.</p>
  {% endif %}
```

- [ ] **Step 5: Style error rows**

Append to `src/yolk/web/static/app.css`:

```css
.entry-error { color: var(--fail); }
tr.has-error td:first-child { box-shadow: inset 3px 0 0 var(--fail); }
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_web_plans.py -q`
Expected: PASS

- [ ] **Step 7: Run the whole suite and commit**

Run: `uv run python -m pytest -q`
Expected: PASS, 241 tests, the one known warning

```bash
git add src/yolk/web/routes/plans.py src/yolk/web/templates/plans src/yolk/web/static/app.css tests/test_web_plans.py
git commit -m "feat: show every meal slot and unmeasurable entries on their own rows" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 7: Draft pages, New plan, and saving

**Files:**
- Create: `src/yolk/web/routes/drafts.py`, `src/yolk/web/templates/drafts/detail.html`
- Modify: `src/yolk/web/routes/plans.py` (full replacement below), `src/yolk/web/app.py`
- Modify: `src/yolk/web/templates/plans/list.html`, `plans/detail.html`, `plans/_totals.html`, `src/yolk/web/static/app.css`
- Test: `tests/test_web_drafts.py` (create)

**Interfaces:**
- Consumes: `drafts.*` (Task 3); `compare`, `draft_summaries`, `get_plan`, `plan_slots`, `PlanHeader` (Task 4); `current_profiles` (Task 4); `owned_plan` (Task 5).
- Produces:
  - Routes: `POST /plans` (name, profile_id) → 303 `/drafts/{id}`; `POST /plans/{id}/draft` → 303 `/drafts/{id}`; `GET /drafts/{id}`; `POST /drafts/{id}/save-over` → 303 `/plans/{parent}`; `POST /drafts/{id}/save-as-new` (name) → 303 `/plans/{id}`; `POST /drafts/{id}/discard` → 303 to the parent plan or `/plans`.
  - `yolk.web.routes.drafts.draft_context(conn, viewer, draft, **extra) -> dict`, the context for the draft page and its partials: `viewer`, `draft`, `parent`, `evaluation`, `vs`, `slots`, plus `extra`. Task 8 extends it.
  - `plans/_totals.html` accepts an optional `vs` (a `Macros`) and then adds a "vs saved" column.
  - Failures render the same page with status 422 and the message as `form_error`. These include a taken or empty name, a draft that cannot be measured, and save-over on a blank draft.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_web_drafts.py`:

```python
from yolk.db.connection import connect
from yolk.people import create_person, create_profile
from yolk.planning import drafts
from yolk.planning.evaluate import evaluate


def _with_conn(path, work):
    conn = connect(path)
    try:
        return work(conn)
    finally:
        conn.close()


def _start_draft(client, plan_id) -> int:
    response = client.post(f"/plans/{plan_id}/draft", follow_redirects=False)
    assert response.status_code == 303
    return int(response.headers["location"].rsplit("/", 1)[1])


def _profile_id(path, plan_id):
    return _with_conn(path, lambda c: c.execute(
        "SELECT profile_id FROM day_plans WHERE id = ?", (plan_id,)
    ).fetchone()["profile_id"])


def _new_plan(client, path, plan_id, name="Rest day"):
    return client.post(
        "/plans", data={"name": name, "profile_id": _profile_id(path, plan_id)},
        follow_redirects=False,
    )


def _double_first_entry(path, draft):
    def work(conn):
        entry = conn.execute(
            "SELECT id, qty, unit FROM day_plan_entries WHERE day_plan_id = ? "
            "ORDER BY slot_no, sort_order, id", (draft,),
        ).fetchone()
        drafts.update_entry(conn, entry["id"], qty=entry["qty"] * 2, unit=entry["unit"])
        return evaluate(conn, draft).totals
    return _with_conn(path, work)


def _totals(path, plan_id):
    return _with_conn(path, lambda c: evaluate(c, plan_id).totals)


def test_edit_or_copy_opens_a_draft_of_the_plan(client, seeded):
    _, plan_id, spec = seeded
    assert 'action="/plans/%d/draft"' % plan_id in client.get(f"/plans/{plan_id}").text
    draft = _start_draft(client, plan_id)
    text = client.get(f"/drafts/{draft}").text
    assert f"{spec['plan_name']} (draft)" in text
    assert "Save over" in text
    assert spec["slots"][0]["entries"][0]["food"] in text


def test_edit_twice_opens_the_same_draft(client, seeded):
    _, plan_id, _ = seeded
    assert _start_draft(client, plan_id) == _start_draft(client, plan_id)


def test_new_plan_starts_a_blank_draft_with_every_slot(client, seeded):
    path, plan_id, spec = seeded
    response = _new_plan(client, path, plan_id)
    assert response.status_code == 303
    text = client.get(response.headers["location"]).text
    for slot in spec["slots"]:
        assert slot["name"] in text
    assert text.count("Nothing planned for this meal.") == len(spec["slots"])
    assert "Save over" not in text


def test_new_plan_with_a_taken_name_says_so(client, seeded):
    path, plan_id, spec = seeded
    response = _new_plan(client, path, plan_id, name=spec["plan_name"])
    assert response.status_code == 422
    assert "You already have a plan called" in response.text


def test_the_plan_list_shows_drafts_in_progress(client, seeded):
    _, plan_id, _ = seeded
    draft = _start_draft(client, plan_id)
    text = client.get("/plans").text
    assert "In progress" in text
    assert f'href="/drafts/{draft}"' in text


def test_save_as_new_turns_a_blank_draft_into_a_saved_plan(client, seeded):
    path, plan_id, _ = seeded
    location = _new_plan(client, path, plan_id).headers["location"]
    draft = int(location.rsplit("/", 1)[1])

    def add_pork(conn):
        food = conn.execute("SELECT id FROM foods WHERE name = 'Pork Rinds'").fetchone()["id"]
        drafts.add_entry_to_draft(conn, draft, slot_no=1, food_id=food, qty=50, unit="g")
    _with_conn(path, add_pork)

    response = client.post(
        f"/drafts/{draft}/save-as-new", data={"name": "Rest day"}, follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == f"/plans/{draft}"
    listing = client.get("/plans").text
    assert "Rest day" in listing
    assert "In progress" not in listing


def test_save_over_replaces_the_saved_plan(client, seeded):
    path, plan_id, _ = seeded
    draft = _start_draft(client, plan_id)
    draft_totals = _double_first_entry(path, draft)
    response = client.post(f"/drafts/{draft}/save-over", follow_redirects=False)
    assert response.headers["location"] == f"/plans/{plan_id}"
    assert _totals(path, plan_id) == draft_totals


def test_discard_leaves_the_saved_plan_exactly_as_it_was(client, seeded):
    path, plan_id, _ = seeded
    before = _totals(path, plan_id)
    draft = _start_draft(client, plan_id)
    _double_first_entry(path, draft)
    response = client.post(f"/drafts/{draft}/discard", follow_redirects=False)
    assert response.headers["location"] == f"/plans/{plan_id}"
    assert _totals(path, plan_id) == before
    assert client.get(f"/drafts/{draft}").status_code == 404


def test_a_draft_that_cannot_be_measured_cannot_be_saved(client, seeded):
    path, plan_id, _ = seeded
    draft = _start_draft(client, plan_id)

    def add_bad(conn):
        food = conn.execute("SELECT id FROM foods WHERE name = 'Pork Rinds'").fetchone()["id"]
        drafts.add_entry_to_draft(conn, draft, slot_no=1, food_id=food, qty=1, unit="handful")
    _with_conn(path, add_bad)

    response = client.post(f"/drafts/{draft}/save-over", follow_redirects=False)
    assert response.status_code == 422
    assert "handful" in response.text
    assert client.get(f"/drafts/{draft}").status_code == 200


def test_the_draft_page_shows_the_change_against_the_saved_plan(client, seeded):
    path, plan_id, _ = seeded
    draft = _start_draft(client, plan_id)
    _double_first_entry(path, draft)  # Buff Chick Coffee, 80 kcal, doubled
    text = client.get(f"/drafts/{draft}").text
    assert "vs saved" in text
    assert "+80" in text


def test_another_persons_draft_is_not_found(client, seeded):
    def sams_draft(conn):
        sam = create_person(conn, "Sam")
        profile = create_profile(
            conn, sam, name="rest", effective_on="2026-07-14",
            kcal=2000, fat_pct=40, carb_pct=20, protein_pct=40,
        )
        return drafts.start_blank_draft(conn, sam, profile, "Sam plan")
    draft = _with_conn(seeded[0], sams_draft)
    assert client.get(f"/drafts/{draft}").status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_web_drafts.py -q`
Expected: FAIL. `POST /plans/{id}/draft`, `POST /plans` and `/drafts/...` return 404 or 405.

- [ ] **Step 3: Replace `src/yolk/web/routes/plans.py`**

```python
"""Plan pages: the list, one plan, and starting drafts from either."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from yolk.db import Connection
from yolk.errors import YolkError
from yolk.people import current_profiles
from yolk.planning import drafts
from yolk.planning.evaluate import evaluate
from yolk.planning.plans import draft_summaries, plan_slots, plan_summaries
from yolk.web.deps import ConnDep, Viewer, ViewerDep, owned_plan
from yolk.web.templating import templates

router = APIRouter()


def _plan_list(
    request: Request, conn: Connection, viewer: Viewer, *, status_code: int = 200, **extra
):
    return templates.TemplateResponse(
        request,
        "plans/list.html",
        {
            "viewer": viewer,
            "plans": plan_summaries(conn, viewer.person.id),
            "drafts": draft_summaries(conn, viewer.person.id),
            "profiles": current_profiles(
                conn, viewer.person.id, date.today().isoformat()
            ),
            **extra,
        },
        status_code=status_code,
    )


@router.get("/plans", response_class=HTMLResponse)
def plan_list(request: Request, conn: ConnDep, viewer: ViewerDep):
    return _plan_list(request, conn, viewer)


@router.post("/plans")
def new_plan(
    request: Request,
    conn: ConnDep,
    viewer: ViewerDep,
    profile_id: Annotated[int, Form()],
    name: Annotated[str, Form()] = "",
):
    try:
        draft_id = drafts.start_blank_draft(conn, viewer.person.id, profile_id, name)
    except LookupError:
        raise HTTPException(status_code=404, detail=f"There is no profile {profile_id}.")
    except (YolkError, ValueError) as exc:
        return _plan_list(
            request, conn, viewer, status_code=422, form_error=str(exc), form_name=name
        )
    return RedirectResponse(f"/drafts/{draft_id}", status_code=303)


@router.get("/plans/{plan_id}", response_class=HTMLResponse)
def plan_detail(plan_id: int, request: Request, conn: ConnDep, viewer: ViewerDep):
    plan = owned_plan(conn, viewer, plan_id)
    if plan.status == "draft":
        return RedirectResponse(f"/drafts/{plan.id}", status_code=303)
    # partial=True: an entry that cannot be measured shows on its own row,
    # naming the food and unit, instead of hiding the whole plan.
    evaluation = evaluate(conn, plan.id, partial=True)
    return templates.TemplateResponse(
        request,
        "plans/detail.html",
        {
            "viewer": viewer,
            "plan": plan,
            "evaluation": evaluation,
            "slots": plan_slots(conn, plan.id, evaluation),
        },
    )


@router.post("/plans/{plan_id}/draft")
def edit_plan(plan_id: int, conn: ConnDep, viewer: ViewerDep):
    plan = owned_plan(conn, viewer, plan_id)
    if plan.status == "draft":
        return RedirectResponse(f"/drafts/{plan.id}", status_code=303)
    try:
        draft_id = drafts.start_draft(conn, plan.id)
    except YolkError as exc:
        # A saved plan already uses the draft's name, "<name> (draft)".
        raise HTTPException(status_code=409, detail=str(exc))
    return RedirectResponse(f"/drafts/{draft_id}", status_code=303)
```

- [ ] **Step 4: Add the drafts routes**

Create `src/yolk/web/routes/drafts.py`:

```python
"""Draft pages: look at a draft, then save it over its plan, save it as new,
or discard it."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from yolk.db import Connection
from yolk.errors import YolkError
from yolk.planning import drafts
from yolk.planning.evaluate import evaluate
from yolk.planning.plans import PlanHeader, compare, get_plan, plan_slots
from yolk.web.deps import ConnDep, Viewer, ViewerDep, owned_plan
from yolk.web.templating import templates

router = APIRouter()


def draft_context(
    conn: Connection, viewer: Viewer, draft: PlanHeader, **extra
) -> dict:
    """Everything the draft page and its partials need."""
    evaluation = evaluate(conn, draft.id, partial=True)
    parent = (
        None if draft.parent_plan_id is None else get_plan(conn, draft.parent_plan_id)
    )
    vs = (
        None
        if parent is None
        else compare(evaluation, evaluate(conn, parent.id, partial=True))
    )
    return {
        "viewer": viewer,
        "draft": draft,
        "parent": parent,
        "evaluation": evaluation,
        "vs": vs,
        "slots": plan_slots(conn, draft.id, evaluation),
        **extra,
    }


def _draft_page(
    request: Request,
    conn: Connection,
    viewer: Viewer,
    draft: PlanHeader,
    *,
    status_code: int = 200,
    **extra,
):
    return templates.TemplateResponse(
        request,
        "drafts/detail.html",
        draft_context(conn, viewer, draft, **extra),
        status_code=status_code,
    )


@router.get("/drafts/{draft_id}", response_class=HTMLResponse)
def draft_page(draft_id: int, request: Request, conn: ConnDep, viewer: ViewerDep):
    draft = owned_plan(conn, viewer, draft_id, status="draft")
    return _draft_page(request, conn, viewer, draft)


@router.post("/drafts/{draft_id}/save-over")
def save_draft_over(draft_id: int, request: Request, conn: ConnDep, viewer: ViewerDep):
    draft = owned_plan(conn, viewer, draft_id, status="draft")
    try:
        drafts.save_over(conn, draft.id)
    except (YolkError, ValueError) as exc:
        return _draft_page(
            request, conn, viewer, draft, status_code=422, form_error=str(exc)
        )
    return RedirectResponse(f"/plans/{draft.parent_plan_id}", status_code=303)


@router.post("/drafts/{draft_id}/save-as-new")
def save_draft_as_new(
    draft_id: int,
    request: Request,
    conn: ConnDep,
    viewer: ViewerDep,
    name: Annotated[str, Form()] = "",
):
    draft = owned_plan(conn, viewer, draft_id, status="draft")
    try:
        plan_id = drafts.save_as_new(conn, draft.id, name=name)
    except (YolkError, ValueError) as exc:
        return _draft_page(
            request, conn, viewer, draft, status_code=422, form_error=str(exc)
        )
    return RedirectResponse(f"/plans/{plan_id}", status_code=303)


@router.post("/drafts/{draft_id}/discard")
def discard_draft(draft_id: int, conn: ConnDep, viewer: ViewerDep):
    draft = owned_plan(conn, viewer, draft_id, status="draft")
    drafts.discard_draft(conn, draft.id)
    back = f"/plans/{draft.parent_plan_id}" if draft.parent_plan_id else "/plans"
    return RedirectResponse(back, status_code=303)
```

In `src/yolk/web/app.py`, change `from yolk.web.routes import foods, people, plans` to `from yolk.web.routes import drafts, foods, people, plans`, and after `app.include_router(foods.router)` add `app.include_router(drafts.router)`.

- [ ] **Step 5: Write the templates**

Create `src/yolk/web/templates/drafts/detail.html`:

```html
{% extends "base.html" %}
{% block title %}{{ draft.name }} · yolk{% endblock %}
{% block content %}
<h1>{{ draft.name }}</h1>
<p class="muted">Draft · Profile: {{ draft.profile_name }}{% if parent %} · from <a href="/plans/{{ parent.id }}">{{ parent.name }}</a>{% endif %}</p>
{% if form_error %}<p class="notice error-panel">{{ form_error }}</p>{% endif %}
<div class="draft-actions">
  {% if parent %}
  <form method="post" action="/drafts/{{ draft.id }}/save-over"
        data-confirm="Replace “{{ parent.name }}” with this draft?"
        onsubmit="return confirm(this.dataset.confirm)">
    <button type="submit">Save over “{{ parent.name }}”</button>
  </form>
  {% endif %}
  <form class="save-as" method="post" action="/drafts/{{ draft.id }}/save-as-new">
    <label>Name <input name="name" required value="{{ '' if parent else draft.name }}"></label>
    <button type="submit">Save as new</button>
  </form>
  <form method="post" action="/drafts/{{ draft.id }}/discard"
        data-confirm="Discard this draft? Its changes will be lost."
        onsubmit="return confirm(this.dataset.confirm)">
    <button type="submit">Discard</button>
  </form>
</div>
{% include "plans/_totals.html" %}
{% for ps in slots %}
{% include "plans/_slot.html" %}
{% endfor %}
{% endblock %}
```

The confirmation text sits in an HTML attribute, which autoescaping makes safe, and is read through `dataset`. A plan name is never pasted into JavaScript source.

Replace `src/yolk/web/templates/plans/list.html` with:

```html
{% extends "base.html" %}
{% block title %}Plans · yolk{% endblock %}
{% block content %}
<h1>{{ viewer.person.name }}'s plans</h1>
{% if drafts %}
<h2>In progress</h2>
<table class="plans">
  <thead><tr><th>Draft</th><th>Profile</th></tr></thead>
  <tbody>
  {% for d in drafts %}
    <tr><td><a href="/drafts/{{ d.id }}">{{ d.name }}</a></td><td>{{ d.profile_name }}</td></tr>
  {% endfor %}
  </tbody>
</table>
<h2>Saved</h2>
{% endif %}
{% if plans %}
<table class="plans">
  <thead><tr><th>Plan</th><th>Profile</th><th>Day</th></tr></thead>
  <tbody>
  {% for plan in plans %}
    <tr>
      <td><a href="/plans/{{ plan.id }}">{{ plan.name }}</a></td>
      <td>{{ plan.profile_name }}</td>
      <td>
        {% if plan.error %}<span class="mark error" title="{{ plan.error }}">Can't evaluate</span>
        {% elif plan.ok %}<span class="mark pass">Within tolerance</span>
        {% else %}<span class="mark fail">Outside tolerance</span>{% endif %}
      </td>
    </tr>
  {% endfor %}
  </tbody>
</table>
{% else %}
<p>No active plans yet.</p>
{% endif %}
<section class="notice new-plan">
  <h2>New plan</h2>
  {% if form_error %}<p class="entry-error">{{ form_error }}</p>{% endif %}
  {% if profiles %}
  <form class="new-plan-form" method="post" action="/plans">
    <label>Name <input name="name" required value="{{ form_name or '' }}"></label>
    <label>Profile
      <select name="profile_id">
        {% for p in profiles %}<option value="{{ p.id }}">{{ p.name }} · {{ "%.0f"|format(p.kcal) }} kcal</option>{% endfor %}
      </select>
    </label>
    <button type="submit">Start</button>
  </form>
  {% else %}
  <p class="muted">A plan is measured against a macro profile, and there isn't one yet.</p>
  {% endif %}
</section>
{% endblock %}
```

In `src/yolk/web/templates/plans/detail.html`, insert after the `<p class="muted">Profile: …</p>` line:

```html
<form class="plan-actions" method="post" action="/plans/{{ plan.id }}/draft">
  <button type="submit">Edit or copy</button>
</form>
```

In `src/yolk/web/templates/plans/_totals.html`:
- Change the first comment line to `{# Needs: evaluation (DayEvaluation). Optional: vs (Macros, draft minus saved plan). Fat and carb marks judge share of calories, not grams. #}`.
- In the header row, insert `{% if vs %}<th class="num">vs saved</th>{% endif %}` directly before the final empty `<th></th>`.
- In the body row, insert directly before the `<td>` that holds the Within/Outside mark:

```html
        {% if vs %}<td class="num">{{ delta_fmt|format(vs|attr(field)) }}{{ suffix }}</td>{% endif %}
```

- [ ] **Step 6: Style the controls**

Append to `src/yolk/web/static/app.css`:

```css
button, .button {
  display: inline-block;
  font: inherit;
  padding: 0.35rem 0.8rem;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
  color: var(--text);
  text-decoration: none;
  cursor: pointer;
}
button:hover, .button:hover { border-color: var(--accent); }

input, select {
  font: inherit;
  color: var(--text);
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 0.3rem 0.5rem;
}

.draft-actions, .new-plan-form {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  align-items: flex-end;
  margin-bottom: 1rem;
}
.draft-actions form, .save-as { display: flex; gap: 0.5rem; align-items: center; }
.new-plan-form label, .save-as label { display: flex; gap: 0.4rem; align-items: center; }
.plan-actions { margin-bottom: 1rem; }
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_web_drafts.py tests/test_web.py tests/test_web_plans.py -q`
Expected: PASS

- [ ] **Step 8: Run the whole suite and commit**

Run: `uv run python -m pytest -q`
Expected: PASS, 252 tests, the one known warning. `grep -rn "execute(" src/yolk/web` prints nothing.

```bash
git add src/yolk/web/routes/plans.py src/yolk/web/routes/drafts.py src/yolk/web/app.py src/yolk/web/templates src/yolk/web/static/app.css tests/test_web_drafts.py
git commit -m "feat: start, review, save, and discard drafts in the browser" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 8: Editing meals in a draft

**Files:**
- Create: `src/yolk/web/static/htmx.min.js` (downloaded; see Step 1)
- Create: `src/yolk/web/templates/drafts/_changed.html`, `foods/_picker.html`, `foods/pick.html`
- Modify: `src/yolk/web/routes/drafts.py` (full replacement below), `src/yolk/web/routes/foods.py`
- Modify: `src/yolk/web/templates/base.html`, `plans/_slot.html` (full replacement below), `plans/_totals.html`, `foods/_results.html`
- Modify: `src/yolk/web/static/app.css`
- Test: `tests/test_web_editing.py` (create)

**Interfaces:**
- Consumes:
  - From Task 3: `drafts.add_entry_to_draft`, `update_entry`, `replace_entry_food`, `remove_entry`, `parse_amount`, `locate_entry`.
  - From Task 4: `entry_units`, `units.default_portion`.
  - From Task 5: `owned_plan`, `is_htmx`.
  - From Task 7: `draft_context`.
  - From Part A: `search_library`.
- Produces:
  - Routes:
    - `POST /drafts/{id}/entries` (slot_no, food_id)
    - `POST /drafts/{id}/entries/{entry_id}` (qty, unit)
    - `POST /drafts/{id}/entries/{entry_id}/swap` (food_id)
    - `POST /drafts/{id}/entries/{entry_id}/remove`
    - `GET /foods/search?draft=&slot=&q=&entry=`
  - With `HX-Request: true`, each edit answers 200 with `drafts/_changed.html`: the changed slot section, plus the totals section with `hx-swap-oob="true"`. Without it, each edit answers 303 to `/drafts/{id}#slot-N`.
  - A bad amount answers with the slot (htmx), or with the whole draft page at 422 (plain post). Either way the message appears on that entry's row, and nothing is written.
  - `foods/_results.html` accepts an optional `pick` dict: `action`, `label`, `fields`, and `target` (a CSS selector, or `None` for a plain post). With it, each row gets a button that posts `food_id` plus `fields` to `action`. `/foods` passes no `pick` and is unchanged.

**Behaviour:**
- **Adding or swapping.** Adding a food uses `default_portion`: one of its usual unit, or 100 g. Swapping keeps the entry's place but resets the amount to the new food's `default_portion`.
- **Changing the unit.** This keeps the typed number. "1 cup" becomes "1 g", and the person then adjusts the amount.
- **Removing the last entry of a templated slot.** The slot stays and reads "Nothing planned for this meal."
- **Removing the last entry of a slot without a template.** The slot disappears, so the htmx answer is an empty body with `HX-Refresh: true`, which tells htmx to reload the page.

- [ ] **Step 1: Vendor htmx**

The controller asks the user before this download. It is htmx 2.0.11, about 50 KB, from the jsDelivr npm mirror.

```bash
curl -fsSL https://cdn.jsdelivr.net/npm/htmx.org@2.0.11/dist/htmx.min.js -o src/yolk/web/static/htmx.min.js
```

Check it: `wc -c src/yolk/web/static/htmx.min.js` prints roughly 50000, and `head -c 300 src/yolk/web/static/htmx.min.js` contains `htmx`. If the download fails, stop and report BLOCKED. Do not substitute another version or source.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_web_editing.py`:

```python
from yolk.db.connection import connect

HTMX = {"HX-Request": "true"}


def _with_conn(path, work):
    conn = connect(path)
    try:
        return work(conn)
    finally:
        conn.close()


def _draft_and_first_entry(client, seeded):
    path, plan_id, _ = seeded
    response = client.post(f"/plans/{plan_id}/draft", follow_redirects=False)
    draft = int(response.headers["location"].rsplit("/", 1)[1])
    entry = _with_conn(path, lambda c: dict(c.execute(
        "SELECT id, slot_no, qty, unit, food_id FROM day_plan_entries "
        "WHERE day_plan_id = ? ORDER BY slot_no, sort_order, id", (draft,),
    ).fetchone()))
    return path, draft, entry


def _entry(path, entry_id):
    row = _with_conn(path, lambda c: c.execute(
        "SELECT food_id, qty, unit FROM day_plan_entries WHERE id = ?", (entry_id,)
    ).fetchone())
    return None if row is None else dict(row)


def _food(path, name):
    return _with_conn(path, lambda c: c.execute(
        "SELECT id FROM foods WHERE name = ?", (name,)
    ).fetchone()["id"])


def test_changing_an_amount_answers_with_the_slot_and_totals(client, seeded):
    path, draft, entry = _draft_and_first_entry(client, seeded)
    response = client.post(
        f"/drafts/{draft}/entries/{entry['id']}",
        data={"qty": "2", "unit": entry["unit"]}, headers=HTMX,
    )
    assert response.status_code == 200
    assert f'id="slot-{entry["slot_no"]}"' in response.text
    assert 'hx-swap-oob="true"' in response.text
    assert _entry(path, entry["id"])["qty"] == 2


def test_changing_an_amount_without_htmx_redirects_back(client, seeded):
    path, draft, entry = _draft_and_first_entry(client, seeded)
    response = client.post(
        f"/drafts/{draft}/entries/{entry['id']}",
        data={"qty": "3", "unit": entry["unit"]}, follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"].startswith(f"/drafts/{draft}")
    assert _entry(path, entry["id"])["qty"] == 3


def test_a_bad_amount_shows_on_its_row_and_changes_nothing(client, seeded):
    path, draft, entry = _draft_and_first_entry(client, seeded)
    url = f"/drafts/{draft}/entries/{entry['id']}"
    response = client.post(url, data={"qty": "abc", "unit": entry["unit"]}, headers=HTMX)
    assert response.status_code == 200
    assert "Amount must be a number" in response.text
    response = client.post(url, data={"qty": "0", "unit": entry["unit"]}, headers=HTMX)
    assert "greater than 0" in response.text
    assert _entry(path, entry["id"])["qty"] == entry["qty"]


def test_a_bad_amount_without_htmx_shows_the_page_with_the_message(client, seeded):
    path, draft, entry = _draft_and_first_entry(client, seeded)
    response = client.post(
        f"/drafts/{draft}/entries/{entry['id']}",
        data={"qty": "", "unit": entry["unit"]}, follow_redirects=False,
    )
    assert response.status_code == 422
    assert "Amount must be a number" in response.text


def test_remove_takes_the_entry_out(client, seeded):
    path, draft, entry = _draft_and_first_entry(client, seeded)
    response = client.post(f"/drafts/{draft}/entries/{entry['id']}/remove", headers=HTMX)
    assert response.status_code == 200
    assert _entry(path, entry["id"]) is None


def test_adding_a_food_uses_its_usual_portion(client, seeded):
    path, draft, _ = _draft_and_first_entry(client, seeded)
    for name, expected in [("Buff Chick Coffee", (1, "packet")), ("Pork Rinds", (100, "g"))]:
        response = client.post(
            f"/drafts/{draft}/entries",
            data={"slot_no": "1", "food_id": str(_food(path, name))}, headers=HTMX,
        )
        assert response.status_code == 200
        added = _with_conn(path, lambda c: c.execute(
            "SELECT qty, unit FROM day_plan_entries WHERE day_plan_id = ? "
            "ORDER BY id DESC", (draft,),
        ).fetchone())
        assert (added["qty"], added["unit"]) == expected


def test_swap_replaces_the_food_in_place(client, seeded):
    path, draft, entry = _draft_and_first_entry(client, seeded)
    pork = _food(path, "Pork Rinds")
    client.post(
        f"/drafts/{draft}/entries/{entry['id']}/swap",
        data={"food_id": str(pork)}, headers=HTMX,
    )
    assert _entry(path, entry["id"]) == {"food_id": pork, "qty": 100, "unit": "g"}


def test_the_picker_lists_foods_with_add_buttons(client, seeded):
    _, draft, _ = _draft_and_first_entry(client, seeded)
    response = client.get(
        "/foods/search", params={"draft": draft, "slot": 1, "q": "pork"}, headers=HTMX
    )
    assert response.status_code == 200
    assert "Pork Rinds" in response.text
    assert f'action="/drafts/{draft}/entries"' in response.text
    assert 'name="slot_no" value="1"' in response.text
    assert "hx-post=" in response.text
    assert "<html" not in response.text


def test_the_picker_without_htmx_is_a_full_page_of_plain_forms(client, seeded):
    _, draft, _ = _draft_and_first_entry(client, seeded)
    response = client.get("/foods/search", params={"draft": draft, "slot": 1})
    assert "<html" in response.text
    assert "Back to" in response.text
    assert f'action="/drafts/{draft}/entries"' in response.text
    assert "hx-post=" not in response.text


def test_an_entry_from_another_plan_is_not_found(client, seeded):
    path, plan_id, _ = seeded
    _, draft, _ = _draft_and_first_entry(client, seeded)
    saved_entry = _with_conn(path, lambda c: c.execute(
        "SELECT id FROM day_plan_entries WHERE day_plan_id = ?", (plan_id,)
    ).fetchone()["id"])
    response = client.post(
        f"/drafts/{draft}/entries/{saved_entry}/remove", follow_redirects=False
    )
    assert response.status_code == 404


def test_htmx_is_served_from_the_app_itself(client):
    assert '<script src="/static/htmx.min.js"' in client.get("/plans").text
    script = client.get("/static/htmx.min.js")
    assert script.status_code == 200
    assert "htmx" in script.text[:2000]
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_web_editing.py -q`
Expected: FAIL. The edit routes return 405 or 404, there is no picker route, and `base.html` does not load htmx. `test_an_entry_from_another_plan_is_not_found` may already pass through FastAPI's own 404.

- [ ] **Step 4: Replace `src/yolk/web/routes/drafts.py`**

```python
"""Draft pages and every edit to a draft.

Every edit has one shape: change the draft through the library, re-evaluate,
then answer with the changed slot and the day totals (htmx), or redirect back
to the draft page (a plain form post).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from yolk.db import Connection
from yolk.errors import YolkError
from yolk.planning import drafts
from yolk.planning.evaluate import evaluate
from yolk.planning.plans import PlanHeader, compare, entry_units, get_plan, plan_slots
from yolk.units import default_portion
from yolk.web.deps import ConnDep, Viewer, ViewerDep, is_htmx, owned_plan
from yolk.web.templating import templates

router = APIRouter()


def draft_context(
    conn: Connection, viewer: Viewer, draft: PlanHeader, **extra
) -> dict:
    """Everything the draft page and its partials need."""
    evaluation = evaluate(conn, draft.id, partial=True)
    parent = (
        None if draft.parent_plan_id is None else get_plan(conn, draft.parent_plan_id)
    )
    vs = (
        None
        if parent is None
        else compare(evaluation, evaluate(conn, parent.id, partial=True))
    )
    return {
        "viewer": viewer,
        "draft": draft,
        "parent": parent,
        "evaluation": evaluation,
        "vs": vs,
        "slots": plan_slots(conn, draft.id, evaluation),
        "entry_units": entry_units(conn, evaluation),
        **extra,
    }


def _draft_page(
    request: Request,
    conn: Connection,
    viewer: Viewer,
    draft: PlanHeader,
    *,
    status_code: int = 200,
    **extra,
):
    return templates.TemplateResponse(
        request,
        "drafts/detail.html",
        draft_context(conn, viewer, draft, **extra),
        status_code=status_code,
    )


def _slot_of_entry(conn: Connection, draft: PlanHeader, entry_id: int) -> int:
    """The entry's slot, once it is known to belong to this draft."""
    try:
        where = drafts.locate_entry(conn, entry_id)
    except LookupError:
        where = None
    if where is None or where.plan_id != draft.id:
        raise HTTPException(
            status_code=404, detail=f"There is no entry {entry_id} in this draft."
        )
    return where.slot_no


def _after_edit(
    request: Request,
    conn: Connection,
    viewer: Viewer,
    draft: PlanHeader,
    slot_no: int,
    entry_errors: dict[int, str] | None = None,
):
    """Answer an edit: the changed slot and the totals for htmx, else the page."""
    if not is_htmx(request):
        if entry_errors:
            return _draft_page(
                request, conn, viewer, draft, status_code=422, entry_errors=entry_errors
            )
        return RedirectResponse(f"/drafts/{draft.id}#slot-{slot_no}", status_code=303)
    context = draft_context(conn, viewer, draft, entry_errors=entry_errors or {})
    changed = [ps for ps in context["slots"] if ps.slot_no == slot_no]
    if not changed:
        # The last entry of a slot with no template is gone, and the slot with it.
        return HTMLResponse("", headers={"HX-Refresh": "true"})
    return templates.TemplateResponse(
        request, "drafts/_changed.html", {**context, "ps": changed[0]}
    )


@router.get("/drafts/{draft_id}", response_class=HTMLResponse)
def draft_page(draft_id: int, request: Request, conn: ConnDep, viewer: ViewerDep):
    draft = owned_plan(conn, viewer, draft_id, status="draft")
    return _draft_page(request, conn, viewer, draft)


@router.post("/drafts/{draft_id}/entries")
def add_food(
    draft_id: int,
    request: Request,
    conn: ConnDep,
    viewer: ViewerDep,
    slot_no: Annotated[int, Form()],
    food_id: Annotated[int, Form()],
):
    draft = owned_plan(conn, viewer, draft_id, status="draft")
    qty, unit = default_portion(conn, food_id)
    drafts.add_entry_to_draft(
        conn, draft.id, slot_no=slot_no, food_id=food_id, qty=qty, unit=unit
    )
    return _after_edit(request, conn, viewer, draft, slot_no)


@router.post("/drafts/{draft_id}/entries/{entry_id}")
def change_amount(
    draft_id: int,
    entry_id: int,
    request: Request,
    conn: ConnDep,
    viewer: ViewerDep,
    unit: Annotated[str, Form()],
    qty: Annotated[str, Form()] = "",
):
    draft = owned_plan(conn, viewer, draft_id, status="draft")
    slot_no = _slot_of_entry(conn, draft, entry_id)
    try:
        drafts.update_entry(conn, entry_id, qty=drafts.parse_amount(qty), unit=unit)
    except ValueError as exc:
        return _after_edit(request, conn, viewer, draft, slot_no, {entry_id: str(exc)})
    return _after_edit(request, conn, viewer, draft, slot_no)


@router.post("/drafts/{draft_id}/entries/{entry_id}/swap")
def swap_food(
    draft_id: int,
    entry_id: int,
    request: Request,
    conn: ConnDep,
    viewer: ViewerDep,
    food_id: Annotated[int, Form()],
):
    draft = owned_plan(conn, viewer, draft_id, status="draft")
    slot_no = _slot_of_entry(conn, draft, entry_id)
    qty, unit = default_portion(conn, food_id)
    drafts.replace_entry_food(conn, entry_id, food_id, qty=qty, unit=unit)
    return _after_edit(request, conn, viewer, draft, slot_no)


@router.post("/drafts/{draft_id}/entries/{entry_id}/remove")
def remove_food(
    draft_id: int, entry_id: int, request: Request, conn: ConnDep, viewer: ViewerDep
):
    draft = owned_plan(conn, viewer, draft_id, status="draft")
    slot_no = _slot_of_entry(conn, draft, entry_id)
    drafts.remove_entry(conn, entry_id)
    return _after_edit(request, conn, viewer, draft, slot_no)


@router.post("/drafts/{draft_id}/save-over")
def save_draft_over(draft_id: int, request: Request, conn: ConnDep, viewer: ViewerDep):
    draft = owned_plan(conn, viewer, draft_id, status="draft")
    try:
        drafts.save_over(conn, draft.id)
    except (YolkError, ValueError) as exc:
        return _draft_page(
            request, conn, viewer, draft, status_code=422, form_error=str(exc)
        )
    return RedirectResponse(f"/plans/{draft.parent_plan_id}", status_code=303)


@router.post("/drafts/{draft_id}/save-as-new")
def save_draft_as_new(
    draft_id: int,
    request: Request,
    conn: ConnDep,
    viewer: ViewerDep,
    name: Annotated[str, Form()] = "",
):
    draft = owned_plan(conn, viewer, draft_id, status="draft")
    try:
        plan_id = drafts.save_as_new(conn, draft.id, name=name)
    except (YolkError, ValueError) as exc:
        return _draft_page(
            request, conn, viewer, draft, status_code=422, form_error=str(exc)
        )
    return RedirectResponse(f"/plans/{plan_id}", status_code=303)


@router.post("/drafts/{draft_id}/discard")
def discard_draft(draft_id: int, conn: ConnDep, viewer: ViewerDep):
    draft = owned_plan(conn, viewer, draft_id, status="draft")
    drafts.discard_draft(conn, draft.id)
    back = f"/plans/{draft.parent_plan_id}" if draft.parent_plan_id else "/plans"
    return RedirectResponse(back, status_code=303)
```

- [ ] **Step 5: Add the picker route**

Replace `src/yolk/web/routes/foods.py` with:

```python
"""The food library page, and the food picker used while editing a draft."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from yolk.foods import search_library
from yolk.web.deps import ConnDep, ViewerDep, is_htmx, owned_plan
from yolk.web.templating import templates

router = APIRouter()


@router.get("/foods", response_class=HTMLResponse)
def food_list(request: Request, conn: ConnDep, viewer: ViewerDep, q: str = ""):
    return templates.TemplateResponse(
        request,
        "foods/list.html",
        {"viewer": viewer, "query": q, "foods": search_library(conn, q)},
    )


@router.get("/foods/search", response_class=HTMLResponse)
def food_picker(
    request: Request,
    conn: ConnDep,
    viewer: ViewerDep,
    draft: int,
    slot: int,
    q: str = "",
    entry: int | None = None,
):
    plan = owned_plan(conn, viewer, draft, status="draft")
    htmx = is_htmx(request)
    pick = {
        "action": f"/drafts/{plan.id}/entries"
        if entry is None
        else f"/drafts/{plan.id}/entries/{entry}/swap",
        "label": "Add" if entry is None else "Swap in",
        "fields": {"slot_no": slot} if entry is None else {},
        # Only an inline picker has a slot on the page to swap; the full-page
        # picker posts plainly and is redirected back to the draft.
        "target": f"#slot-{slot}" if htmx else None,
    }
    return templates.TemplateResponse(
        request,
        "foods/_picker.html" if htmx else "foods/pick.html",
        {
            "viewer": viewer,
            "draft": plan,
            "slot": slot,
            "entry": entry,
            "query": q,
            "foods": search_library(conn, q),
            "pick": pick,
        },
    )
```

- [ ] **Step 6: Write the templates**

In `src/yolk/web/templates/base.html`, add after the stylesheet `<link>`:

```html
  <script src="/static/htmx.min.js" defer></script>
```

Replace `src/yolk/web/templates/plans/_slot.html` with:

```html
{# Needs: ps (PlanSlot).
   Editing a draft also needs: draft (PlanHeader) and entry_units
   (dict[int, list[str]]); entry_errors (dict[int, str]) is optional.
   Without draft the slot is read-only. #}
<section class="slot" id="slot-{{ ps.slot_no }}">
  <h2>{{ ps.name }}</h2>
  {% if ps.slot and ps.slot.entries %}
  <table>
    <thead>
      <tr>
        <th>Food</th><th class="num">Amount</th><th class="num">Grams</th>
        <th class="num">kcal</th><th class="num">Protein</th>
        <th class="num">Fat</th><th class="num">Carbs</th>
        {% if draft %}<th></th>{% endif %}
      </tr>
    </thead>
    <tbody>
    {% for entry in ps.slot.entries %}
      {% set action = "/drafts/" ~ draft.id ~ "/entries/" ~ entry.entry_id if draft else "" %}
      <tr{% if entry.error %} class="has-error"{% endif %}>
        <td>{{ entry.food_name }}</td>
        <td class="num">
          {% if draft %}
          <form class="amount" method="post" action="{{ action }}"
                hx-post="{{ action }}" hx-trigger="change"
                hx-target="#slot-{{ ps.slot_no }}" hx-swap="outerHTML">
            <input name="qty" value="{{ '%g'|format(entry.qty) }}" inputmode="decimal"
                   aria-label="Amount of {{ entry.food_name }}">
            {% set units = entry_units[entry.food_id] %}
            <select name="unit" aria-label="Unit for {{ entry.food_name }}">
              {% if entry.unit not in units %}<option selected>{{ entry.unit }}</option>{% endif %}
              {% for unit in units %}<option{% if unit == entry.unit %} selected{% endif %}>{{ unit }}</option>{% endfor %}
            </select>
            <noscript><button type="submit">Update</button></noscript>
          </form>
          {% else %}
          {{ "%g"|format(entry.qty) }} {{ entry.unit }}
          {% endif %}
        </td>
        {% if entry.error %}
        <td colspan="5" class="entry-error">{{ entry.error }}</td>
        {% else %}
        <td class="num">{{ "%.0f"|format(entry.grams) }}</td>
        <td class="num">{{ "%.0f"|format(entry.macros.kcal) }}</td>
        <td class="num">{{ "%.1f"|format(entry.macros.protein_g) }}</td>
        <td class="num">{{ "%.1f"|format(entry.macros.fat_g) }}</td>
        <td class="num">{{ "%.1f"|format(entry.macros.carb_g) }}</td>
        {% endif %}
        {% if draft %}
        {% set swap_url = "/foods/search?draft=" ~ draft.id ~ "&slot=" ~ ps.slot_no ~ "&entry=" ~ entry.entry_id %}
        <td class="actions">
          <a class="button" href="{{ swap_url }}" hx-get="{{ swap_url }}"
             hx-target="#picker-{{ ps.slot_no }}">Swap</a>
          <form method="post" action="{{ action }}/remove" hx-post="{{ action }}/remove"
                hx-target="#slot-{{ ps.slot_no }}" hx-swap="outerHTML">
            <button type="submit">Remove</button>
          </form>
        </td>
        {% endif %}
      </tr>
      {% if entry_errors and entry.entry_id in entry_errors %}
      <tr><td colspan="8" class="entry-error">{{ entry_errors[entry.entry_id] }}</td></tr>
      {% endif %}
    {% endfor %}
    </tbody>
    <tfoot>
      <tr>
        <td colspan="3">Slot total</td>
        <td class="num">{{ "%.0f"|format(ps.slot.totals.kcal) }}</td>
        <td class="num">{{ "%.1f"|format(ps.slot.totals.protein_g) }}</td>
        <td class="num">{{ "%.1f"|format(ps.slot.totals.fat_g) }}</td>
        <td class="num">{{ "%.1f"|format(ps.slot.totals.carb_g) }}</td>
        {% if draft %}<td></td>{% endif %}
      </tr>
    </tfoot>
  </table>
  {% else %}
  <p class="muted">Nothing planned for this meal.</p>
  {% endif %}
  {% if draft %}
  {% set add_url = "/foods/search?draft=" ~ draft.id ~ "&slot=" ~ ps.slot_no %}
  <p class="slot-actions">
    <a class="button" href="{{ add_url }}" hx-get="{{ add_url }}"
       hx-target="#picker-{{ ps.slot_no }}">Add food</a>
  </p>
  <div class="picker" id="picker-{{ ps.slot_no }}"></div>
  {% endif %}
</section>
```

Jinja autoescapes the `&` in these URLs to `&amp;` inside the attributes, which is correct HTML, and the browser decodes it back.

In `src/yolk/web/templates/plans/_totals.html`, change the comment's `Optional: vs (Macros, draft minus saved plan).` to `Optional: vs (Macros, draft minus saved plan); oob (true when htmx swaps the totals out of band).`, and change `<section class="totals" id="totals">` to:

```html
<section class="totals" id="totals"{% if oob %} hx-swap-oob="true"{% endif %}>
```

Create `src/yolk/web/templates/drafts/_changed.html`:

```html
{# The htmx answer to one edit: the changed slot, and the day totals swapped
   out of band. Needs the draft_context plus ps (the changed PlanSlot). #}
{% include "plans/_slot.html" %}
{% with oob = true %}{% include "plans/_totals.html" %}{% endwith %}
```

Create `src/yolk/web/templates/foods/_picker.html`:

```html
{# The food picker under a slot. Needs: draft (PlanHeader), slot (int),
   entry (int or None: set when swapping), query (str), foods, pick. #}
<form class="search" method="get" action="/foods/search"
      hx-get="/foods/search" hx-target="#picker-{{ slot }}">
  <input type="hidden" name="draft" value="{{ draft.id }}">
  <input type="hidden" name="slot" value="{{ slot }}">
  {% if entry is not none %}<input type="hidden" name="entry" value="{{ entry }}">{% endif %}
  <input type="search" name="q" value="{{ query }}" aria-label="Search foods"
         placeholder="{{ 'Swap for…' if entry is not none else 'Add a food…' }}">
  <button type="submit">Search</button>
</form>
{% include "foods/_results.html" %}
```

Create `src/yolk/web/templates/foods/pick.html`:

```html
{% extends "base.html" %}
{% block title %}Choose a food · yolk{% endblock %}
{% block content %}
<h1>Choose a food</h1>
<p><a href="/drafts/{{ draft.id }}">Back to {{ draft.name }}</a></p>
<div class="picker" id="picker-{{ slot }}">
{% include "foods/_picker.html" %}
</div>
{% endblock %}
```

In `src/yolk/web/templates/foods/_results.html`:
- Replace the first comment line with:

```html
{# Needs: foods (list[FoodSummary]), query (str).
   Optional: pick, which adds a button to every row: {"action": URL to post to,
   "label": button text, "fields": extra hidden fields, "target": CSS selector
   for htmx to swap, or None for a plain post}. Each button posts food_id plus
   the fields. This partial knows nothing about what the action does. #}
```

- In the header row, insert `{% if pick %}<th></th>{% endif %}` after `<th>Units</th>`.
- In the body row, insert after the Units `<td>…</td>`:

```html
        {% if pick %}
        <td class="actions">
          <form method="post" action="{{ pick.action }}"{% if pick.target %} hx-post="{{ pick.action }}" hx-target="{{ pick.target }}" hx-swap="outerHTML"{% endif %}>
            {% for name, value in pick.fields.items() %}<input type="hidden" name="{{ name }}" value="{{ value }}">{% endfor %}
            <input type="hidden" name="food_id" value="{{ food.id }}">
            <button type="submit">{{ pick.label }}</button>
          </form>
        </td>
        {% endif %}
```

- [ ] **Step 7: Style the editing controls**

Append to `src/yolk/web/static/app.css`:

```css
form.amount { display: flex; gap: 0.3rem; justify-content: flex-end; }
form.amount input { width: 4.5rem; text-align: right; }
td.actions { white-space: nowrap; }
td.actions form { display: inline; }
.slot-actions { margin: 0.75rem 0 0; }
.picker:not(:empty) { margin-top: 0.75rem; }
.slot .results { border: 0; padding: 0; margin: 0; background: transparent; }
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_web_editing.py tests/test_web_drafts.py tests/test_web_foods.py tests/test_web_plans.py -q`
Expected: PASS

- [ ] **Step 9: Run the whole suite and commit**

Run: `uv run python -m pytest -q`
Expected: PASS, 264 tests, the one known warning. `grep -rn "execute(" src/yolk/web` prints nothing.

```bash
git add src/yolk/web tests/test_web_editing.py
git commit -m "feat: edit the meals in a draft, in place" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 9: README and a real run

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: everything above.
- Produces: documentation only. Step 2 is the controller's check in a real browser.

- [ ] **Step 1: Document planning**

Append to `README.md`, after the "Looking at a plan" section:

```markdown
## Planning meals

On the plan list, **New plan** starts an empty day against one of your profiles,
and **Edit or copy** on any plan opens a draft of it. All editing happens in a
draft: change amounts and units, swap or remove foods, and add foods from the
library under each meal. The day totals update as you go. A saved plan changes
only when you choose **Save over**. **Save as new** keeps the original and saves
the draft under a new name, and **Discard** throws the draft away. Drafts live in
the database, so an unfinished one is still there after a restart.

The **Foods** page searches the food library by name or brand.

After updating to this version, run `uv run python -m yolk migrate` once. Drafts
need migration 2, and the app says so until it has run.
```

Run: `uv run python -m pytest -q`
Expected: PASS, 264 tests

```bash
git add README.md
git commit -m "docs: explain planning meals with drafts" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 2: Real run (controller only)**

This step changes the real database only by migrating it. It saves nothing else, because the app has no way to delete a plan yet.

1. Back up first: `uv run python -m yolk export --out <scratchpad>/pre-0002-export`.
2. `uv run python -m yolk migrate` prints `Applied migrations: 2`.
3. Restart the `yolk` preview server.
4. **New plan:** create "Test day" against training. Under Meal 1, use Add food to search "coffee" and add Buff Chick Coffee. Change its amount to 2. The slot and day totals must update without a page reload. Swap it for Pork Rinds, then remove it. Then **Discard**. The plan list must show no "Test day" and no "In progress".
5. **Edit or copy:** open Keto Meal Plan A and choose Edit or copy. Change one amount; the "vs saved" column must show the change. **Discard**. Keto Meal Plan A must still read 2146 kcal.
6. Check phone width (375 px) and dark mode on the draft page. The page itself must not scroll sideways.
7. Turn JavaScript off in the browser, or note this as untested if the pane cannot. Confirm that changing an amount with the Update button reloads the page with the new value.

Record anything that looks wrong as a follow-up rather than fixing it inside this task.

---

## Done when

- `uv run python -m pytest` passes at 264 tests, with only the one known warning.
- In the browser, you can start, edit, save and discard drafts, and a saved plan changes only through Save over.
- `grep -rn "execute(" src/yolk/web` prints nothing.
- `git status --short` shows no `yolk.db`.
