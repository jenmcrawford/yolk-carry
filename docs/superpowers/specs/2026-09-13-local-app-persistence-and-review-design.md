# Local App, Persistence, and Food Review — Design

**Date:** 2026-09-13
**Status:** Approved in brainstorming, not yet implemented
**Repo:** `yolk-carry` (package name: `yolk`)
**Builds on:** [`2026-08-09-adaptive-meal-planning-design.md`](2026-08-09-adaptive-meal-planning-design.md). Where
this document disagrees with that one, this one wins; §11 lists every amendment.

---

## 1. Goal

The library works and is tested, but nothing persists and nothing is visible. There is no
database file, no way to create one, and no way to look at a plan except by reading the
dataclasses `evaluate()` returns. The stated pain, in order of priority, is **"I can't see a
plan."**

This design adds three things:

1. **Persistence.** A real database at a known path, created and upgraded by command, with a
   committed text export for history and backup.
2. **A local web app** for reading plans, editing them safely, and adding foods and recipes.
3. **A review state for foods**, so anything entered by hand or imported shows as unchecked
   until a human has looked at it.

It is built for one person on this machine first. It must not close the door on sharing the
food library with one other person later, which is when Postgres and hosting come in (§10).

### Success criteria

1. A single command turns an empty checkout into a database holding Keto Plan A, and the app
   shows that plan with the same totals the golden test asserts.
2. Editing a plan never changes the saved plan until an explicit commit, and a test proves it.
3. A recipe can be built in the browser from library foods, USDA results, or hand-entered
   labels, and every food created along the way appears in the review queue.
4. The committed export round-trips: export, import into a fresh database, export again,
   byte-identical.
5. Nothing added here makes a later Postgres port harder than it is today.

---

## 2. Decisions

| Question | Decision |
|---|---|
| App reach | Localhost first. One other person later, via hosting (§10). |
| What gets shared later | The food library. Everything else stays per person. The schema already splits this way. |
| App stack | FastAPI, Jinja templates, HTMX. Server-rendered, one language, one process. |
| Is the database file committed? | **No.** Reverses the original spec. A text export is committed instead (§4.2). |
| Editing model | Scratch mode: edits go to a draft beside the original, and nothing is saved until an explicit commit. |
| Review gate | None. Unverified foods work everywhere and carry a badge. Review is a to-do list, not a gate. |
| Review state | The existing `foods.verified` flag. No new column. |
| Postgres | A rule, not a build item. Two free portability changes now, nothing abstracted (§9). |

---

## 3. Sequencing

Six slices. Each ships something usable, and each gets its own implementation plan. This
document specifies slices 1 through 4 in detail. Slices 5 and 6 are already specified in the
original design's §5 and are listed here only to fix their position.

| # | Slice | Delivers | Depends on |
|---|---|---|---|
| 1 | Persistence | A seeded database file, migrations, export and import | — |
| 2 | Read a plan | Plan list and plan page in the browser | 1 |
| 3 | Edit by hand | Drafts, quantity edits, swaps, add and remove, commit | 2 |
| 4 | Foods, recipes, review | Recipe builder, USDA and manual entry, review queue | 3 (reuses its food search) |
| 5 | Solver | `resolve_flex()` and `substitute()`; a swap re-balances the day | 3 |
| 6 | Fit | `fit()`: where does a new food go, and how much | 5 |

Protocols, inventory, gap lists, and Excel export keep their place in the original spec's
sequencing and are not scheduled by this document.

---

## 4. Slice 1 — Persistence

### 4.1 Where the database lives

The path is resolved in one function, `yolk.config.database_path()`:

1. The `YOLK_DB` environment variable, if set (read through the existing `.env` loading).
2. Otherwise `yolk.db` at the repository root.

`.gitignore` gains `yolk.db`, `yolk.db-journal`, `yolk.db-wal`, and `yolk.db-shm`. Tests keep
using `:memory:` and never touch the resolved path.

### 4.2 The file is not committed; an export is

The original spec put the SQLite file under git. That is reversed. A binary database in git
has no readable diffs, cannot merge, turns each session into an opaque blob commit, and breaks
outright once a second person writes to it.

Instead:

- **`yolk export`** writes every table to `data/<table>.json`: a JSON array of row objects,
  ordered by primary key, keys sorted, two-space indent, trailing newline. Output is
  deterministic, so an unchanged database produces no diff. `schema_version` is exported too,
  and import refuses an export whose version does not match the code's latest migration.
