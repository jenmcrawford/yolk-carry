# Read a Plan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run `uv run python -m yolk serve`, open `http://127.0.0.1:8000`, and see your plans and Keto Plan A's slots, foods, and day totals against the profile target, with the same numbers the golden test asserts.

**Architecture:** A FastAPI app under `src/yolk/web/` renders Jinja templates on the server. Routes only translate between HTTP and library calls. Every number and every query comes from a library function, so this slice first adds the few read functions the pages need (`list_people`, `slot_names`, `get_plan`, `plan_summaries`, `pending`). One connection is opened per request by a dependency that first checks the database exists and is fully migrated, and otherwise renders the command to run.

**Tech Stack:** Python 3.14, `uv`, FastAPI 0.142, Starlette 1.7, uvicorn 0.54, Jinja2 3.1, python-multipart, stdlib `sqlite3`, `pytest` with FastAPI's `TestClient` (it uses the existing `httpx` dependency).

**Spec:** [2026-09-13-local-app-persistence-and-review-design.md](../specs/2026-09-13-local-app-persistence-and-review-design.md), slice 2 (§5), the `yolk serve` row of §4.3, the slice 2 rows of §12, and the slice 2 tests of §13. Slices 3 through 6 are not in this plan.

**Deliberate departures from the spec:**

- **htmx is not vendored in this slice.** §5.1 lists `static/htmx.min.js`, but slice 2 has no swaps: every page is a plain GET. Slice 3 is the first slice that posts edits and swaps partials, so it vendors htmx. The partials rule (§5.2) is still followed here, so slice 3 can swap them without restructuring.
- **With several people and no cookie, the app shows the first person by id.** §5.2 says a picker sets a cookie but not what is shown before anyone picks. Showing the first person, with the picker visible, is the least surprising choice.

## Global Constraints

- Python `>=3.14`, managed by `uv`.
- **Run tools as modules, not as console scripts.** Windows Smart App Control blocks the generated launchers in `.venv/Scripts/`. `uv run python -m pytest` works and `uv run pytest` does not. The same applies to `uv run python -m yolk serve` and to uvicorn: never run `uvicorn.exe`, and never tell the reader to.
- New runtime dependencies are exactly `fastapi`, `uvicorn`, `jinja2`, `python-multipart` (§5.1). Nothing else.
- **The web layer does no arithmetic and no SQL** (§5.2). No `conn.execute` anywhere under `src/yolk/web/`. Formatting a number in a template (`"%.0f"|format(x)`) is display, not arithmetic, and is allowed. Adding, subtracting, or comparing numbers in a route or template is not.
- **Templates consume library dataclasses directly.** No view-model layer.
- **Every fragment is a partial, and full pages include the same partials.**
- **One connection per request**, opened by a dependency and closed after the response.
- The app binds to `127.0.0.1` only. There is no `--host` option.
- The app never migrates and never creates a database file. A missing or behind database renders the command to run (§12).
- Portable SQL only. Placeholders stay `?`. New code uses `RETURNING id` and annotates connections as `yolk.db.Connection`.
- Library tests use `:memory:` databases. Web tests use a file under pytest's `tmp_path`, because the app opens its own connections by path. No test touches the resolved database path (`yolk.db` in the repo root).
- **Starlette 1.x API.** `TemplateResponse` takes the request first: `templates.TemplateResponse(request, "name.html", {...}, status_code=...)`. The old `TemplateResponse("name.html", {"request": request})` form was removed in Starlette 1.0 and will raise.
- The full suite is `uv run python -m pytest`. It passes at 145 tests before this plan starts and must pass at the end of every task.
- Commit at the end of every task.

---

## File Structure

**Created:**

| Path | Responsibility |
|---|---|
| `src/yolk/planning/plans.py` | Reading plans for display: one plan's header, a person's plan list with pass/fail |
| `src/yolk/web/__init__.py` | Package marker |
| `src/yolk/web/app.py` | `create_app()`: routes, static files, exception handlers |
| `src/yolk/web/templating.py` | The one `Jinja2Templates` instance, shared by `app.py` and every route module |
| `src/yolk/web/deps.py` | Per-request connection, readiness check, current person |
| `src/yolk/web/routes/__init__.py` | Package marker |
| `src/yolk/web/routes/plans.py` | `/plans` and `/plans/{id}` |
| `src/yolk/web/routes/people.py` | `POST /person`, the picker |
| `src/yolk/web/templates/base.html` | Page shell, header, person picker |
| `src/yolk/web/templates/setup.html` | "Run this command" page |
| `src/yolk/web/templates/error.html` | Not-found and unexpected-error page |
| `src/yolk/web/templates/plans/list.html` | Plan list |
| `src/yolk/web/templates/plans/detail.html` | Plan page |
| `src/yolk/web/templates/plans/_totals.html` | Totals partial |
| `src/yolk/web/templates/plans/_slot.html` | Slot partial |
| `src/yolk/web/static/app.css` | Stylesheet |
| `tests/test_connection.py`, `tests/test_plans.py`, `tests/test_web.py`, `tests/test_web_plans.py`, `tests/test_web_people.py` | Tests |

**Modified:**

| Path | Change |
|---|---|
| `src/yolk/db/connection.py` | `connect()` gains `check_same_thread` |
| `src/yolk/db/migrate.py` | Gains `pending()` |
| `src/yolk/people.py` | Gains `Person`, `list_people()`, `slot_names()` |
| `src/yolk/cli.py` | Gains `yolk serve` |
| `tests/conftest.py` | Gains `seeded` and `client` fixtures |
| `tests/test_migrate.py`, `tests/test_people.py`, `tests/test_cli.py` | New tests |
| `pyproject.toml`, `uv.lock` | Four runtime dependencies |
| `README.md` | `serve` in the command table, and how to look at a plan |

---

## Task 1: Library reads for people, slots, migrations, and connections

**Files:**
- Modify: `src/yolk/db/connection.py`
- Modify: `src/yolk/db/migrate.py`
- Modify: `src/yolk/people.py`
- Test: `tests/test_connection.py` (create), `tests/test_migrate.py`, `tests/test_people.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `yolk.db.connection.connect(path: str | Path, *, check_same_thread: bool = True) -> Connection`
  - `yolk.db.migrate.pending(conn: Connection, directory: Path = MIGRATIONS_DIR) -> list[int]`
  - `yolk.people.Person` — frozen dataclass with `id: int`, `name: str`
  - `yolk.people.list_people(conn: Connection) -> list[Person]`, ordered by id
  - `yolk.people.slot_names(conn: Connection, profile_id: int) -> dict[int, str]`, slot number to slot template name

**Why `check_same_thread`:** FastAPI runs a sync dependency and a sync route on threadpool threads, and they are not guaranteed to be the same thread. sqlite3 refuses to use a connection from a thread other than the one that opened it unless `check_same_thread=False`. The web app never shares a connection between requests, so turning the guard off there is safe. Everything else keeps the default.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_connection.py`:

```python
import threading

from yolk.db.connection import connect


def test_a_connection_can_be_opened_for_use_on_another_thread(tmp_path):
    """The web app opens a connection in a dependency and may use it in a
    route running on a different threadpool thread."""
    conn = connect(tmp_path / "t.db", check_same_thread=False)
    seen: list[int] = []
    worker = threading.Thread(
        target=lambda: seen.append(conn.execute("SELECT 1 AS n").fetchone()["n"])
    )
    worker.start()
    worker.join()
    conn.close()
    assert seen == [1]
```

Append to `tests/test_migrate.py`, and add `pending` to its existing `from yolk.db.migrate import (...)` block. `connect`, `apply_migrations`, and `available` are already imported there.

```python
def test_pending_lists_every_migration_on_a_fresh_database():
    conn = connect(":memory:")
    assert pending(conn) == [version for version, _ in available()]
    conn.close()


def test_pending_is_empty_once_migrations_are_applied():
    conn = connect(":memory:")
    apply_migrations(conn)
    assert pending(conn) == []
    conn.close()
```

Append to `tests/test_people.py` (add `list_people` and `slot_names` to the existing `from yolk.people import (...)`):

```python
def test_list_people_is_ordered_by_id(db):
    first = create_person(db, "Jen")
    second = create_person(db, "Avery")
    people = list_people(db)
    assert [(p.id, p.name) for p in people] == [(first, "Jen"), (second, "Avery")]


def test_list_people_is_empty_on_a_fresh_database(db):
    assert list_people(db) == []


def test_slot_names_maps_slot_numbers_for_one_profile(db):
    pid = create_person(db, "Jen")
    training = create_profile(
        db, pid, name="training", effective_on="2026-07-14",
        kcal=2150, fat_pct=34, carb_pct=28, protein_pct=38,
    )
    rest = create_profile(
        db, pid, name="rest", effective_on="2026-07-14",
        kcal=2115, fat_pct=39, carb_pct=18, protein_pct=43,
    )
    create_slot(db, pid, training, slot_no=1, name="Wake Up", time_of_day="06:30")
    create_slot(db, pid, training, slot_no=6, name="Dinner", time_of_day="18:00")
    create_slot(db, pid, rest, slot_no=1, name="Rest breakfast", time_of_day="08:00")
    assert slot_names(db, training) == {1: "Wake Up", 6: "Dinner"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_connection.py tests/test_migrate.py tests/test_people.py -q`
Expected: FAIL. `test_connection.py` with `TypeError: connect() got an unexpected keyword argument 'check_same_thread'`; the other two files fail to import `pending`, `list_people`, `slot_names`.

- [ ] **Step 3: Implement**

In `src/yolk/db/connection.py`, replace `connect` with:

```python
def connect(path: str | Path, *, check_same_thread: bool = True) -> Connection:
    """Open a connection with row access by name and foreign keys enforced.

    The web app passes check_same_thread=False: FastAPI may open a request's
    connection on one threadpool thread and use it on another. A connection
    there belongs to exactly one request and is never used concurrently, so
    sqlite3's same-thread guard protects nothing. Everything else keeps it.
    """
    conn = sqlite3.connect(path, check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
```

In `src/yolk/db/migrate.py`, add after `applied`:

```python
def pending(conn: Connection, directory: Path = MIGRATIONS_DIR) -> list[int]:
    """Versions on disk that this database has not applied yet, in order."""
    done = applied(conn)
    return [version for version, _ in available(directory) if version not in done]
```

In `src/yolk/people.py`, add `from dataclasses import dataclass` to the imports, then add after `create_person`:

```python
@dataclass(frozen=True)
class Person:
    id: int
    name: str


def list_people(conn: Connection) -> list[Person]:
    rows = conn.execute("SELECT id, name FROM people ORDER BY id").fetchall()
    return [Person(id=row["id"], name=row["name"]) for row in rows]
```

and at the end of the file:

```python
def slot_names(conn: Connection, profile_id: int) -> dict[int, str]:
    """Slot number to slot template name, for one profile's slots."""
    rows = conn.execute(
        "SELECT slot_no, name FROM slot_templates WHERE profile_id = ? "
        "ORDER BY slot_no",
        (profile_id,),
    ).fetchall()
    return {row["slot_no"]: row["name"] for row in rows}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_connection.py tests/test_migrate.py tests/test_people.py -q`
Expected: PASS

- [ ] **Step 5: Run the whole suite and commit**

Run: `uv run python -m pytest -q`
Expected: PASS, 151 tests

```bash
git add src/yolk/db/connection.py src/yolk/db/migrate.py src/yolk/people.py tests/test_connection.py tests/test_migrate.py tests/test_people.py
git commit -m "feat: add the people, slot, and migration reads the web app needs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 2: Plan reads for display

**Files:**
- Create: `src/yolk/planning/plans.py`
- Test: `tests/test_plans.py`

**Interfaces:**
- Consumes: `yolk.planning.evaluate.evaluate(conn, day_plan_id) -> DayEvaluation`, which raises `LookupError` for a missing plan and a `yolk.errors.YolkError` subclass (for example `UnknownUnitError`) for a plan it cannot compute.
- Produces:
  - `yolk.planning.plans.PlanHeader` — frozen dataclass: `id: int`, `person_id: int`, `profile_id: int`, `profile_name: str`, `name: str`, `status: str`
  - `yolk.planning.plans.PlanSummary` — frozen dataclass: `id: int`, `name: str`, `profile_name: str`, `ok: bool | None`, `error: str | None`. `ok` is `None` exactly when `error` is set.
  - `yolk.planning.plans.get_plan(conn: Connection, plan_id: int) -> PlanHeader`, raising `LookupError` when there is no such plan
  - `yolk.planning.plans.plan_summaries(conn: Connection, person_id: int) -> list[PlanSummary]`: that person's `active` plans, ordered by name

**Why `plan_summaries` catches errors:** the list page shows whether each plan is within tolerance. One plan with an unresolvable unit must not take the whole list down, and the route may not decide that itself, because routes contain no logic beyond translating calls. So the library returns the error as data.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_plans.py`:

```python
import pytest

from yolk.people import create_person, create_profile
from yolk.planning.evaluate import add_entry, create_day_plan
from yolk.planning.plans import get_plan, plan_summaries
from yolk.seed import seed_keto_plan_a


def _second_person_with_plan(db) -> tuple[int, int]:
    sam = create_person(db, "Sam")
    profile = create_profile(
        db, sam, name="rest", effective_on="2026-07-14",
        kcal=2000, fat_pct=40, carb_pct=20, protein_pct=40,
    )
    return sam, create_day_plan(db, sam, profile, name="Sam plan")


def _first_food_id(db, plan_id: int) -> int:
    return db.execute(
        "SELECT food_id FROM day_plan_entries WHERE day_plan_id = ? ORDER BY id",
        (plan_id,),
    ).fetchone()["food_id"]


def test_get_plan_returns_the_header_with_its_profile_name(db):
    plan_id, spec = seed_keto_plan_a(db)
    plan = get_plan(db, plan_id)
    assert plan.id == plan_id
    assert plan.name == spec["plan_name"]
    assert plan.profile_name == spec["profile"]["name"]
    assert plan.status == "active"


def test_get_plan_for_a_missing_plan_raises(db):
    with pytest.raises(LookupError):
        get_plan(db, 999)


def test_plan_summaries_marks_the_seeded_plan_within_tolerance(db):
    plan_id, spec = seed_keto_plan_a(db)
    person_id = get_plan(db, plan_id).person_id
    [summary] = plan_summaries(db, person_id)
    assert (summary.id, summary.name, summary.profile_name) == (
        plan_id, spec["plan_name"], spec["profile"]["name"]
    )
    assert summary.ok is True
    assert summary.error is None


def test_plan_summaries_leaves_out_archived_plans(db):
    plan_id, _ = seed_keto_plan_a(db)
    person_id = get_plan(db, plan_id).person_id
    db.execute("UPDATE day_plans SET status = 'archived' WHERE id = ?", (plan_id,))
    db.commit()
    assert plan_summaries(db, person_id) == []


def test_plan_summaries_shows_only_that_persons_plans(db):
    plan_id, _ = seed_keto_plan_a(db)
    sam, sam_plan = _second_person_with_plan(db)
    assert [s.id for s in plan_summaries(db, sam)] == [sam_plan]


def test_a_plan_that_cannot_be_evaluated_is_listed_with_its_error(db):
    """An unknown unit must not take the whole list down."""
    plan_id, _ = seed_keto_plan_a(db)
    person_id = get_plan(db, plan_id).person_id
    add_entry(
        db, plan_id, slot_no=1, food_id=_first_food_id(db, plan_id),
        qty=1, unit="handful",
    )
    [summary] = plan_summaries(db, person_id)
    assert summary.ok is None
    assert "handful" in summary.error
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_plans.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'yolk.planning.plans'`

- [ ] **Step 3: Implement**

Create `src/yolk/planning/plans.py`:

```python
"""Reading plans for display: one plan's header, and a person's plan list.

These exist so the web layer can show plans without running SQL itself.
"""

from __future__ import annotations

from dataclasses import dataclass

from yolk.db import Connection
from yolk.errors import YolkError
from yolk.planning.evaluate import evaluate


@dataclass(frozen=True)
class PlanHeader:
    id: int
    person_id: int
    profile_id: int
    profile_name: str
    name: str
    status: str


@dataclass(frozen=True)
class PlanSummary:
    id: int
    name: str
    profile_name: str
    # None exactly when the plan could not be evaluated; `error` then says why.
    ok: bool | None
    error: str | None


def get_plan(conn: Connection, plan_id: int) -> PlanHeader:
    row = conn.execute(
        "SELECT p.id, p.person_id, p.profile_id, p.name, p.status, "
        "m.name AS profile_name "
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
    )


def plan_summaries(conn: Connection, person_id: int) -> list[PlanSummary]:
    """A person's active plans, each marked within tolerance or not.

    A plan that cannot be evaluated is still listed, carrying the error, so
    one bad entry cannot hide every other plan.
    """
    rows = conn.execute(
        "SELECT p.id, p.name, m.name AS profile_name "
        "FROM day_plans p JOIN macro_profiles m ON m.id = p.profile_id "
        "WHERE p.person_id = ? AND p.status = 'active' ORDER BY p.name, p.id",
        (person_id,),
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_plans.py -q`
Expected: PASS

- [ ] **Step 5: Run the whole suite and commit**

Run: `uv run python -m pytest -q`
Expected: PASS, 157 tests

```bash
git add src/yolk/planning/plans.py tests/test_plans.py
git commit -m "feat: read plan headers and per-person plan summaries

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 3: The app shell, readiness checks, and the plan list

**Files:**
- Modify: `pyproject.toml`, `uv.lock` (via `uv add`)
- Create: `src/yolk/web/__init__.py`, `src/yolk/web/app.py`, `src/yolk/web/templating.py`, `src/yolk/web/deps.py`
- Create: `src/yolk/web/routes/__init__.py`, `src/yolk/web/routes/plans.py`
- Create: `src/yolk/web/templates/base.html`, `setup.html`, `error.html`, `plans/list.html`
- Create: `src/yolk/web/static/app.css`
- Modify: `tests/conftest.py`
- Test: `tests/test_web.py`

**Interfaces:**
- Consumes: `connect(path, *, check_same_thread)`, `pending(conn)`, `Person`, `list_people(conn)` (Task 1); `plan_summaries(conn, person_id)` (Task 2); `yolk.config.database_path() -> Path`.
- Produces:
  - `yolk.web.app.create_app(db_path: Path | None = None) -> FastAPI`. With `None`, it resolves `database_path()` once, at creation. The path is kept on `app.state.db_path`.
  - `yolk.web.templating.templates: Jinja2Templates`
  - `yolk.web.deps.SetupRequired(Exception)` with attributes `message: str`, `command: str`
  - `yolk.web.deps.Viewer` — frozen dataclass: `person: Person`, `people: list[Person]`
  - `yolk.web.deps.PERSON_COOKIE = "yolk_person"`
  - `yolk.web.deps.ConnDep = Annotated[Connection, Depends(get_conn)]`
  - `yolk.web.deps.ViewerDep = Annotated[Viewer, Depends(get_viewer)]`
  - `yolk.web.routes.plans.router: APIRouter`, serving `GET /plans`
  - Template context contract: every page template receives `viewer` (a `Viewer`) except `setup.html` and the unexpected-error page, which receive no `viewer`. `base.html` must render without one.
  - Test fixtures in `tests/conftest.py`: `seeded` → `(path: Path, plan_id: int, spec: dict)`; `client` → `TestClient` over `create_app(path)`.

**Setup states (§5.2, §12):**

| Database state | Response |
|---|---|
| No file at the path | 503, `setup.html`, command `uv run python -m yolk init --seed`. The file must **not** be created: `sqlite3.connect` would create an empty one, which would then look like a database to every later check. |
| File exists, migrations pending | 503, `setup.html`, command `uv run python -m yolk migrate` |
| Migrated, no rows in `people` | 503, `setup.html`, command `uv run python -m yolk init --seed` |
| Unexpected exception | 500, `error.html` with a plain message. uvicorn logs the traceback to the console; the page never shows it. |

- [ ] **Step 1: Add the dependencies**

Run:

```bash
uv add "fastapi>=0.142" "uvicorn>=0.54" "jinja2>=3.1" "python-multipart>=0.0.32"
```

Expected: `pyproject.toml`'s `dependencies` gains the four packages and `uv.lock` updates. Confirm with `uv run python -c "import fastapi, uvicorn, jinja2, multipart"`, which should print nothing.

- [ ] **Step 2: Add the web fixtures**

Append to `tests/conftest.py` (keep the existing `db` and `person` fixtures as they are), and add these imports at the top:

```python
from fastapi.testclient import TestClient

