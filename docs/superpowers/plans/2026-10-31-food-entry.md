# Food Entry Implementation Plan (Part B)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Jen can add a food in the web app, by typing a label or picking a USDA result, see its points before saving, then check or fix it. A receipt that Claude turns into a CSV imports with one command.

**Architecture:**
- A new library module, `yolk/food_entry.py`, owns label input, validation, per-serving to per-100 g conversion, role derivation, preview, create, edit and mark-checked.
- The web routes and the CSV importer are thin callers of it.
- Everything builds on Part A's `points.py` and `point_portions`.

**Tech Stack:** Python 3.14, SQLite, FastAPI + Jinja2 + htmx 2.0.11, pytest, and the stdlib `csv` module. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-31-point-system-design.md` §7 and §8. **Requires** Part A (`docs/superpowers/plans/2026-10-31-points-core.md`) to be merged first.

## Global Constraints

- Label figures are entered **per serving, as printed**. Stored macros are per 100 g, factor `100 / serving_g`.
- "Counts as" values: `auto` (default), `fat`, `carb`, `protein`, `veggie`, `free`.
- Role derives from "counts as":
  - fat, carb or protein → the same role;
  - veggie → `veg`;
  - auto → the role of the type with the most points;
  - free → the chosen `free_role` from `veg`, `sauce` or `beverage`. It is required only for free.
- New foods are unverified, with `source = 'label'` (form or CSV) or `'usda'`.
- "Mark checked" sets `verified = 1` and `verified_on` to today. Any edit of a checked food clears both.
- An edit never touches a `point_portions` row with `source = 'coach'`.
- Fiber left blank is stored as NULL (unknown), never 0. Sugar alcohols left blank are stored as NULL.
- The web layer does no arithmetic and no SQL. Every new POST is covered by the existing same-origin guard.
- A missing `USDA_API_KEY` shows a plain message pointing at `.env`, not an error page.

## Review Focus

1. **Serving size 0, blank or negative** must be refused by field, never divided by. Pinned in Task 1.
2. **A label whose macros exceed its serving weight** (fat + carb + protein > serving_g, a typo like 300 g fat in a 30 g serving) must be refused with a message naming the fields. Pinned in Task 1.
3. **A duplicate `(name, brand)`** on the form must show the error by the name field and keep everything she typed. Pinned in Task 2.
4. **A CSV saved by Excel**, with a UTF-8 BOM, CRLF line endings, or a blank trailing line, must import. Pinned in Task 5.
5. **Commas as decimal separators or units typed into numbers** ("12g") in a CSV cell must be named by line and column, not crash. Pinned in Task 5.

---

### Task 1: Label input library

**Files:**
- Create: `src/yolk/food_entry.py`
- Modify: `src/yolk/foods.py` (`create_item` gains `point_class: str | None = None`, `fiber_known: bool = True`, `sugar_alcohol_g_100g: float | None = None`)
- Test: `tests/test_food_entry.py`

**Interfaces:**
- Consumes (Part A): `Points`, `PointRules`, `load_rules`, `points_for`, `effective_class`, `format_points`, `one_point`, `add_portion`.
- Produces:
  ```python
  COUNTS_AS = ("auto", "fat", "carb", "protein", "veggie", "free")
  FREE_ROLES = ("veg", "sauce", "beverage")
  @dataclass(frozen=True)
  class LabelInput:
      name: str; brand: str; serving_g: float | None
      kcal: float | None; fat_g: float | None; carb_g: float | None
      fiber_g: float | None; sugar_alcohol_g: float | None; protein_g: float | None
      counts_as: str = "auto"; free_role: str | None = None
      unit: str | None = None; unit_qty: float | None = None   # "4 pancakes" -> ("pancake", 4)
      notes: str | None = None
  class LabelInputError(YolkError):           # .errors: dict[str, str], field name -> message
      ...
  def validate(inp: LabelInput) -> dict[str, str]
  def per_100g(inp: LabelInput) -> Macros
  def role_for(counts_as: str, free_role: str | None, per_100g: Macros, rules: PointRules) -> str
  @dataclass(frozen=True)
  class LabelPreview:
      serving_points: str          # e.g. "1C + ¾P + ¼F"
      serving_text: str            # e.g. "4 pancake (116 g)"
      one_point: str | None        # OnePoint.label
      errors: dict[str, str]
  def preview(conn, inp: LabelInput) -> LabelPreview   # never raises on bad input; errors filled
  def create_label_food(conn, inp: LabelInput, *, source: str = "label", commit: bool = True) -> int
  ```

- [ ] **Step 1: Write the failing tests** in `tests/test_food_entry.py`.
  - `test_per_serving_converts_to_per_100g`: the Crepini label (serving 116 g, kcal 240, fat 4, carb 25, fiber 1, protein 20) gives per-100 g fat ≈ 3.448, carb ≈ 21.55 and protein ≈ 17.24.
  - `test_blank_fiber_is_unknown_not_zero`: after `create_label_food`, the row's `fiber_g_100g IS NULL`.
  - `test_role_follows_counts_as`:
    - `'veggie'` gives `'veg'`;
    - `'protein'` gives `'protein'`;
    - `'free'` with `'beverage'` gives `'beverage'`;
    - `'auto'` on the birria label (fat 9, carb 1, protein 25 per 142 g) gives `'protein'`.
  - `test_free_requires_free_role`: `validate` returns `{'free_role': ...}`.
  - `test_serving_must_be_positive` (Review Focus 1): `serving_g` of `0`, `None` and `-5` each give an error keyed `serving_g`.
  - `test_macros_cannot_exceed_serving` (Review Focus 2): serving 30 g with fat 300 gives an error keyed `fat_g` that names the serving size.
  - `test_preview_shows_points_and_one_point`: the Crepini input with `unit='pancake'` and `unit_qty=4` gives `serving_points == "1C + ¾P + ¼F"` and `serving_text == "4 pancake (116 g)"`.
  - `test_create_writes_unit_and_label_portion`: the food has `food_units` `pancake = 29.0` and a `point_portions` row `('label', 4, 'pancake', '1C + ¾P + ¼F')`. `verified == 0` and `source == 'label'`.
  - `test_no_unit_means_one_serving`: with no unit, a `serving` unit equal to `serving_g` is written and the portion is `1 serving`.
  - `test_create_rejects_duplicate_name_brand`: raises `LabelInputError` with `errors == {'name': ...}`, and writes nothing.

- [ ] **Step 2: Run** `uv run python -m pytest tests/test_food_entry.py -q`. Expected: FAIL with an ImportError.

- [ ] **Step 3: Implement.**
  - `validate` checks: the name is non-empty; `serving_g > 0`; kcal, fat, carb and protein are present and ≥ 0; optional fields are ≥ 0; `fat + carb + protein ≤ serving_g × 1.05`; `fiber + sugar_alcohol ≤ carb`; `counts_as` is in `COUNTS_AS`; `free_role` is set and valid exactly when `counts_as == 'free'`; and `unit_qty > 0` when `unit` is set.
  - `create_label_food` calls `validate` and raises `LabelInputError` on errors. It catches the `(name, brand)` `IntegrityError` and turns it into `errors['name']`. Food, unit and portion are written in one transaction.

- [ ] **Step 4: Run** `uv run python -m pytest -q`. Expected: all pass.

- [ ] **Step 5: Commit** with the message `feat: label entry library with validation, preview, and role derivation`.

---

### Task 2: New food page, from a label

**Files:**
- Create: `src/yolk/web/routes/food_entry.py`, `src/yolk/web/templates/foods/new.html`, `src/yolk/web/templates/foods/_preview.html`
- Modify: `src/yolk/web/app.py`, `src/yolk/web/templates/foods/list.html` ("New food" button)
- Test: `tests/test_web_food_entry.py`

**Interfaces:**
- Consumes: Task 1.
- Produces:
  - `GET /foods/new`, the form.
  - `POST /foods/new/preview` (htmx). It returns `_preview.html` with points or errors and never writes. It is triggered on `change` of any field, not on each keystroke.
  - `POST /foods/new`. Success redirects 303 to `/foods/{id}`. Errors give 422 and re-render the form with every typed value kept and each message next to its field.

- [ ] **Step 1: Write the failing tests.**
  - `test_new_food_form_renders`: the form has fields `name`, `brand`, `serving_g`, `kcal`, `fat_g`, `carb_g`, `fiber_g`, `sugar_alcohol_g`, `protein_g`, `counts_as`, `free_role`, `unit`, `unit_qty` and `notes`.
  - `test_preview_shows_points`: POSTing the Crepini figures to the preview gives a response containing "1C + ¾P + ¼F".
  - `test_save_redirects_to_food_page`: 303 to `/foods/<id>`, and the food is in `/foods?q=crepini` with the "unchecked" badge.
  - `test_duplicate_name_keeps_input` (Review Focus 3): saving a second "Crepini" gives 422. The page contains `value="240"` and `value="Crepini"`, and the error sits inside the name field's container (`id="field-name"`).
  - `test_blank_numbers_are_errors_not_500`: an empty `fat_g` gives 422 with a message by `fat_g`.

- [ ] **Step 2: Run** `uv run python -m pytest tests/test_web_food_entry.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement.**
  - Parse form strings to `LabelInput`: a blank string becomes None, and a number that does not parse is a field error, not a 422 from FastAPI. Take all fields as `str` form values and convert in a small route helper that returns `(LabelInput, dict[str, str])`.
  - Hide `free_role` unless "free" is chosen, with a progressive-enhancement `hx-` swap or plain CSS. It must still work without JS.