- **`yolk import`** loads that directory into a freshly migrated, **empty** database with
  explicit ids, in foreign-key dependency order, in one transaction. It refuses a database that
  already has rows in any table other than `schema_version`.
- `data/` is committed. It is the backup, the history, and later the thing handed to another
  person.

JSON rather than a SQL dump because a SQL dump is SQLite dialect, and JSON loads into Postgres
just as easily.

**Check before the first export commit:** the export contains plans, profiles, and inventory.
If the GitHub repository is public, those become public. `examples/` already contains
named meal-plan PDFs, so this may already be accepted, but it should be a deliberate choice.

### 4.3 Commands

A thin CLI at `src/yolk/cli.py`, exposed as the `yolk` console script in `pyproject.toml`,
using `argparse` subcommands:

| Command | Does |
|---|---|
| `yolk init [--seed]` | Creates the database if absent and applies all pending migrations. `--seed` then loads Keto Plan A, and refuses if the database already holds any plan. Running `yolk init` again on an up-to-date database is a no-op. |
| `yolk migrate` | Applies pending migrations to an existing database. |
| `yolk export` | §4.2 |
| `yolk import` | §4.2 |
| `yolk serve` | Starts the web app on `127.0.0.1` (§5). Bound to localhost only. |

### 4.4 Migrations

- Numbered SQL files in `src/yolk/db/migrations/`, named `NNNN_description.sql`.
- The current `schema.sql` becomes `0001_baseline.sql`. There is **one source of truth**:
  a fresh database, including every test's in-memory database, is built by applying every
  migration in order. `create_schema()` keeps its name and signature and calls the runner, so
  `tests/conftest.py` does not change.
- A `schema_version` table records each applied migration number and when it was applied.
- Forward only. No down migrations.

**SQLite rebuild procedure.** SQLite cannot alter a CHECK constraint, so changing one means
rebuilding the table. The runner handles the part that is easy to get wrong:

1. `PRAGMA foreign_keys = OFF`, outside any transaction. With enforcement off, dropping the
   old table does not fire `ON DELETE CASCADE` on its children.
2. Run the migration in a transaction: create the new table, copy rows, drop the old one,
   rename, recreate indexes.
3. `PRAGMA foreign_key_check`. Any row returned aborts and rolls back.
4. `PRAGMA foreign_keys = ON`.

The first migration that needs this is slice 3's `0002_draft_status.sql` (§6.1).

### 4.5 Seed

`src/yolk/seed.py` exposes `seed_keto_plan_a(conn)`. The plan-building loop moves out of
`tests/test_golden_keto_a.py` into this module, and the golden test calls it. One code path,
so the test and the seeder cannot drift.

The seed creates:

- The person Jen, and the `training` profile from the fixture.
- One slot template per fixture slot. The slot name is stored whole. `time_of_day` is parsed
  from the name's leading time, so `"Meal 1 - 6:30am Wake Up"` gives `06:30`. A name with no
  parseable time raises.
- Every food in the fixture, with the entry's `source_note` stored in `foods.notes`, and
  `verified = 1` with `verified_on` set to the seed date. Each of these carries a citation to a
  product label or a USDA id and was checked when the fixture was built.
- The plan and its entries.

The fixture stays at `tests/fixtures/keto_plan_a.json`. Seeding is a development and
first-run convenience, and the fixture is not packaged.

---

## 5. Slice 2 — Read a plan

### 5.1 Layout

```
src/yolk/web/
  app.py            -- create_app(); mounts routes, templates, static
  deps.py           -- per-request connection; current person
  routes/
    plans.py
  templates/
    base.html
    plans/list.html
    plans/detail.html
    plans/_slot.html      -- partial
    plans/_totals.html    -- partial
  static/
    app.css
    htmx.min.js     -- vendored at a pinned version; the app works offline
```

New runtime dependencies: `fastapi`, `uvicorn`, `jinja2`, `python-multipart`.

### 5.2 Rules

- **The web layer does no arithmetic and no SQL.** Every number on a page comes from a library
  call, and every write goes through a library function. Routes translate HTTP to library
  calls and results to templates.
- **Templates consume library dataclasses directly.** No separate view-model layer.
- **Every fragment is a partial, and full pages include the same partials.** A slot renders
  identically on page load and after an HTMX swap.