from yolk.seed import seed_keto_plan_a
from yolk.web.app import create_app
```

```python
@pytest.fixture
def seeded(tmp_path):
    """A seeded database file, for tests that go through the app.

    The app opens its own connection per request by path, so these tests use
    a file under tmp_path rather than :memory:.
    """
    path = tmp_path / "yolk.db"
    conn = connect(path)
    create_schema(conn)
    plan_id, spec = seed_keto_plan_a(conn)
    conn.close()
    return path, plan_id, spec


@pytest.fixture
def client(seeded):
    return TestClient(create_app(seeded[0]))
```

- [ ] **Step 3: Write the failing tests**

Create `tests/test_web.py`:

```python
from fastapi.testclient import TestClient

from yolk.db.connection import connect, create_schema
from yolk.db.migrate import applied
from yolk.web.app import create_app


def test_the_root_redirects_to_the_plan_list(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/plans"


def test_the_plan_list_shows_the_seeded_plan(client, seeded):
    _, plan_id, spec = seeded
    response = client.get("/plans")
    assert response.status_code == 200
    assert spec["plan_name"] in response.text
    assert spec["profile"]["name"] in response.text
    assert f'href="/plans/{plan_id}"' in response.text
    assert "Within tolerance" in response.text


def test_a_missing_database_says_to_run_init_and_is_not_created(tmp_path):
    path = tmp_path / "absent.db"
    response = TestClient(create_app(path)).get("/plans")
    assert response.status_code == 503
    assert "uv run python -m yolk init --seed" in response.text
    assert not path.exists()


def test_a_database_behind_on_migrations_says_to_run_migrate(tmp_path):
    path = tmp_path / "old.db"
    conn = connect(path)
    applied(conn)  # creates the bookkeeping table, applies nothing
    conn.close()
    response = TestClient(create_app(path)).get("/plans")
    assert response.status_code == 503
    assert "uv run python -m yolk migrate" in response.text


def test_a_database_with_nobody_in_it_says_to_seed(tmp_path):
    path = tmp_path / "empty.db"
    conn = connect(path)
    create_schema(conn)
    conn.close()
    response = TestClient(create_app(path)).get("/plans")
    assert response.status_code == 503
    assert "uv run python -m yolk init --seed" in response.text


def test_an_unexpected_error_renders_a_plain_page(seeded, monkeypatch):
    def explode(conn, person_id):
        raise RuntimeError("boom")

    monkeypatch.setattr("yolk.web.routes.plans.plan_summaries", explode)
    client = TestClient(create_app(seeded[0]), raise_server_exceptions=False)
    response = client.get("/plans")
    assert response.status_code == 500
    assert "Something went wrong" in response.text
    assert "boom" not in response.text
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_web.py -q`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'yolk.web'`. Every other test file also fails to collect now, because `conftest.py` imports `yolk.web.app`. That is expected and is fixed by Step 5.

- [ ] **Step 5: Implement the app**

Create `src/yolk/web/__init__.py` and `src/yolk/web/routes/__init__.py`, both empty.

Create `src/yolk/web/templating.py`:

```python
"""The template environment, shared by the app and every route module."""

from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
```

Create `src/yolk/web/deps.py`:

```python
"""Per-request plumbing: the database connection and the current person.

Routes get both through FastAPI dependencies, so no route opens a connection,
checks the database is ready, or decides who is looking.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from yolk.db import Connection
from yolk.db.connection import connect
from yolk.db.migrate import pending
from yolk.people import Person, list_people

PERSON_COOKIE = "yolk_person"

INIT_COMMAND = "uv run python -m yolk init --seed"
MIGRATE_COMMAND = "uv run python -m yolk migrate"


class SetupRequired(Exception):
    """The database cannot serve pages yet. `command` is what fixes it."""

    def __init__(self, message: str, command: str) -> None:
        super().__init__(message)
        self.message = message
        self.command = command


def get_conn(request: Request) -> Iterator[Connection]:
    """One connection per request, closed after the response.

    The app never migrates and never creates the database: either would hide
    a setup problem behind a page that looks fine.
    """
    path = request.app.state.db_path
    if not path.is_file():
        # connect() would create an empty file here, and an empty file looks
        # like a database to every later check. Refuse before opening.
        raise SetupRequired(f"There is no database at {path}.", INIT_COMMAND)
    conn = connect(path, check_same_thread=False)
    try:
        waiting = pending(conn)
        if waiting:
            raise SetupRequired(
                f"The database at {path} has not applied migration(s) "
                f"{', '.join(str(v) for v in waiting)}.",
                MIGRATE_COMMAND,
            )
        yield conn
    finally:
        conn.close()


ConnDep = Annotated[Connection, Depends(get_conn)]


@dataclass(frozen=True)
class Viewer:
    """Who the page is for, and who else could be picked."""

    person: Person
    people: list[Person]


def get_viewer(request: Request, conn: ConnDep) -> Viewer:
    """The person named by the cookie, or the first person if it names nobody."""
    people = list_people(conn)
    if not people:
        raise SetupRequired("The database has nobody in it yet.", INIT_COMMAND)
    chosen = request.cookies.get(PERSON_COOKIE)
    for person in people:
        if str(person.id) == chosen:
            return Viewer(person=person, people=people)
    return Viewer(person=people[0], people=people)


ViewerDep = Annotated[Viewer, Depends(get_viewer)]
```

FastAPI caches a dependency within one request, so `get_viewer`'s `ConnDep` and a route's `ConnDep` are the same connection.

Create `src/yolk/web/routes/plans.py`:

```python
"""Plan pages."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from yolk.planning.plans import plan_summaries
from yolk.web.deps import ConnDep, ViewerDep
from yolk.web.templating import templates

router = APIRouter()


@router.get("/plans", response_class=HTMLResponse)
def plan_list(request: Request, conn: ConnDep, viewer: ViewerDep):
    return templates.TemplateResponse(
        request,
        "plans/list.html",
        {"viewer": viewer, "plans": plan_summaries(conn, viewer.person.id)},
    )
```

Create `src/yolk/web/app.py`:

```python
"""The local web app.

create_app() wires routes, static files, and the two pages that replace a
normal response: "run this command" when the database is not ready, and a
plain error page for anything unexpected.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from yolk.config import database_path
from yolk.web.deps import SetupRequired
from yolk.web.routes import plans
from yolk.web.templating import templates

STATIC_DIR = Path(__file__).parent / "static"


def create_app(db_path: Path | None = None) -> FastAPI:
    app = FastAPI(title="yolk", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.db_path = db_path if db_path is not None else database_path()

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(plans.router)

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

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception):
        # Starlette re-raises after this handler responds, so uvicorn still
        # logs the traceback to the console. The page never shows it.
        return templates.TemplateResponse(request, "error.html", {}, status_code=500)

    return app
```

- [ ] **Step 6: Write the templates and stylesheet**

Create `src/yolk/web/templates/base.html`:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}yolk{% endblock %}</title>
  <link rel="stylesheet" href="/static/app.css">