- [ ] **Step 4: Run** `uv run python -m pytest -q`, then preview the page in the browser pane: enter the Crepini label and take a screenshot of the preview.

- [ ] **Step 5: Commit** with the message `feat: add a food from its label in the app`.

---

### Task 3: New food from USDA

**Files:**
- Modify: `src/yolk/food_entry.py`, `src/yolk/web/routes/food_entry.py`, `src/yolk/web/templates/foods/new.html`
- Create: `src/yolk/web/templates/foods/_usda_results.html`
- Test: `tests/test_web_food_entry.py`, `tests/test_food_entry.py`

**Interfaces:**
- Consumes: `sources.usda.search_foods(query, page_size=10)`, `usda.get_food`, `usda.parse_macros`, `usda.import_food(conn, fdc_id, role=…, units=…)`.
- Produces:
  ```python
  @dataclass(frozen=True)
  class UsdaChoice:
      fdc_id: int; description: str; per_100g: Macros; points_100g: str
  def usda_search(query: str, rules: PointRules) -> list[UsdaChoice]   # raises UsdaUnavailable
  class UsdaUnavailable(YolkError): ...   # wraps missing key (RuntimeError) and SourceRequestError
  def create_usda_food(conn, fdc_id: int, *, counts_as: str, free_role: str | None) -> int
  ```
  - `GET /foods/new/usda?q=` (htmx partial) lists choices with an Add button that POSTs `fdc_id`, `counts_as` and `free_role` to `/foods/new/usda`, then 303 to `/foods/{id}`.

