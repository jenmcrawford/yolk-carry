# Food Search and Egg Icon Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `/foods` page that searches the food library by name or brand and shows each food's role, per-100 g macros, and units, plus a small fried-egg icon beside "yolk" in the header.

**Architecture:** One new library function, `search_library()` in `foods.py`, returns frozen `FoodSummary` dataclasses, so the web layer stays free of SQL. A new route module renders a full page and a results partial, `foods/_results.html`, which Part B's food picker will reuse. The egg is inline SVG in `base.html`, so it renders with the page and works offline.

**Tech Stack:** Python 3.14, `uv`, FastAPI 0.142, Starlette 1.7, Jinja2, stdlib `sqlite3`, `pytest` with FastAPI's `TestClient`.

**Spec:** [2026-10-01-plan-and-search-design.md](../specs/2026-10-01-plan-and-search-design.md), Part A (§3). Part B (planning) gets its own plan.

## Global Constraints

- Python `>=3.14`, managed by `uv`.
- **Run tools as modules, not as console scripts.** Windows Smart App Control blocks the generated launchers in `.venv/Scripts/`. `uv run python -m pytest` works and `uv run pytest` does not.
- No new dependencies of any kind.
- **The web layer does no arithmetic and no SQL.** No `conn.execute` anywhere under `src/yolk/web/`. Formatting a number in a template (`"%.0f"|format(x)`, `"%g"|format(x)`) is display, not arithmetic, and is allowed.
- **Templates consume library dataclasses directly.** No view-model layer.
- **Every fragment is a partial, and full pages include the same partials.**
- Portable SQL only: it must also run on Postgres. Placeholders stay `?`. Case-insensitive matching is written `lower(column) LIKE ?`, not SQLite's case-insensitive `LIKE` default and not `ILIKE`. New code annotates connections as `yolk.db.Connection`.
- Library tests use the `db` fixture (`:memory:`). Web tests use the `seeded` and `client` fixtures in `tests/conftest.py`, which build a seeded file under pytest's `tmp_path`; `client` is `TestClient(create_app(path), base_url="http://127.0.0.1")`. Any other `TestClient` must also pass `base_url="http://127.0.0.1"`, because the app's `TrustedHostMiddleware` refuses the default `testserver` host. No test touches the repository's `yolk.db`.
- Starlette 1.x: `templates.TemplateResponse(request, "name.html", {...})`, with the request first.
- Every page template receives `viewer` (from `ViewerDep`), so the header's person picker keeps working.
- The full suite is `uv run python -m pytest`. It passes at 178 tests with one known warning (`StarletteDeprecationWarning` about `httpx2`) before this plan starts, and must pass at the end of every task with no new warnings.
- Commit at the end of every task. Every commit message ends with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

---

## File Structure

**Created:**

| Path | Responsibility |
|---|---|
| `src/yolk/web/routes/foods.py` | `GET /foods` |
| `src/yolk/web/templates/foods/list.html` | The Foods page: search form plus results |
| `src/yolk/web/templates/foods/_results.html` | Results partial, reused by Part B's picker |
| `tests/test_search.py` | `search_library` tests |
| `tests/test_web_foods.py` | Foods page and egg icon tests |

**Modified:**

| Path | Change |
|---|---|
| `src/yolk/foods.py` | Gains `FoodSummary` and `search_library()` |
| `src/yolk/web/app.py` | Includes the foods router |
| `src/yolk/web/templates/base.html` | **Foods** nav link; the egg icon |
| `src/yolk/web/static/app.css` | Nav, search form, results card, badge, egg |

---

## Task 1: Search the library

**Files:**
- Modify: `src/yolk/foods.py`
- Test: `tests/test_search.py` (create)