</head>
<body>
  <header class="site">
    <a class="brand" href="/plans">yolk</a>
    <nav><a href="/plans">Plans</a></nav>
    {% block picker %}{% endblock %}
  </header>
  <main>
    {% block content %}{% endblock %}
  </main>
</body>
</html>
```

The `picker` block is empty here; Task 5 fills it.

Create `src/yolk/web/templates/setup.html`:

```html
{% extends "base.html" %}
{% block title %}Setup needed · yolk{% endblock %}
{% block content %}
<section class="notice">
  <h1>Setup needed</h1>
  <p>{{ message }}</p>
  <p>Run this from the repository, then reload:</p>
  <pre><code>{{ command }}</code></pre>
</section>
{% endblock %}
```

Create `src/yolk/web/templates/error.html`:

```html
{% extends "base.html" %}
{% block title %}Error · yolk{% endblock %}
{% block content %}
<section class="notice">
  {% if message %}
  <h1>Not found</h1>
  <p>{{ message }}</p>
  {% else %}
  <h1>Something went wrong</h1>
  <p>The details are in the terminal running <code>yolk serve</code>.</p>
  {% endif %}
  <p><a href="/plans">Back to plans</a></p>
</section>
{% endblock %}
```

Create `src/yolk/web/templates/plans/list.html`:

```html
{% extends "base.html" %}
{% block title %}Plans · yolk{% endblock %}
{% block content %}
<h1>{{ viewer.person.name }}'s plans</h1>
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
{% endblock %}
```

Create `src/yolk/web/static/app.css`:

```css
:root {
  --bg: #fbfaf7;
  --surface: #ffffff;
  --text: #1f1d1a;
  --muted: #6b665e;
  --line: #e4e0d8;
  --accent: #c9821a;
  --pass: #2f7a3e;
  --fail: #b3412e;
  --code-bg: #f1eee8;
}

@media (prefers-color-scheme: dark) {
  :root {
    --bg: #171614;
    --surface: #201f1c;
    --text: #ece8e1;
    --muted: #a29c92;
    --line: #36332e;
    --accent: #e3a443;
    --pass: #6cc07c;
    --fail: #ec8572;
    --code-bg: #2a2825;
  }
}

* { box-sizing: border-box; }

body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font: 16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
}

a { color: var(--accent); }

header.site {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 1rem;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--line);
  background: var(--surface);
}

header.site .brand { font-weight: 700; color: var(--text); text-decoration: none; }
header.site .picker { margin-left: auto; display: flex; gap: 0.5rem; align-items: center; }

main { max-width: 60rem; margin: 0 auto; padding: 1rem; }

h1 { font-size: 1.5rem; margin: 0.5rem 0 1rem; }
h2 { font-size: 1.1rem; margin: 0 0 0.5rem; }