- [ ] **Step 1: Write the failing tests.** Monkeypatch `usda.search_foods` and `usda.get_food` with the `SAMPLE_PAYLOAD` shape from `tests/test_usda.py`. Never hit the network.
  - `test_usda_search_lists_points_per_100g`: the partial shows the description and "1P" (22.5 g protein per 100 g is 0.9P, which rounds to 1P; 2.62 g fat adds "¼F").
  - `test_usda_add_sets_class_and_role`: adding with `counts_as=protein` gives role `protein`, `point_class` `protein`, source `usda` and verified 0.
  - `test_missing_key_shows_plain_message`: with `search_foods` raising `RuntimeError("USDA_API_KEY is not set…")`, the response is 200 and contains ".env", with no traceback text.

- [ ] **Step 2: Run** `uv run python -m pytest tests/test_web_food_entry.py tests/test_food_entry.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement.** `create_usda_food` calls `import_food` with the derived role (using `role_for` on the parsed per-100 g macros), then sets `point_class` (NULL for auto) in the same transaction. Pass `commit=False` through, adding that parameter to `import_food`.

- [ ] **Step 4: Run** `uv run python -m pytest -q`. Expected: all pass.

- [ ] **Step 5: Commit** with the message `feat: add a food from USDA with its points previewed`.

---

### Task 4: Food page: check and fix a food

**Files:**
- Modify: `src/yolk/food_entry.py`, `src/yolk/web/routes/food_entry.py`, `src/yolk/web/templates/foods/_results.html` (name links to `/foods/{id}`)
- Create: `src/yolk/web/templates/foods/detail.html`, `src/yolk/web/templates/foods/edit.html`
- Test: `tests/test_food_entry.py`, `tests/test_web_food_detail.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass(frozen=True)
  class FoodDetail:
      summary: FoodSummary          # Part A fields included
      source: str; source_ref: str | None; notes: str | None; verified_on: str | None
      portions: list[Portion]       # every source, coach first in display
      sugar_alcohol_g_100g: float | None
  def food_detail(conn, food_id: int) -> FoodDetail           # LookupError if missing
  def mark_checked(conn, food_id: int) -> None
  @dataclass(frozen=True)
  class FoodEdit:
      name: str; brand: str; kcal: float; fat_g: float; carb_g: float
      fiber_g: float | None; sugar_alcohol_g: float | None; protein_g: float
      counts_as: str; free_role: str | None
      units: dict[str, float]                  # full replacement of the food's own units
      manual_portion: tuple[float, str] | None # None removes the manual row
  def update_food(conn, food_id: int, edit: FoodEdit) -> None  # per-100 g figures; raises LabelInputError
  ```
  - Routes: `GET /foods/{id}`, `POST /foods/{id}/check`, `GET /foods/{id}/edit` and `POST /foods/{id}/edit`. Recipes give a read-only detail page with no edit link, and `POST /foods/{id}/edit` on a recipe returns 409.

- [ ] **Step 1: Write the failing tests.**
  - `test_detail_shows_coach_and_computed_points`: a seeded coach food shows its coach portion text, its computed points, and the "coach says" flag when `disagrees`.
  - `test_mark_checked_sets_today`: afterwards `verified == 1` and `verified_on == date.today().isoformat()`.
  - `test_edit_clears_checked`: editing a checked food's fat gives `verified == 0` and `verified_on IS NULL`.
  - `test_edit_never_touches_coach_portion`: setting `manual_portion=(5, 'oz')` keeps the coach row unchanged and adds a manual row. `preferred_portion(...).source == 'manual'`.
  - `test_edit_refuses_removing_a_unit_in_use`: dropping a unit that a `day_plan_entries` or `point_portions` row uses raises `LabelInputError` keyed `units`, naming the plan or portion.
  - `test_recipe_is_read_only`: the edit POST on a recipe gives 409.
  - `test_unknown_food_is_404`.

- [ ] **Step 2: Run** `uv run python -m pytest tests/test_food_entry.py tests/test_web_food_detail.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement.** The edit form uses per-100 g figures (what is stored), labelled as such. `update_food` validates with the same rules as `validate` where they apply (non-negative, fiber + sugar alcohol ≤ carb, sum ≤ 100 × 1.05).