**Interfaces:**
- Consumes: `yolk.foods.create_item(conn, *, name, role, macros, brand="", source="manual", units=None, verified=False, ...) -> int`; `yolk.macros.Macros`.
- Produces:
  - `yolk.foods.FoodSummary`, a frozen dataclass: `id: int`, `name: str`, `brand: str`, `kind: str`, `role: str`, `verified: bool`, `per_100g: Macros | None`, `units: list[tuple[str, float]]`
  - `yolk.foods.search_library(conn: Connection, query: str) -> list[FoodSummary]`

**Behaviour:**
- Matches foods whose name or brand contains the query, case-insensitively.
- `%`, `_` and `\` in the query match themselves, not as wildcards. They are escaped, with `ESCAPE '\'` in the SQL.
- An empty or whitespace-only query returns every food.
- Results are ordered by `lower(name)`, then `lower(brand)`, then `id`, so "beef jerky" sorts between "Avocado" and "Chicken" instead of after every capitalised name.
- `per_100g` is `None` exactly when a recipe's macros were never computed (`kcal_100g IS NULL`). This does not raise, unlike `macros_per_100g`: one unfinished recipe must not break the whole list. A NULL fiber is 0, as in `macros_per_100g`.
- `units` lists the food's `food_units` rows as `(unit, grams)`, ordered by unit.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_search.py`:

```python
from yolk.foods import create_item, search_library
from yolk.macros import Macros

SOME = Macros(kcal=100, protein_g=10, fat_g=5, carb_g=2)


def _names(results):
    return [food.name for food in results]


def test_search_matches_the_name_case_insensitively(db):
    create_item(db, name="Chicken Breast", role="protein", macros=SOME)
    create_item(db, name="Pork Rinds", role="protein", macros=SOME)
    assert _names(search_library(db, "chicken")) == ["Chicken Breast"]
    assert _names(search_library(db, "CHICK")) == ["Chicken Breast"]


def test_search_matches_the_brand(db):
    create_item(db, name="Mayonnaise", brand="Primal Kitchen", role="fat", macros=SOME)
    create_item(db, name="Olive Oil", role="fat", macros=SOME)
    assert _names(search_library(db, "primal")) == ["Mayonnaise"]


def test_an_empty_query_lists_everything_ordered_by_name_ignoring_case(db):
    create_item(db, name="Chicken", role="protein", macros=SOME)
    create_item(db, name="beef jerky", role="protein", macros=SOME)
    create_item(db, name="Avocado", role="fat", macros=SOME)
    expected = ["Avocado", "beef jerky", "Chicken"]
    assert _names(search_library(db, "")) == expected
    assert _names(search_library(db, "   ")) == expected


def test_wildcard_characters_in_the_query_match_themselves(db):
    create_item(db, name="Milk 2%", role="beverage", macros=SOME)
    create_item(db, name="Oats", role="carb", macros=SOME)
    assert _names(search_library(db, "%")) == ["Milk 2%"]
    assert _names(search_library(db, "_")) == []


def test_a_summary_carries_macros_units_and_review_state(db):
    create_item(
        db, name="Mayonnaise", brand="Primal Kitchen", role="fat",
        macros=Macros(kcal=680, protein_g=0, fat_g=75, carb_g=0),
        units={"tbsp": 14.0, "cup": 224.0},
    )
    [food] = search_library(db, "mayo")
    assert (food.kind, food.role, food.brand, food.verified) == (
        "item", "fat", "Primal Kitchen", False
    )
    assert food.per_100g.kcal == 680
    assert food.per_100g.fat_g == 75
    assert food.units == [("cup", 224.0), ("tbsp", 14.0)]


def test_a_recipe_without_computed_macros_is_listed_without_them(db):
    db.execute(
        "INSERT INTO foods (kind, name, role, source) "
        "VALUES ('recipe', 'Chili', 'protein', 'computed')"
    )
    db.commit()
    [food] = search_library(db, "chili")
    assert food.kind == "recipe"
    assert food.per_100g is None
    assert food.units == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_search.py -q`
Expected: FAIL at import with `ImportError: cannot import name 'search_library' from 'yolk.foods'`

