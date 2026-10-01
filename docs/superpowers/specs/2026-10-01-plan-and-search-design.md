# Food Search and Meal Planning — Design

**Date:** 2026-10-01
**Status:** Approved in brainstorming, not yet implemented
**Repo:** `yolk-carry` (package name: `yolk`)
**Builds on:** [`2026-09-13-local-app-persistence-and-review-design.md`](2026-09-13-local-app-persistence-and-review-design.md)
(slices 1 and 2 are built and merged). Where this document disagrees with that one, this one wins; §8
lists every amendment.

---

## 1. Goal

The app can show a plan but cannot change one, and there is no way to look through the food library.
This design adds:

1. **A fried-egg icon** beside "yolk" in the header.
2. **A Foods page** that searches the library by name or brand.
3. **Planning:** start a new day plan from blank, copy an existing one, and edit the meals in any plan,
   with nothing saved until an explicit save.

### Success criteria

1. Searching "chicken" on `/foods` finds the seeded chicken breast and shows its per-100 g macros and units.
2. A new blank plan can be created, filled with foods from the library, and saved, and it then appears in
   the plan list with its own within-tolerance mark.
3. Editing a draft never changes the saved plan's evaluation until "Save over", and a test proves it.
4. One entry whose amount cannot be measured shows its error on its own row; the rest of the plan still
   renders, and the plan cannot be saved until it is fixed.
5. No request from another website can change anything.

---

## 2. Decisions

| Question | Decision |
|---|---|
| What "plan new meals" means | Both: create new day plans (blank or copied) and edit the meals inside any plan. |
| What search covers | Foods in the local library only. No USDA, no plan search. |
| How a new plan starts | Blank (name and profile, empty slots) or a copy of an existing plan. |
| Egg icon | A simple flat fried egg, inline SVG, in the logo's colours. |
| Saving model | Drafts in the database, as the 2026-09-13 design specified. No direct edits, no browser-held state. |
| Sequencing | Part A (icon and Foods page) ships first; Part B (planning) reuses A's search. Each gets its own implementation plan. |

The rules from slice 2 still hold: the web layer does no arithmetic and no SQL; templates consume library
dataclasses; every fragment is a partial that full pages include; one connection per request; the app binds
to `127.0.0.1` and never migrates or creates the database.

---

## 3. Part A — Egg icon and Foods page

### 3.1 Egg icon

An inline SVG fried egg sits before the word "yolk" in `base.html`'s header link:

- Wavy egg white `#FFF8EC`, round yolk `#F4B63F` with a small lighter highlight, outline `#3A2F26`
  (the outline colour `logo.svg` uses).
- About 22 px tall, `aria-hidden="true"`; "yolk" stays the link's accessible text.
- Inline rather than a file, so it renders with the page and works offline. It does not change in dark
  mode: the white egg reads against both themes because of its outline.

### 3.2 Library search

New in `foods.py`:

```python
@dataclass(frozen=True)
class FoodSummary:
    id: int
    name: str
    brand: str
    kind: str                 # 'item' or 'recipe'
    role: str
    verified: bool
    per_100g: Macros | None   # None for a recipe whose macros were never computed
    units: list[tuple[str, float]]   # (unit, grams), ordered by unit

def search_library(conn: Connection, query: str) -> list[FoodSummary]: ...
```

- Case-insensitive substring match on name or brand, written portably: `lower(name) LIKE ?` with the
  lowercased query wrapped in `%`. SQLite and Postgres both handle it.
- An empty or whitespace-only query returns every food.
- Ordered by name, then brand, then id.
- An uncomputed recipe comes back with `per_100g = None` rather than raising: the list must not fail
  because one recipe has no yield yet.

### 3.3 Page

- **`GET /foods?q=`**, linked as **Foods** in the header nav. A plain GET form, so it works without
  JavaScript and the URL is bookmarkable.
- Results table: name (with brand when present), role, kcal / protein / fat / carbs per 100 g, units
  (`packet = 22 g`). Unverified foods carry an "unchecked" badge. An uncomputed recipe shows
  "not computed" in place of numbers.
- No match: "No foods match 'xyz'."
- The table is the partial `foods/_results.html`. Part B renders the same partial with an action button
  per row, passed in as context.

### 3.4 Tests

Library: case-insensitive match, brand match, empty query returns all, ordering, uncomputed recipe has
`per_100g is None`. Web: the page lists a seeded food, a query narrows the list, no match shows the message,
and the header contains the egg SVG.

---

## 4. Part B — Planning

### 4.1 Drafts in the database

A draft is a `day_plans` row with `status = 'draft'`.

**Migration `0002_draft_status.sql`** rebuilds `day_plans` with the slice 1 rebuild procedure so the status
CHECK allows `'draft'`, and adds:

```sql
CREATE UNIQUE INDEX idx_one_draft_per_plan
    ON day_plans (parent_plan_id) WHERE status = 'draft';
```

At most one open draft per saved plan. A blank draft has `parent_plan_id IS NULL`; unique indexes allow
repeated NULLs in both SQLite and Postgres, so several blank drafts may coexist.