- **One connection per request**, opened by a dependency and closed after the response.
- **Current person.** If there is exactly one row in `people`, that is the person. If there are
  none, every page says to run `yolk init --seed`. If there are several, a picker in the header
  sets a cookie. There is no authentication; the app is bound to localhost.

### 5.3 Pages

- **`/plans`** — the current person's plans with status `active`: name, profile, and whether the
  day is within tolerance.
- **`/plans/{id}`** — the plan page:
  - A totals bar: day totals, profile target, deltas, and a pass or fail mark per macro from
    `within_tolerance`.
  - One section per slot, titled with the slot template name for that slot number on the plan's
    profile, or `Slot N` when there is none.
  - Each entry: food name, quantity and unit, grams, and its macros. Unverified foods carry the
    review badge from slice 4 onward.

Slot names are read through a new library function, `slot_names(conn, profile_id) -> dict[int, str]`
in `people.py`, so the route stays free of SQL.

---

## 6. Slice 3 — Edit by hand

### 6.1 Drafts

A draft is a `day_plans` row with `status = 'draft'` and `parent_plan_id` pointing at the plan
it was started from.

**Migration `0002_draft_status.sql`** rebuilds `day_plans` (§4.4) to allow `'draft'` in the
status CHECK, and adds:

```sql
CREATE UNIQUE INDEX idx_one_draft_per_plan
    ON day_plans (parent_plan_id) WHERE status = 'draft';
```

Partial indexes exist in both SQLite and Postgres. This is what enforces at most one open draft
per plan.

Why this shape: `evaluate()` takes a plan id and never looks at status, so drafts need no
special handling anywhere in the engine. A draft lives in the database rather than server
memory, so it survives a restart and follows you between devices.

### 6.2 Library operations

New module `src/yolk/planning/drafts.py`. Each function commits or rolls back as a unit.

| Function | Behavior |
|---|---|
| `start_draft(conn, plan_id) -> int` | Copies the plan row and all its entries into a new draft named `"<parent name> (draft)"`. If the plan already has an open draft, returns that draft's id instead. Raises if `plan_id` is itself a draft. |
| `update_entry(conn, entry_id, *, qty, unit)` | Changes quantity and unit. |
| `replace_entry_food(conn, entry_id, food_id, *, qty, unit)` | Swaps the food on an entry. |
| `remove_entry(conn, entry_id)` | Deletes an entry. |
| `save_over(conn, draft_id)` | Replaces the parent's entries with the draft's, then deletes the draft. |
| `save_as_new(conn, draft_id, *, name)` | Renames the draft, sets it `active`, and keeps `parent_plan_id` as lineage. |
| `discard_draft(conn, draft_id)` | Deletes the draft and its entries. |

**`update_entry`, `replace_entry_food`, and `remove_entry` raise if the entry's plan is not a
draft.** Saved plans change only through `save_over` or `save_as_new`. The existing `add_entry`
stays unrestricted because the seed and tests use it to build plans; the web layer calls it only
with draft ids.

Because a plan can only change through its single draft, `save_over` cannot overwrite an edit
made somewhere else.

`save_over` and `save_as_new` both resolve every entry's unit to grams before writing, so a
draft that cannot be evaluated cannot be committed.

### 6.3 Pages and interactions

- The plan page gains **Edit**, which calls `start_draft` and opens `/drafts/{id}`.
- **`/drafts/{id}`** shows the draft and its parent side by side: two evaluations, plus the
  difference in each day total.
- **Change a quantity:** an inline field posts on change. The response swaps that slot partial
  and the totals partial.
- **Swap a food:** opens a library search (§6.4), then posts `replace_entry_food`.
- **Add or remove an entry:** same pattern.
- **Save over**, **Save as new** (asks for a name), and **Discard** end the draft.

Every edit has the same shape: mutate the draft, re-evaluate, swap two partials.

### 6.4 Library search

`GET /foods/search?q=` returns a partial listing matching foods by name and brand, showing role,
per-100 g macros, and the review badge. It calls a new `search_library(conn, query)` in
`foods.py`. Slice 3 builds it for swapping. Slice 4 reuses it for recipe ingredient lines.

---

## 7. Slice 4 — Foods, recipes, and review

### 7.1 The recipe builder

`/recipes/new`: name, role, ingredient lines, and yield.

Each ingredient line finds its food in one of three ways:

1. **Library.** The §6.4 search, always shown first. `foods` is unique on `(name, brand)`, so
   searching first also prevents duplicate imports.
2. **USDA.** Search FoodData Central with the existing `search_foods()`, pick a result, choose a
   role, and import with the existing `import_food()`. Portion weights come from USDA's own
   `foodPortions`.
3. **By hand.** Enter name, brand, role, the label's per-serving kcal, protein, fat, carb and
   fiber, the serving's unit name, and its weight in grams. The app converts to per 100 g and
   records the serving unit, the same derivation the Keto A fixture used. Source is `label`.

Foods created through paths 2 and 3 are written immediately, before the recipe is saved. An
abandoned recipe leaves them in the library and in the review queue, which is correct: they are
real foods either way.

Then the line takes a quantity and unit. Mass units always resolve. Any other unit needs a gram
weight for that specific food, and when one is missing the line asks for it inline before the
recipe can be saved, rather than failing at save time.

Yield is either a serving count or a weighed cooked yield in grams, passed to the existing
`create_recipe()` as `servings` or `cooked_yield_g`.

### 7.2 Editing foods

`/foods/{id}` shows a food and allows editing:

- Items: macros and unit weights.
- Recipes: components, quantities, and yield.

Saving an edit to a food's macros, units, components, or yield:

1. Sets `verified = 0` and clears `verified_on` on that food.
2. Recomputes every recipe that contains it, directly or through nested recipes, innermost first,
   using the existing `recompute_recipe()`. Recipe macros are cached on the row, so skipping
   this would leave them stale. Those recipes are **not** marked unverified; their ingredient
   now is, and §7.3's derived warning shows that.
3. Lists, before saving, every active plan whose numbers will change, found by walking
   `food_components` upward from the food to plan entries. The walk terminates because cycles
   are already rejected at insert.

Versioning foods, so saved plans keep old numbers, would fully solve the third point and is out
of scope.

### 7.3 Review

- **The review state is `foods.verified`.** Nothing in the codebase currently sets it to 1, so it
  is free to take on this meaning. Every food created through the app or `import_food()` starts
  at 0.
- **Unverified foods are usable everywhere**, in drafts and saved plans alike, and carry a
  visible badge wherever they appear.
- **`/review`** lists unverified foods with source, source reference, per-100 g macros, units,
  notes, and for recipes their components.
- **Approve** sets `verified = 1` and `verified_on` to today.
- **Reject** deletes the food. The schema already refuses when a plan entry or recipe uses it
  (`ON DELETE RESTRICT`), and the app names what is holding it.
- **Derived warning.** A recipe with any unverified ingredient, at any depth, shows "contains
  unverified ingredients." Computed on display, never stored.

New library functions in `foods.py`: `approve_food`, `delete_food`, `update_item`,
`update_recipe`, `recipes_containing`, `plans_using_food`, `has_unverified_ingredients`.

Why review matters most for hand entry: the golden test documents that a wrong gram-per-serving
weight cancels out exactly in the math. Only a person reading the label catches it.

### 7.4 Runbook update

`docs/recipe-import.md` currently says no importer is built. It is updated to describe the app
path alongside the in-session path. Reading a cookbook photo or pasted web text stays a session
activity.

---

## 8. Slices 5 and 6 — Solver and fit

Specified in the original design, §5. Two notes from this design:

- `substitute()` operates on a draft from §6. It no longer needs to create its own variant
  plans; the draft is the variant.
- The solver adds `scipy` as a runtime dependency.

---

## 9. Postgres portability

No database abstraction layer is built. Two changes are made in slice 1 because they cost
nothing today:

1. **`RETURNING id` replaces `cursor.lastrowid`** at all seven current call sites and in all new
   code. SQLite has supported it since 3.35.
2. **A `Connection` type alias** in `yolk.db` replaces `sqlite3.Connection` in every annotation.

Rules for all new code:

- No SQLite-only SQL or functions.
- Booleans stay `INTEGER` with a `CHECK (x IN (0, 1))`, and dates stay ISO-8601 `TEXT`, matching
  the existing schema.
- Placeholders stay `?`. Converting to `%s` is a mechanical change at port time.

What the port itself would involve, for sizing: the placeholder change, a Postgres driver in
`connection.py`, replacing `sqlite3.Row`, `IDENTITY` columns and native `BOOLEAN`, `DATE` and
`TIMESTAMPTZ` types in a Postgres baseline migration, a Postgres run of the test suite, and
loading the §4.2 export. Estimated at one to two days.