- [ ] **Step 3: Implement**

In `src/yolk/foods.py`, add this stdlib import directly above `from datetime import date, datetime, timezone`:

```python
from dataclasses import dataclass
```

Then add after `portion_macros`:

```python
@dataclass(frozen=True)
class FoodSummary:
    id: int
    name: str
    brand: str
    kind: str
    role: str
    verified: bool
    # None exactly when a recipe's macros were never computed.
    per_100g: Macros | None
    units: list[tuple[str, float]]


def _like_pattern(query: str) -> str:
    """A LIKE pattern matching `query` anywhere, with its wildcards taken literally."""
    escaped = (
        query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    )
    return f"%{escaped}%"


def search_library(conn: Connection, query: str) -> list[FoodSummary]:
    """Foods whose name or brand contains `query`, ignoring case.

    An empty query lists every food. Unlike macros_per_100g, a recipe whose
    macros were never computed is returned with per_100g=None rather than
    raising, so one unfinished recipe cannot break the whole list.
    """
    pattern = _like_pattern(query.strip().lower())
    rows = conn.execute(
        "SELECT id, name, brand, kind, role, verified, kcal_100g, "
        "protein_g_100g, fat_g_100g, carb_g_100g, fiber_g_100g FROM foods "
        "WHERE lower(name) LIKE ? ESCAPE '\\' OR lower(brand) LIKE ? ESCAPE '\\' "
        "ORDER BY lower(name), lower(brand), id",
        (pattern, pattern),
    ).fetchall()

    units: dict[int, list[tuple[str, float]]] = {}
    for row in conn.execute(
        "SELECT food_id, unit, grams FROM food_units ORDER BY food_id, unit"
    ):
        units.setdefault(row["food_id"], []).append((row["unit"], row["grams"]))

    return [
        FoodSummary(
            id=row["id"],
            name=row["name"],
            brand=row["brand"],
            kind=row["kind"],
            role=row["role"],
            verified=bool(row["verified"]),
            per_100g=None
            if row["kcal_100g"] is None
            else Macros(
                kcal=row["kcal_100g"],
                protein_g=row["protein_g_100g"] or 0.0,
                fat_g=row["fat_g_100g"] or 0.0,
                carb_g=row["carb_g_100g"] or 0.0,
                fiber_g=row["fiber_g_100g"] or 0.0,
            ),
            units=units.get(row["id"], []),
        )
        for row in rows
    ]
```

The SQL string `'\\'` in Python source is the two characters `'\'` in the SQL, which is the `ESCAPE` clause's single backslash. Reading every unit row is deliberate: the library holds tens of foods, and one query is simpler than an `IN (...)` list built per search.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_search.py -q`
Expected: PASS, 6 tests

- [ ] **Step 5: Run the whole suite and commit**

Run: `uv run python -m pytest -q`
Expected: PASS, 184 tests, the one known warning

```bash
git add src/yolk/foods.py tests/test_search.py
git commit -m "feat: search the food library by name or brand

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 2: The Foods page

**Files:**
- Create: `src/yolk/web/routes/foods.py`
- Create: `src/yolk/web/templates/foods/list.html`, `src/yolk/web/templates/foods/_results.html`
- Modify: `src/yolk/web/app.py`, `src/yolk/web/templates/base.html`, `src/yolk/web/static/app.css`
- Test: `tests/test_web_foods.py` (create)

**Interfaces:**
- Consumes: `search_library(conn, query) -> list[FoodSummary]` (Task 1); `ConnDep`, `ViewerDep` from `yolk.web.deps`; `templates` from `yolk.web.templating`; fixtures `seeded` → `(path, plan_id, spec)` and `client`.
- Produces:
  - `yolk.web.routes.foods.router: APIRouter`, serving `GET /foods?q=`
  - The partial `foods/_results.html`, whose context is `foods` (a `list[FoodSummary]`) and `query` (a `str`). Part B adds an action column to it; nothing else may depend on its internals.

**What the page shows (spec §3.3):**
- A heading "Foods" and a plain GET form: a text input named `q`, holding the current query, and a **Search** button. No JavaScript.
- A results table with these columns: Food (the name; the brand after it in muted text when present; an "unchecked" badge when `verified` is false), Role, kcal, Protein, Fat, Carbs (all per 100 g), and Units.
  - Units are rendered `unit = grams g` and joined with `, `, for example `packet = 22 g`. Grams use `%g`.
  - kcal uses `%.0f`; the other macros use `%.1f`.
  - When `per_100g` is `None`, the four macro cells become one cell reading "not computed".
- No results and a non-empty query: `No foods match “<query>”.` (curly quotes, so autoescaping leaves the text intact). No results and an empty query: `No foods yet.`
- A **Foods** link in the header nav, after **Plans**.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_web_foods.py`:

```python
from yolk.db.connection import connect
from yolk.foods import create_item
from yolk.macros import Macros


def _add_food(path, **kwargs):
    conn = connect(path)
    create_item(conn, **kwargs)
    conn.close()


def test_the_foods_page_lists_seeded_foods(client):
    response = client.get("/foods")
    assert response.status_code == 200
    assert "Grilled or baked chicken breast" in response.text
    assert "Pork Rinds" in response.text


def test_a_query_narrows_the_list(client):
    response = client.get("/foods", params={"q": "chicken"})
    assert "Grilled or baked chicken breast" in response.text
    assert "Pork Rinds" not in response.text
    assert 'value="chicken"' in response.text


def test_a_food_shows_its_units_in_grams(client):
    response = client.get("/foods", params={"q": "buff chick"})
    assert "packet = 22 g" in response.text


def test_no_match_says_so(client):
    response = client.get("/foods", params={"q": "zzzz"})
    assert response.status_code == 200
    assert "No foods match" in response.text
    assert "zzzz" in response.text


def test_the_header_links_to_foods(client):
    assert 'href="/foods"' in client.get("/plans").text


def test_an_unverified_food_carries_a_badge(client, seeded):
    assert "unchecked" not in client.get("/foods").text
    _add_food(
        seeded[0], name="Cottage cheese", role="protein",
        macros=Macros(kcal=98, protein_g=11, fat_g=4.3, carb_g=3.4),
    )
    response = client.get("/foods", params={"q": "cottage"})
    assert "unchecked" in response.text


def test_a_recipe_without_macros_says_not_computed(client, seeded):
    conn = connect(seeded[0])
    conn.execute(
        "INSERT INTO foods (kind, name, role, source) "
        "VALUES ('recipe', 'Chili', 'protein', 'computed')"
    )
    conn.commit()
    conn.close()
    response = client.get("/foods", params={"q": "chili"})
    assert "not computed" in response.text
```