`UNIQUE (person_id, name)` still applies to drafts. A draft of a plan is named `"<parent name> (draft)"`.
A blank draft takes its intended name directly.

### 4.2 Library: `planning/drafts.py`

Each function commits or rolls back as a unit.

| Function | Behaviour |
|---|---|
| `start_draft(conn, plan_id) -> int` | Copies the plan row and all its entries into a draft with `parent_plan_id = plan_id`. If the plan already has an open draft, returns that draft's id. Raises if `plan_id` is itself a draft. |
| `start_blank_draft(conn, person_id, profile_id, name) -> int` | A draft with no parent and no entries. Raises `DuplicatePlanNameError` if the person already has a plan or draft with that name. |
| `add_entry_to_draft(conn, draft_id, *, slot_no, food_id, qty, unit) -> int` | Appends an entry at the end of the slot. |
| `update_entry(conn, entry_id, *, qty, unit)` | Changes quantity and unit. |
| `replace_entry_food(conn, entry_id, food_id, *, qty, unit)` | Swaps the food, keeping the entry's slot and position. |
| `remove_entry(conn, entry_id)` | Deletes the entry. |
| `save_over(conn, draft_id)` | Replaces the parent's entries with the draft's, then deletes the draft. Raises if the draft has no parent. |
| `save_as_new(conn, draft_id, *, name) -> int` | Renames the draft, sets it `active`, keeps `parent_plan_id` as lineage. Raises `DuplicatePlanNameError` on a taken name. |
| `discard_draft(conn, draft_id)` | Deletes the draft and its entries. |

- **The four entry edits raise `NotADraftError` when the entry's plan is not a draft.** Saved plans change
  only through `save_over` and `save_as_new`.
- **`qty` must be greater than 0**; a non-positive quantity raises `ValueError` before any write.
- **Both saves resolve every entry to grams first**, and raise naming the food and unit if any cannot be
  resolved. A draft whose numbers are wrong cannot become a saved plan.
- `DuplicatePlanNameError` and `NotADraftError` are new `YolkError` subclasses in `errors.py`.

### 4.3 Library: evaluation and display helpers

- **`evaluate(conn, plan_id, *, partial=False)`.** The default is unchanged: the first unresolvable entry
  raises. With `partial=True`, an entry whose grams or macros cannot be computed (`UnknownUnitError`,
  `MissingYieldError`) comes back with `error: str` set and `grams`/`macros` as `None`, and is left out of
  slot and day totals. `DayEvaluation` gains `excluded: int` (entries left out). When `excluded > 0`,
  `ok` is `False`. `EntryEvaluation.error` defaults to `None`, so existing callers see no change.
- **`plan_slots(conn, plan_id, evaluation) -> list[PlanSlot]`** in `planning/plans.py`.
  `PlanSlot(slot_no, name, slot: SlotEvaluation | None)` lists every slot template of the plan's profile,
  plus any slot number with entries but no template (named `"Slot N"`), in slot order. This is what lets
  a blank plan show Meal 1 through Meal 6 empty and ready to fill.
- **`units_for(conn, food_id) -> list[str]`** in `units.py`: the food's own units first (its default
  display unit at the top), then the mass units `g`, `oz`, `lb`, `kg`.
- **`default_portion(conn, food_id) -> tuple[float, str]`** in `units.py`: `(1, default display unit)`,
  else `(1, first unit)`, else `(100, "g")`.
- **`compare(draft: DayEvaluation, parent: DayEvaluation) -> Macros`** in `planning/plans.py`: the draft's
  totals minus the parent's.
- **`draft_summaries(conn, person_id) -> list[PlanSummary]`** in `planning/plans.py`: the person's open
  drafts, for the plan list. `plan_summaries` is unchanged and still returns only active plans.
- **`current_profiles(conn, person_id, on_date) -> list[ProfileChoice]`** in `people.py`: for each profile
  name, the row in force on `on_date` (latest `effective_on <= on_date`), for the New plan form.
  `ProfileChoice(id, name, kcal)`.

### 4.4 Pages

**`/plans`**
- **New plan** opens a form: name, and profile from `current_profiles`. Submitting calls
  `start_blank_draft` and redirects to the draft.
- Open drafts are listed in their own **In progress** section above the saved plans.

**`/plans/{id}`** is unchanged except for an **Edit or copy** button, a POST that calls `start_draft` and
redirects to `/drafts/{draft_id}`.

**`/drafts/{id}`**
- Header: draft name, profile, and the save actions:
  - **Save over "<parent name>"**, shown only when the draft has a parent, with a confirmation.
  - **Save as new**, which asks for a name.
  - **Discard**, with a confirmation.
- Totals: the slice 2 totals table, plus a **vs saved** column from `compare` when the draft has a parent.
  When `excluded > 0`, the totals carry "Incomplete: N entries excluded".