table { width: 100%; border-collapse: collapse; }
th, td { padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--line); text-align: left; }
th { color: var(--muted); font-weight: 600; font-size: 0.85rem; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
tfoot td { font-weight: 600; border-bottom: none; }

.slot, .totals, .notice {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 1rem;
  margin-bottom: 1rem;
  overflow-x: auto;
}

.mark { font-weight: 600; white-space: nowrap; }
.mark.pass { color: var(--pass); }
.mark.fail, .mark.error { color: var(--fail); }

.error-panel { border-color: var(--fail); }

.muted { color: var(--muted); }

pre { background: var(--code-bg); padding: 0.75rem; border-radius: 6px; overflow-x: auto; }
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_web.py -q`
Expected: PASS

- [ ] **Step 8: Run the whole suite and commit**

Run: `uv run python -m pytest -q`
Expected: PASS, 163 tests

```bash
git add pyproject.toml uv.lock src/yolk/web tests/conftest.py tests/test_web.py
git commit -m "feat: serve the plan list, and explain an unready database

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 4: The plan page

**Files:**
- Modify: `src/yolk/web/routes/plans.py`
- Create: `src/yolk/web/templates/plans/detail.html`, `plans/_totals.html`, `plans/_slot.html`
- Test: `tests/test_web_plans.py`

**Interfaces:**
- Consumes: `get_plan(conn, plan_id) -> PlanHeader` (Task 2); `slot_names(conn, profile_id) -> dict[int, str]` (Task 1); `evaluate(conn, plan_id) -> DayEvaluation`; `ConnDep`, `ViewerDep`, `templates` (Task 3); fixtures `seeded`, `client` (Task 3).
- Produces: `GET /plans/{plan_id}`. The partials' context contract, which slice 3 relies on when it swaps them:
  - `plans/_totals.html` needs `evaluation` (a `DayEvaluation`).
  - `plans/_slot.html` needs `slot` (a `SlotEvaluation`) and `slot_names` (a `dict[int, str]`).

**What the page shows (§5.3):**

- A totals bar: one row each for calories, protein, fat, and carbs, with the day total, the profile target, the delta, and a mark. The calorie and protein marks come from `within_tolerance["kcal"]` and `within_tolerance["protein_g"]`. The fat and carb marks come from `within_tolerance["fat_pct"]` and `within_tolerance["carb_pct"]`, because the profile's tolerance for those is a share of calories, not grams. Fiber is not shown: no food in the database records it yet, so it would read 0 everywhere.
- One section per slot, titled with the slot template name, or `Slot N` when the profile has no template for that slot number.
- Each entry: food name, quantity and unit, grams, and its calories, protein, fat, and carbs. Then the slot's totals.
- If `evaluate` raises a `YolkError`, the plan's name and profile still show, and the error message replaces the totals and slots, in an error panel. Status 200: this is a page about a plan with a problem in it, not a failed request.
- An unknown plan id gives 404 with `error.html`.

**Number formats:** calories `%.0f`, grams and macros `%.1f`, deltas with a sign (`%+.0f`, `%+.1f`), quantities `%g` (so `0.5`, `1`, `0.25` render as written).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_web_plans.py`:

```python
from yolk.db.connection import connect
from yolk.planning.evaluate import add_entry, evaluate


def _add_entry_to_seeded_plan(path, plan_id, *, slot_no, unit):
    conn = connect(path)
    food_id = conn.execute(
        "SELECT food_id FROM day_plan_entries WHERE day_plan_id = ? ORDER BY id",
        (plan_id,),
    ).fetchone()["food_id"]
    add_entry(conn, plan_id, slot_no=slot_no, food_id=food_id, qty=1, unit=unit)
    conn.close()


def test_the_plan_page_shows_every_slot_name_and_the_day_kcal_total(client, seeded):
    path, plan_id, spec = seeded
    conn = connect(path)
    kcal = evaluate(conn, plan_id).totals.kcal
    conn.close()

    response = client.get(f"/plans/{plan_id}")
    assert response.status_code == 200
    for slot in spec["slots"]:
        assert slot["name"] in response.text
    assert f"{kcal:.0f}" in response.text


def test_the_plan_page_shows_each_entry_with_its_quantity(client, seeded):
    _, plan_id, spec = seeded
    first = spec["slots"][0]["entries"][0]
    response = client.get(f"/plans/{plan_id}")
    assert first["food"] in response.text
    assert f"{first['qty']:g} {first['unit']}" in response.text


def test_the_seeded_plan_is_marked_within_tolerance_on_every_macro(client, seeded):
    _, plan_id, _ = seeded
    response = client.get(f"/plans/{plan_id}")
    assert response.text.count("Within") == 4
    assert "Outside" not in response.text


def test_a_slot_without_a_template_is_titled_by_number(client, seeded):
    path, plan_id, _ = seeded
    _add_entry_to_seeded_plan(path, plan_id, slot_no=7, unit="g")
    response = client.get(f"/plans/{plan_id}")
    assert "Slot 7" in response.text


def test_an_unknown_unit_renders_inline_not_as_a_500(client, seeded):
    path, plan_id, spec = seeded
    _add_entry_to_seeded_plan(path, plan_id, slot_no=1, unit="handful")
    response = client.get(f"/plans/{plan_id}")
    assert response.status_code == 200
    assert spec["plan_name"] in response.text
    assert "handful" in response.text
    assert "Something went wrong" not in response.text


def test_an_unknown_plan_is_a_404(client):
    response = client.get("/plans/999")
    assert response.status_code == 404
    assert "There is no plan 999" in response.text
```

`"g"` is always a valid unit (it is in `MASS_UNITS`), so slot 7 evaluates cleanly.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_web_plans.py -q`
Expected: FAIL. Requests to `/plans/{id}` return 404 with FastAPI's JSON body, because the route does not exist yet.

- [ ] **Step 3: Add the route**

In `src/yolk/web/routes/plans.py`, extend the imports:

```python
from yolk.errors import YolkError
from yolk.people import slot_names
from yolk.planning.evaluate import evaluate
from yolk.planning.plans import get_plan, plan_summaries
```

and add:

```python
@router.get("/plans/{plan_id}", response_class=HTMLResponse)
def plan_detail(plan_id: int, request: Request, conn: ConnDep, viewer: ViewerDep):
    try:
        plan = get_plan(conn, plan_id)
    except LookupError:
        return templates.TemplateResponse(
            request,
            "error.html",
            {"viewer": viewer, "message": f"There is no plan {plan_id}."},
            status_code=404,
        )
    try:
        evaluation, error = evaluate(conn, plan_id), None
    except YolkError as exc:
        # Shown in place of the totals and slots, naming the food and unit.
        evaluation, error = None, str(exc)
    return templates.TemplateResponse(
        request,
        "plans/detail.html",
        {
            "viewer": viewer,
            "plan": plan,
            "evaluation": evaluation,
            "error": error,
            "slot_names": slot_names(conn, plan.profile_id),
        },
    )
```

- [ ] **Step 4: Write the templates**

Create `src/yolk/web/templates/plans/detail.html`:

```html
{% extends "base.html" %}
{% block title %}{{ plan.name }} · yolk{% endblock %}
{% block content %}
<h1>{{ plan.name }}</h1>
<p class="muted">Profile: {{ plan.profile_name }}</p>
{% if error %}
<section class="notice error-panel">
  <h2>This plan can't be evaluated</h2>
  <p>{{ error }}</p>
</section>
{% else %}
{% include "plans/_totals.html" %}
{% for slot in evaluation.slots %}
{% include "plans/_slot.html" %}
{% endfor %}
{% endif %}
{% endblock %}
```

Create `src/yolk/web/templates/plans/_totals.html`:

```html
{# Needs: evaluation (DayEvaluation). Fat and carb marks judge share of calories, not grams. #}
{% set rows = [
  ("Calories", "kcal", "kcal", "%.0f", "%+.0f", ""),
  ("Protein", "protein_g", "protein_g", "%.1f", "%+.1f", " g"),
  ("Fat", "fat_g", "fat_pct", "%.1f", "%+.1f", " g"),
  ("Carbs", "carb_g", "carb_pct", "%.1f", "%+.1f", " g"),
] %}
<section class="totals" id="totals">
  <h2>Day totals</h2>
  <table>
    <thead>
      <tr><th></th><th class="num">Total</th><th class="num">Target</th><th class="num">Delta</th><th></th></tr>
    </thead>
    <tbody>
    {% for label, field, check, fmt, delta_fmt, suffix in rows %}
      <tr>
        <th scope="row">{{ label }}</th>
        <td class="num">{{ fmt|format(evaluation.totals|attr(field)) }}{{ suffix }}</td>
        <td class="num">{{ fmt|format(evaluation.target|attr(field)) }}{{ suffix }}</td>
        <td class="num">{{ delta_fmt|format(evaluation.deltas|attr(field)) }}{{ suffix }}</td>
        <td>
          {% if evaluation.within_tolerance[check] %}<span class="mark pass">Within</span>
          {% else %}<span class="mark fail">Outside</span>{% endif %}
        </td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
</section>
```

Create `src/yolk/web/templates/plans/_slot.html`:

```html
{# Needs: slot (SlotEvaluation), slot_names (dict[int, str]). #}
<section class="slot" id="slot-{{ slot.slot_no }}">
  <h2>{{ slot_names.get(slot.slot_no, "Slot " ~ slot.slot_no) }}</h2>
  <table>
    <thead>
      <tr>
        <th>Food</th><th class="num">Amount</th><th class="num">Grams</th>
        <th class="num">kcal</th><th class="num">Protein</th>
        <th class="num">Fat</th><th class="num">Carbs</th>
      </tr>
    </thead>
    <tbody>
    {% for entry in slot.entries %}
      <tr>
        <td>{{ entry.food_name }}</td>
        <td class="num">{{ "%g"|format(entry.qty) }} {{ entry.unit }}</td>
        <td class="num">{{ "%.0f"|format(entry.grams) }}</td>
        <td class="num">{{ "%.0f"|format(entry.macros.kcal) }}</td>
        <td class="num">{{ "%.1f"|format(entry.macros.protein_g) }}</td>
        <td class="num">{{ "%.1f"|format(entry.macros.fat_g) }}</td>
        <td class="num">{{ "%.1f"|format(entry.macros.carb_g) }}</td>
      </tr>
    {% endfor %}
    </tbody>
    <tfoot>
      <tr>
        <td colspan="3">Slot total</td>
        <td class="num">{{ "%.0f"|format(slot.totals.kcal) }}</td>
        <td class="num">{{ "%.1f"|format(slot.totals.protein_g) }}</td>
        <td class="num">{{ "%.1f"|format(slot.totals.fat_g) }}</td>
        <td class="num">{{ "%.1f"|format(slot.totals.carb_g) }}</td>
      </tr>
    </tfoot>
  </table>
</section>
```

Inside a `{% for %}` loop, `{% include %}` sees the loop variable, so `_slot.html` gets `slot` from `detail.html`'s loop and `slot_names` from the page context.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_web_plans.py -q`
Expected: PASS

If `test_the_seeded_plan_is_marked_within_tolerance_on_every_macro` counts more than 4, some other text on the page contains "Within". Find it and reword it rather than loosening the test.

- [ ] **Step 6: Run the whole suite and commit**

Run: `uv run python -m pytest -q`
Expected: PASS, 169 tests

```bash
git add src/yolk/web/routes/plans.py src/yolk/web/templates/plans tests/test_web_plans.py
git commit -m "feat: show a plan's slots, entries, and day totals against target

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 5: The person picker

**Files:**
- Create: `src/yolk/web/routes/people.py`
- Modify: `src/yolk/web/app.py`, `src/yolk/web/templates/base.html`
- Test: `tests/test_web_people.py`

**Interfaces:**
- Consumes: `ViewerDep`, `PERSON_COOKIE` (Task 3); `create_person`, `create_profile` from `yolk.people`; `create_day_plan` from `yolk.planning.evaluate`; fixtures `seeded`, `client`.
- Produces: `POST /person` with form field `person_id`. It sets the `yolk_person` cookie when the id names a known person, ignores it otherwise, and always redirects 303 to `/plans`. The picker renders in the header only when there is more than one person.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_web_people.py`:

```python
from yolk.db.connection import connect
from yolk.people import create_person, create_profile
from yolk.planning.evaluate import create_day_plan


def _add_sam(path) -> int:
    conn = connect(path)
    sam = create_person(conn, "Sam")
    profile = create_profile(
        conn, sam, name="rest", effective_on="2026-07-14",
        kcal=2000, fat_pct=40, carb_pct=20, protein_pct=40,
    )
    create_day_plan(conn, sam, profile, name="Sam plan")
    conn.close()
    return sam


def test_with_one_person_there_is_no_picker(client):
    assert 'action="/person"' not in client.get("/plans").text


def test_with_two_people_the_picker_lists_both(client, seeded):
    _add_sam(seeded[0])
    text = client.get("/plans").text
    assert 'action="/person"' in text
    assert "Jen" in text and "Sam" in text


def test_picking_a_person_shows_their_plans(client, seeded):
    path, _, spec = seeded
    sam = _add_sam(path)
    response = client.post("/person", data={"person_id": sam})
    assert response.status_code == 200  # after following the redirect
    assert "Sam plan" in response.text
    assert spec["plan_name"] not in response.text


def test_picking_an_unknown_person_changes_nothing(client, seeded):
    path, _, spec = seeded
    _add_sam(path)
    response = client.post("/person", data={"person_id": 999})
    assert spec["plan_name"] in response.text
    assert "Sam plan" not in response.text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_web_people.py -q`
Expected: `test_with_one_person_there_is_no_picker` passes already; the other three FAIL (no picker markup, and `POST /person` returns 404 or 405).

- [ ] **Step 3: Implement**

Create `src/yolk/web/routes/people.py`:

```python
"""Choosing whose plans to show."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form
from fastapi.responses import RedirectResponse

from yolk.web.deps import PERSON_COOKIE, ViewerDep

router = APIRouter()


@router.post("/person")
def choose_person(person_id: Annotated[int, Form()], viewer: ViewerDep):
    response = RedirectResponse("/plans", status_code=303)
    if any(person.id == person_id for person in viewer.people):
        response.set_cookie(PERSON_COOKIE, str(person_id), httponly=True, samesite="lax")
    return response
```

In `src/yolk/web/app.py`, change `from yolk.web.routes import plans` to `from yolk.web.routes import people, plans`, and after `app.include_router(plans.router)` add:

```python
    app.include_router(people.router)
```

In `src/yolk/web/templates/base.html`, replace `{% block picker %}{% endblock %}` with:

```html
    {% if viewer and viewer.people|length > 1 %}
    <form class="picker" method="post" action="/person">
      <label for="person_id">Showing</label>
      <select id="person_id" name="person_id">
        {% for p in viewer.people %}
        <option value="{{ p.id }}"{% if p.id == viewer.person.id %} selected{% endif %}>{{ p.name }}</option>
        {% endfor %}
      </select>
      <button type="submit">Switch</button>
    </form>
    {% endif %}
```

`viewer` is undefined on the setup and unexpected-error pages. Jinja treats an undefined name as false in an `{% if %}`, so those pages render without a picker.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_web_people.py -q`
Expected: PASS

- [ ] **Step 5: Run the whole suite and commit**

Run: `uv run python -m pytest -q`
Expected: PASS, 173 tests

```bash
git add src/yolk/web/routes/people.py src/yolk/web/app.py src/yolk/web/templates/base.html tests/test_web_people.py
git commit -m "feat: pick whose plans to show when there is more than one person

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 6: `yolk serve`, the README, and a look in the browser

**Files:**
- Modify: `src/yolk/cli.py`
- Modify: `README.md`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `create_app(db_path)` (Task 3); `database_path()`; the existing `db_path` fixture in `tests/test_cli.py`, which points `YOLK_DB` at a temporary file.
- Produces: `yolk serve [--port N]`, default port 8000, always bound to `127.0.0.1`. It does not require the database to exist: the pages explain what to run.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
def test_serve_binds_to_localhost_and_uses_the_resolved_database(
    db_path, monkeypatch, capsys
):
    calls = []
    monkeypatch.setattr(
        "yolk.cli.uvicorn.run", lambda app, **kwargs: calls.append((app, kwargs))
    )
    assert main(["serve", "--port", "8123"]) == 0
    [(app, kwargs)] = calls
    assert kwargs == {"host": "127.0.0.1", "port": 8123}
    assert app.state.db_path == db_path
    assert "http://127.0.0.1:8123" in capsys.readouterr().out


def test_serve_defaults_to_port_8000(db_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "yolk.cli.uvicorn.run", lambda app, **kwargs: calls.append(kwargs)
    )
    main(["serve"])
    assert calls == [{"host": "127.0.0.1", "port": 8000}]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_cli.py -q`
Expected: the two new tests FAIL. argparse rejects `serve` as an invalid choice and exits with `SystemExit: 2`.

- [ ] **Step 3: Implement**

In `src/yolk/cli.py`, change the module docstring's first line to:

```python
"""The `yolk` command: create, migrate, export, import, and serve the database."""
```

Add `import uvicorn` with the other third-party imports, and `from yolk.web.app import create_app` with the `yolk` imports. Add a constant and a command after `_cmd_import`:

```python
# The app has no authentication, so it must never listen beyond this machine.
LOCALHOST = "127.0.0.1"


def _cmd_serve(args: argparse.Namespace) -> int:
    path = database_path()
    print(f"Serving {path} at http://{LOCALHOST}:{args.port} (Ctrl+C to stop)")
    uvicorn.run(create_app(path), host=LOCALHOST, port=args.port)
    return 0
```

In `_parser()`, before `return parser`:

```python
    serve = sub.add_parser("serve", help="run the web app on this machine")
    serve.add_argument("--port", type=int, default=8000)
    serve.set_defaults(func=_cmd_serve)
```

The test patches `yolk.cli.uvicorn.run`, which is the same object as `uvicorn.run`. That only works because the code calls `uvicorn.run(...)` through the module. Do not change it to `from uvicorn import run`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_cli.py -q`
Expected: PASS

- [ ] **Step 5: Update the README**

In `README.md`, add a row to the command table, after the `import` row:

```markdown
| `uv run python -m yolk serve [--port N]` | Run the web app at http://127.0.0.1:8000 |
```

and append after the `YOLK_DB` sentence:

```markdown
## Looking at a plan

```bash
uv run python -m yolk serve
```

Open http://127.0.0.1:8000. The plan list shows each plan and whether the day lands
within the profile's tolerances. A plan page shows the day totals against the target,
then every slot with its foods. The app only listens on this machine and has no login.
If the database is missing or needs a migration, the page says which command to run;
the app never creates or migrates the database itself.
```

- [ ] **Step 6: Run the whole suite and commit**

Run: `uv run python -m pytest -q`
Expected: PASS, 175 tests

```bash
git add src/yolk/cli.py tests/test_cli.py README.md
git commit -m "feat: add yolk serve to run the web app on localhost

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 7: Look at it in a real browser**

This step checks the parts the tests cannot: layout, readability, and the real database. It changes no files.

1. Run `uv run python -m yolk migrate`. Expected: `Already up to date.` If there is no `yolk.db` yet, run `uv run python -m yolk init --seed` instead.
2. Start the server in the background: `uv run python -m yolk serve`.
3. Open `http://127.0.0.1:8000`. It should redirect to `/plans` and list Keto Meal Plan A as within tolerance.
4. Open the plan. Check that the calorie total reads 2146 against a 2150 target, that all six slot names appear in order, and that every macro row is marked Within.
5. Narrow the window to phone width (about 375 px). Tables may scroll sideways inside their cards; the page itself must not.
6. Stop the server.

Record anything that looks wrong as a follow-up rather than fixing it inside this task.

---

## Done when

- `uv run python -m pytest` passes, at 175 tests.
- `uv run python -m yolk serve` shows Keto Meal Plan A with the golden test's totals (spec §1, success criterion 1).
- `grep -rn "execute(" src/yolk/web` prints nothing.
- A missing database, a database behind on migrations, and an empty database each render a page naming the command to run, and none of them creates or changes a file.
- `git status --short` shows no `yolk.db`.

Slice 3 (editing by hand) gets its own plan. It adds migration `0002_draft_status.sql`, `planning/drafts.py`, `search_library`, and vendors htmx.