- [ ] **Step 4: Run** `uv run python -m pytest -q`. Expected: all pass.

- [ ] **Step 5: Commit** with the message `feat: food page to check and fix a food`.

---

### Task 5: Receipt inbox CSV import

**Files:**
- Create: `src/yolk/inbox.py`, `docs/food-inbox-template.csv`, `docs/food-inbox.md`
- Modify: `src/yolk/cli.py` (`import-foods FILE` subcommand), `README.md`
- Test: `tests/test_inbox.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: Task 1 (`LabelInput`, `validate`, `create_label_food`).
- Produces:
  ```python
  INBOX_COLUMNS = ("name", "brand", "store", "serving_text", "serving_g", "kcal", "fat_g",
                   "carb_g", "fiber_g", "sugar_alcohol_g", "protein_g", "point_class",
                   "unit", "unit_g", "source_note")
  @dataclass(frozen=True)
  class InboxReport:
      created: list[str]; skipped: list[str]     # "name (brand)" strings
  class InboxError(YolkError):                   # .problems: list[str], each "line N, column: message"
      ...
  def import_inbox(conn, path: Path) -> InboxReport
  ```
  - Row mapping:
    - `point_class` is the "counts as" value. For free foods it is written `free:<role>`, for example `free:beverage`. Blank means auto.
    - `unit`/`unit_g` becomes `unit` plus `unit_qty = serving_g / unit_g`.
    - `notes` = `"{store} · {serving_text} · {source_note}"`, with blanks left out.

- [ ] **Step 1: Write the failing tests** in `tests/test_inbox.py`, writing CSVs to `tmp_path`.
  - `test_template_header_matches_columns`: the first line of `docs/food-inbox-template.csv` equals `",".join(INBOX_COLUMNS)`.
  - `test_imports_valid_rows_unverified`: two Costco rows create two `label` foods with `verified == 0`, and `report.created` names both.
  - `test_one_bad_row_imports_nothing`: rows 2 and 4 are bad (a blank `serving_g`; fat > serving). `InboxError.problems` names `line 2` and `line 4` with the column, and `foods` is unchanged.
  - `test_existing_name_brand_is_skipped`: it is listed in `report.skipped` and not duplicated.
  - `test_excel_csv_imports` (Review Focus 4): a file written with `encoding="utf-8-sig"`, `\r\n` line endings and a trailing blank line imports.
  - `test_unparseable_numbers_are_named` (Review Focus 5): `"12g"` and `"1,5"` in `fat_g` each give a problem naming the line and `fat_g`.
  - `test_unknown_column_is_refused`: a header with an extra or missing column gives an `InboxError` naming the column, before any row is read.
  - In `tests/test_cli.py`, `test_import_foods_command`: it prints "Imported 2, skipped 0" and returns 0. A bad file prints the problems to stderr and returns 1.

- [ ] **Step 2: Run** `uv run python -m pytest tests/test_inbox.py tests/test_cli.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement.**
  - Open with `encoding="utf-8-sig"` and `newline=""`, using `csv.DictReader` and skipping fully blank rows.
  - Validate every row (`validate` plus number parsing) before any write, then create all rows in one transaction.
  - Write the template with its header and the eight Costco items from spec §1's source material as example rows. They are already approximate, so they demonstrate the format.
  - Write `docs/food-inbox.md`, a runbook in the voice of `docs/recipe-import.md`. In a Claude Code session: hand over the receipt, have Claude find each product's label figures and fill the CSV (with `source_note` naming where each number came from), run `yolk import-foods`, then check each food against its package on the Foods page.

- [ ] **Step 4: Run** `uv run python -m pytest -q`. Expected: all pass.

- [ ] **Step 5: Commit** with the message `feat: import foods from a receipt inbox CSV`.

---

### Task 6: End-to-end check in the app

**Files:** none new.

- [ ] **Step 1:** Start the dev server with preview_start (`yolk` entry in `.claude/launch.json`) against the real database, migrated and seeded by Part A.
- [ ] **Step 2:** Add the Crepini pancakes from their label in the app. Confirm the preview says about "1C + ¾P + ¼F" before saving. Then add them to a new Active recovery plan at 7:00 and confirm the meal shows them at "4 pancake".
- [ ] **Step 3:** Mark the food checked on its page and confirm the "unchecked" badge is gone from the Foods list.
- [ ] **Step 4:** Take screenshots of the preview and the plan, and attach them to the branch summary.
- [ ] **Step 5:** Run `uv run python -m pytest -q`. Expected: all pass.