---

## 10. Sharing, later

Out of scope here, recorded so nothing above blocks it.

- The other person gets the food library (`foods`, `food_units`, `food_components`, `tags`,
  `food_tags`) and their own everything else. Every personal table already carries `person_id`,
  so no schema change is needed.
- Sharing needs hosting, accounts, and sessions. That is a larger build than the Postgres port
  and should wait until the local app is in daily use.
- Review becomes more valuable with two people adding to one library. Recording who added and
  who approved a food would be added then, not now.

---

## 11. Amendments to the 2026-08-09 design

| Original | Amended to |
|---|---|
| §3 Environment: "SQLite file lives in the repo, under git." | File is ignored. A JSON export in `data/` is committed. |
| §3 Operating model: Claude Code as the primary front door, with a thin CLI. | Claude Code and a local web app are both front doors. The thin CLI covers setup and data commands. |
| §3 Layout: `db/migrations/` listed but unbuilt; `schema.sql` is the schema. | `schema.sql` becomes migration `0001_baseline.sql`; migrations are the single source of truth. |
| §5 `substitute()` derives a variant plan. | It operates on a §6 draft. |
| §6: no importer is built for ingredient capture. | The app's recipe builder is one. Image and pasted-text capture stay in session. |
| §9: `verified` marks whether a human checked a food. | Unchanged in meaning, now surfaced as the review queue. |

---

## 12. Error handling

The library already raises instead of guessing. The app's job is to show those errors where they
happened.

| Condition | Behavior |
|---|---|
| `UnknownUnitError`, `MissingYieldError`, or any `yolk.errors` exception during a request | Rendered inline in the fragment that caused it, naming the food and unit. Never a 500 page. |
| Duplicate `(name, brand)` on create | Inline message linking to the existing food. |
| Delete blocked by a foreign key | Inline message naming the plans or recipes using the food. |
| USDA request failure | The existing `SourceRequestError`, shown inline. Cached results still work. |
| Database missing or behind on migrations | Every page says which command to run. The app does not migrate on startup. |
| Editing a non-draft plan's entries | The library raises; the app never offers the action. |
| Unexpected exception | A plain error page, logged to the console. |

---

## 13. Testing

Test-driven, as in the original design.

**Slice 1**
- Migrations applied to an empty database produce the same tables, columns, and indexes as the
  current `schema.sql`.
- Applying migrations twice is a no-op.
- A rebuild migration preserves every row, and aborts on a failing `foreign_key_check`.
- Export, import into a fresh database, export again: byte-identical.
- Import refuses a non-empty database and a mismatched schema version.
- The golden test passes through `seed.py`.
- `yolk init --seed` against a temporary path yields a plan whose evaluation matches the golden
  totals.
- Every `RETURNING id` call site returns the same id `lastrowid` did, covered by the existing
  create tests.

**Slice 2** — through FastAPI's `TestClient`, which uses the existing `httpx` dependency:
- The plan page for the seeded plan shows every slot name and the day's kcal total.
- A plan with an unknown unit renders the error inline, not a 500.
- A missing database or pending migration renders the command to run.

**Slice 3**
- **Editing a draft never changes the parent's evaluation.** The most important test in this
  design.
- `start_draft` twice returns the same draft.
- Entry edits on a non-draft plan raise.
- `save_over` leaves the parent's entries equal to the draft's, and no draft remains.
- `save_as_new` keeps lineage and leaves the parent unchanged.
- A draft with an unresolvable unit cannot be committed.

**Slice 4**
- Editing an item resets its `verified` flag and recomputes every recipe containing it,
  including nested ones.
- `plans_using_food` finds a plan that uses the food only through a nested recipe.
- `has_unverified_ingredients` sees an unverified ingredient two levels down.
- Rejecting a food in use raises and changes nothing.
- The hand-entry per-serving to per-100 g conversion matches a Keto A fixture entry.
- USDA import through the app uses a recorded cache response, never the network.

Web tests assert on the things that matter in the rendered output. They are not exhaustive markup
checks.

---

## 14. Out of scope

- Hosting, accounts, and authentication.
- The Postgres port itself.
- Versioning of foods.
- Recording who added or approved a food.
- Phone-specific layouts beyond a stylesheet that does not break on a narrow screen.
- Everything the original design already defers.