- Every slot from `plan_slots`, empty ones included. Each entry row:
  - **Amount**: a number input. On change it posts `update_entry`.
  - **Unit**: a select of `units_for`. On change it posts `update_entry`.
  - **Swap** and **Remove** buttons.
  - An entry with `error` shows the message in its own row, styled as an error.
- **Add food** under each slot opens an inline search box. It renders `foods/_results.html` with an
  **Add** button per row. Choosing a food posts `add_entry_to_draft` with `default_portion`. **Swap**
  opens the same search, and choosing posts `replace_entry_food` with the new food's `default_portion`.

### 4.5 Interaction

- htmx is vendored at a pinned version under `static/`, so the app works offline.
- Every edit has one shape: POST the change, mutate the draft, re-evaluate with `partial=True`, and
  respond with that slot's partial plus the totals partial (the totals swapped out of band).
- **Every form also works without JavaScript.** Without htmx, a POST redirects (303) back to
  `/drafts/{id}` and the full page re-renders.
- Routes: `POST /plans` (new blank draft), `POST /plans/{id}/draft`, `GET /drafts/{id}`,
  `POST /drafts/{id}/entries`, `POST /drafts/{id}/entries/{entry_id}`,
  `POST /drafts/{id}/entries/{entry_id}/swap`, `POST /drafts/{id}/entries/{entry_id}/remove`,
  `POST /drafts/{id}/save-over`, `POST /drafts/{id}/save-as-new`, `POST /drafts/{id}/discard`,
  `GET /foods/search?q=&draft=&slot=&entry=` (the inline picker, returning the results partial).

---

## 5. Errors and safety

| Condition | Behaviour |
|---|---|
| Duplicate plan name (new blank plan, save as new) | Inline message next to the name field: "You already have a plan called 'X'." |
| Save with an unresolvable entry | Refused; inline message naming the food and unit. The row is already marked. |
| Non-positive or non-numeric amount | Inline message on that row; nothing written. |
| Unknown route, unknown plan or draft id, malformed path or form value | The app's HTML error page with the right status (404 or 422), not FastAPI's JSON. |
| Plan or draft belonging to another person | 404. The person picker can never leave you editing someone else's plan. |
| POST whose `Origin` (or `Referer` when `Origin` is absent) host is not `127.0.0.1` or `localhost`, or that carries neither | 403. Another website cannot submit edits. This sits on top of slice 2's Host check. |
| Unexpected exception | Unchanged: the plain error page; the traceback goes to the console. |

`error.html` takes an explicit `title` in place of today's "any message means Not found".

---

## 6. Testing

**Part A:** §3.4.

**Part B, library**
- **Editing a draft never changes the parent's evaluation.** The most important test in this design.
- `start_draft` twice returns the same draft; on a draft it raises.
- Entry edits on a non-draft plan raise `NotADraftError`.
- `save_over` leaves the parent's entries equal to the draft's, and no draft remains.
- `save_as_new` keeps lineage and leaves the parent unchanged; a taken name raises.
- A draft with an unresolvable unit cannot be saved either way.
- A blank draft's `plan_slots` lists every slot template with `slot = None`.
- `evaluate(partial=True)` marks only the bad entry, excludes it from totals, sets `excluded`, and is
  not `ok`; `evaluate()` without the flag still raises.
- Migration 0002 preserves every existing plan and entry, and the partial index rejects a second draft of
  one plan.

**Part B, web**
- Full flow: New plan → Add food → change amount → Save as new; the plan appears in the list.
- Edit → change → Discard leaves the saved plan's totals unchanged.
- An amount change returns the updated slot and totals.
- The same flows work as plain form posts without the htmx header.
- A POST with a foreign `Origin`, or with no `Origin` and no `Referer`, gets 403.
- Another person's plan or draft gets 404.
- An unknown route gets the HTML error page.

---

## 7. Out of scope

- Deleting or archiving saved plans.
- Undo inside a draft.
- Reordering entries within a slot.
- Re-balancing the day after a swap (slice 5).
- USDA import, the recipe builder, and the review queue (slice 4).

---

## 8. Amendments to the 2026-09-13 design

| 2026-09-13 says | This design says |
|---|---|
| §3: slice 3 is "Edit by hand"; slice 4 builds foods, recipes, review. | Slice 3 becomes Part A plus Part B here: the Foods page and the egg icon are added, and new blank and copied plans are added to editing. Slice 4 is unchanged. |
| §6.2: entry edits are `update_entry`, `replace_entry_food`, `remove_entry`; the existing `add_entry` is used on drafts. | Adds `add_entry_to_draft` (refuses non-drafts) and `start_blank_draft`; the web layer never calls `add_entry`. |
| §6.3: the draft page shows draft and parent side by side, two full evaluations. | One evaluation with a "vs saved" column per day total. |
| §6.4: `GET /foods/search?q=` returns a partial for swapping. | Also a full `/foods` page; the search returns `FoodSummary` with per-100 g macros and units. |
| §12: library errors render "inline in the fragment that caused it". | Achieved for plan rendering through `evaluate(partial=True)`. |
| §12: no mention of cross-site requests. | Origin/Referer check on every POST (§5). |