All seeded foods are verified, which is why the first assertion of the badge test holds.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_web_foods.py -q`
Expected: FAIL. `/foods` returns FastAPI's 404, and the header has no `/foods` link.

- [ ] **Step 3: Add the route**

Create `src/yolk/web/routes/foods.py`:

```python
"""The food library page."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from yolk.foods import search_library
from yolk.web.deps import ConnDep, ViewerDep
from yolk.web.templating import templates

router = APIRouter()


@router.get("/foods", response_class=HTMLResponse)
def food_list(request: Request, conn: ConnDep, viewer: ViewerDep, q: str = ""):
    return templates.TemplateResponse(
        request,
        "foods/list.html",
        {"viewer": viewer, "query": q, "foods": search_library(conn, q)},
    )
```

In `src/yolk/web/app.py`, change `from yolk.web.routes import people, plans` to `from yolk.web.routes import foods, people, plans`, and after `app.include_router(people.router)` add:

```python
    app.include_router(foods.router)
```

- [ ] **Step 4: Write the templates**

Create `src/yolk/web/templates/foods/list.html`:

```html
{% extends "base.html" %}
{% block title %}Foods · yolk{% endblock %}
{% block content %}
<h1>Foods</h1>
<form class="search" method="get" action="/foods" role="search">
  <label class="visually-hidden" for="q">Search foods</label>
  <input id="q" name="q" type="search" value="{{ query }}" placeholder="Name or brand">
  <button type="submit">Search</button>
</form>
{% include "foods/_results.html" %}
{% endblock %}
```

Create `src/yolk/web/templates/foods/_results.html`:

```html
{# Needs: foods (list[FoodSummary]), query (str). #}
{% if foods %}
<section class="results">
  <table>
    <thead>
      <tr>
        <th>Food</th><th>Role</th>
        <th class="num">kcal</th><th class="num">Protein</th>
        <th class="num">Fat</th><th class="num">Carbs</th>
        <th>Units</th>
      </tr>
    </thead>
    <tbody>
    {% for food in foods %}
      <tr>
        <td>
          {{ food.name }}{% if food.brand %} <span class="muted">{{ food.brand }}</span>{% endif %}
          {% if not food.verified %}<span class="badge">unchecked</span>{% endif %}
        </td>
        <td>{{ food.role }}</td>
        {% if food.per_100g %}
        <td class="num">{{ "%.0f"|format(food.per_100g.kcal) }}</td>
        <td class="num">{{ "%.1f"|format(food.per_100g.protein_g) }}</td>
        <td class="num">{{ "%.1f"|format(food.per_100g.fat_g) }}</td>
        <td class="num">{{ "%.1f"|format(food.per_100g.carb_g) }}</td>
        {% else %}
        <td colspan="4" class="muted">not computed</td>
        {% endif %}
        <td>{% for unit, grams in food.units %}{{ unit }} = {{ "%g"|format(grams) }} g{% if not loop.last %}, {% endif %}{% endfor %}</td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
  <p class="muted">Macros per 100 g.</p>
</section>
{% elif query %}
<p>No foods match “{{ query }}”.</p>
{% else %}
<p>No foods yet.</p>
{% endif %}
```

In `src/yolk/web/templates/base.html`, replace `<nav><a href="/plans">Plans</a></nav>` with:

```html
    <nav><a href="/plans">Plans</a><a href="/foods">Foods</a></nav>
```

- [ ] **Step 5: Style it**

In `src/yolk/web/static/app.css`:

Change the card rule's selector from `.slot, .totals, .notice {` to:

```css
.slot, .totals, .notice, .results {
```

Append:

```css
header.site nav { display: flex; gap: 1rem; }

form.search { display: flex; gap: 0.5rem; margin-bottom: 1rem; }
form.search input {
  flex: 1;
  min-width: 0;
  padding: 0.4rem 0.6rem;
  font: inherit;
  color: var(--text);
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 6px;
}

.badge {
  display: inline-block;
  margin-left: 0.35rem;
  padding: 0 0.45rem;
  border-radius: 999px;
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--fail);
  background: var(--code-bg);
}

.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_web_foods.py -q`
Expected: PASS, 7 tests

- [ ] **Step 7: Run the whole suite and commit**

Run: `uv run python -m pytest -q`
Expected: PASS, 191 tests, the one known warning. Also run `grep -rn "execute(" src/yolk/web`; it must print nothing.

```bash
git add src/yolk/web/routes/foods.py src/yolk/web/templates/foods src/yolk/web/app.py src/yolk/web/templates/base.html src/yolk/web/static/app.css tests/test_web_foods.py
git commit -m "feat: add a Foods page that searches the library

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 3: The egg icon

**Files:**
- Modify: `src/yolk/web/templates/base.html`, `src/yolk/web/static/app.css`
- Test: `tests/test_web_foods.py`

**Interfaces:**
- Consumes: fixtures `client`; `create_app` from `yolk.web.app`; `TestClient`.
- Produces: an inline `<svg class="egg">` inside the header's brand link on every page, including the setup and error pages, which extend `base.html` too.

**The icon (spec §3.1):** a flat fried egg. A slightly wavy egg white `#FFF8EC`, a round yolk `#F4B63F` with a lighter highlight `#FBD98B`, and outline `#3A2F26`. It is about 22 px tall and `aria-hidden="true"`. The link's accessible text stays "yolk". The colours are fixed and do not change in dark mode: the outline keeps the white egg visible on the dark header.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_web_foods.py`:

```python
def test_the_header_shows_the_egg_beside_yolk(client):
    text = client.get("/plans").text
    assert '<svg class="egg"' in text
    assert 'aria-hidden="true"' in text
    assert "</svg>yolk</a>" in text


def test_the_egg_shows_on_the_setup_page_too(tmp_path):
    from fastapi.testclient import TestClient

    from yolk.web.app import create_app

    client = TestClient(create_app(tmp_path / "absent.db"), base_url="http://127.0.0.1")
    response = client.get("/plans")
    assert response.status_code == 503
    assert '<svg class="egg"' in response.text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_web_foods.py -q`
Expected: the two new tests FAIL on `'<svg class="egg"' in ...`.

- [ ] **Step 3: Add the icon**

In `src/yolk/web/templates/base.html`, replace `<a class="brand" href="/plans">yolk</a>` with:

```html
    <a class="brand" href="/plans"><svg class="egg" viewBox="0 0 32 28" width="25" height="22" aria-hidden="true" focusable="false"><path d="M5 10 C2 14 3 20 7 22 C9 25 13 26 16 25 C19 27 24 25 26 22 C30 20 31 14 28 10 C27 6 23 3 19 4 C16 2 12 2 10 4 C7 5 6 7 5 10 Z" fill="#FFF8EC" stroke="#3A2F26" stroke-width="1.5" stroke-linejoin="round"/><circle cx="16" cy="14" r="6" fill="#F4B63F" stroke="#3A2F26" stroke-width="1.5"/><circle cx="14" cy="12" r="1.8" fill="#FBD98B"/></svg>yolk</a>
```

Keep it on one line, exactly as written, so that `</svg>yolk</a>` is contiguous. The test relies on that, and it prevents whitespace from appearing between the icon and the word.

In `src/yolk/web/static/app.css`, replace the rule `header.site .brand { font-weight: 700; color: var(--text); text-decoration: none; }` with:

```css
header.site .brand {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  font-weight: 700;
  color: var(--text);
  text-decoration: none;
}
header.site .egg { flex: none; display: block; }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_web_foods.py -q`
Expected: PASS, 9 tests

- [ ] **Step 5: Run the whole suite and commit**

Run: `uv run python -m pytest -q`
Expected: PASS, 193 tests, the one known warning

```bash
git add src/yolk/web/templates/base.html src/yolk/web/static/app.css tests/test_web_foods.py
git commit -m "feat: put a fried egg beside yolk in the header

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 6: Look at it in a real browser**

This step changes no files. The controller does it, not the implementer.

1. Restart the `yolk` preview server (`.claude/launch.json`) so it serves the new code.
2. Open `http://localhost:8000/foods`. Check that every seeded food is listed, and that searching "chicken" narrows the list to the chicken breast.
3. Look at the header in light mode and in dark mode. The egg must be crisp and vertically centred beside "yolk", and readable on both backgrounds.
4. Check at phone width (375 px). The page must not scroll sideways; the results table may scroll inside its card.

Record anything that looks wrong as a follow-up rather than fixing it inside this task.

---

## Done when

- `uv run python -m pytest` passes at 193 tests, with only the one known warning.
- `/foods` lists and searches the library, and the header shows the egg on every page.
- `grep -rn "execute(" src/yolk/web` prints nothing.
- `git status --short` shows no `yolk.db`.

Part B (planning: drafts, new and copied plans, editing meals) gets its own plan from spec §4–§6.
