# Points Core Implementation Plan (Part A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every food and planned meal shows points computed from stored macros. The active recovery day exists as a points profile that is judged by macros, and the coach's lists are seeded as foods.

**Architecture:**
- Migration 0003 adds point rules, a carb-basis setting, food point classes, per-source point portions, points profiles and slot allotments.
- A new pure module, `yolk/points.py`, turns `Macros` plus rules into `Points`. `evaluate()` attaches points to every entry, slot and day.
- A fixture, `tests/fixtures/point_system.json`, is built once in session from the coach's workbook and seeded by `yolk seed points`.

**Tech Stack:** Python 3.14, SQLite (portable SQL), FastAPI + Jinja2 + vendored htmx 2.0.11, pytest. Run everything as `uv run python -m …`.

**Spec:** `docs/superpowers/specs/2026-10-31-point-system-design.md` (§1–§6, §8, §10). Part B, food entry (§7), is `docs/superpowers/plans/2026-10-31-food-entry.md`.

## Global Constraints

- Point sizes are seeded as fat 15 g, carb 25 g, protein 25 g and veggie 10 g, global (not per person).
- `settings.carb_basis` is `'total'` (default) or `'net'`.
- Net carbs = `carb_g − fiber_g − sugar_alcohol_g`, floored at 0. Under net, a food with NULL fiber falls back to total carbs and is flagged "fiber unknown."
- Points are never stored on a food or an entry. They are always computed from macros and `point_rules`.
- Display rounds to the nearest ¼, shows quarters as `¼ ½ ¾`, and leaves out types that round to 0.
- The per-meal match is ±0.25 per point type. It is only a hint and never fails a day.
- A points-profile day counts kcal as `9·fat + 4·counted_carbs + 4·protein`. Its tolerances are kcal ±5% (seeded `kcal_tol_pct = 5.0`), protein ±8 g, and fat and carb ±3 percentage points.
- Macros profiles (the existing `training` profile behind Keto Meal Plan A) are unchanged: label kcal, total carbs, ±1%.
- The web layer does no arithmetic and no SQL. Templates consume library dataclasses.
- Migrations: forward-only, no transaction control or pragmas, portable types (INTEGER, TEXT, REAL), CHECK constraints for enums, ISO-8601 TEXT dates.
- The coach workbooks (`C:\Users\jcraw\OneDrive\Documents\meal_planning\*.xlsx`) are never copied into the repo.

## Review Focus

1. **A food with zero of its main macro** (a free food, or a pure-fat oil classed as carb) has no one-point portion and must not divide by zero. The picker shows "—". Pinned in Task 3.
2. **A recipe whose components include a recipe with no yield** must keep showing the existing `MissingYieldError` row error, not crash the points column. Pinned in Task 3.
3. **Switching to net with a high-fiber food that has NULL fiber** must show total-carb points with the flag, not 0 carbs. Pinned in Task 2.
4. **An entry in a slot number with no template** (`Slot 7`) on a points profile has no allotment and no hint, and the day still evaluates. Pinned in Task 5.
5. **`yolk seed points` run against a database that has no person named Jen** fails with a clear message and writes nothing. Pinned in Task 6.

---

### Task 1: Migration 0003 and snapshot support

**Files:**
- Create: `src/yolk/db/migrations/0003_points.sql`
- Modify: `src/yolk/snapshot.py` (`TABLES`, `import_database`)
- Test: `tests/test_migration_0003.py`, `tests/test_snapshot.py`

**Interfaces:**
- Produces these tables and columns:
  - `point_rules(point_type TEXT PK CHECK IN ('fat','carb','protein','veggie'), grams_per_point REAL NOT NULL CHECK > 0)`, seeded with 15/25/25/10.
  - `settings(key TEXT PK, value TEXT NOT NULL)`, seeded with `('carb_basis','total')`.
  - `foods.point_class TEXT NULL CHECK IN ('fat','carb','protein','veggie','free')`.
  - `foods.sugar_alcohol_g_100g REAL NULL`.
  - `point_portions(food_id, source, qty, unit, claimed, PK(food_id, source))`. `source` is CHECK IN `('coach','claude','label','manual')`. `food_id` references `foods` ON DELETE CASCADE.
  - `macro_profiles.basis TEXT NOT NULL DEFAULT 'macros' CHECK IN ('macros','points')`, with `kcal`, `fat_pct`, `carb_pct` and `protein_pct` now nullable.
  - `slot_templates.fat_pts`, `carb_pts`, `protein_pts`, `veggie_pts`: each `REAL NOT NULL DEFAULT 0 CHECK (… >= 0)`.

- [ ] **Step 1: Write the failing tests** in `tests/test_migration_0003.py`, using the upgrade-in-place pattern from `tests/test_migration_0002.py`. Copy 0001 and 0002 to `tmp_path`, migrate, seed Keto Plan A, then apply all migrations.
  - `test_0003_keeps_profiles_plans_and_evaluation`: rows of `macro_profiles` (old columns), `slot_templates`, `day_plans` and `day_plan_entries` are unchanged. `evaluate(conn, plan_id).totals` is equal before and after. Every existing profile has `basis == 'macros'`.
  - `test_0003_makes_veg_foods_veggie`: insert a `role='veg'` item before upgrading. After upgrading its `point_class == 'veggie'`, and other foods' `point_class IS NULL`.
  - `test_0003_seeds_point_rules_and_carb_basis`: `{row.point_type: row.grams_per_point}` equals `{'fat': 15.0, 'carb': 25.0, 'protein': 25.0, 'veggie': 10.0}`, and `carb_basis` is `'total'`.
  - `test_points_profile_must_not_store_kcal` and `test_macros_profile_must_store_kcal`: each violating INSERT raises `sqlite3.IntegrityError`.
  - `test_one_portion_per_food_and_source`: a second `('coach')` row for the same food raises `IntegrityError`, while a `('manual')` row beside it succeeds.
  - In `tests/test_snapshot.py`, `test_round_trip_includes_point_tables`: export, import into a fresh migrated database, re-export, and the files are byte-identical, including `point_rules.json`, `settings.json` and `point_portions.json`.

- [ ] **Step 2: Run** `uv run python -m pytest tests/test_migration_0003.py tests/test_snapshot.py -q`. Expected: FAIL, because no such table exists.

- [ ] **Step 3: Write `0003_points.sql`.**
  - Rebuild `macro_profiles` the way 0002 rebuilt `day_plans`: create `macro_profiles_new`, copy rows with `basis = 'macros'`, drop, and rename. Keep `UNIQUE (person_id, name, effective_on)`. Use this CHECK:
    ```sql
    CHECK ((basis = 'macros' AND kcal IS NOT NULL AND kcal > 0
            AND fat_pct IS NOT NULL AND carb_pct IS NOT NULL AND protein_pct IS NOT NULL
            AND abs(fat_pct + carb_pct + protein_pct - 100) < 0.5)
        OR (basis = 'points' AND kcal IS NULL AND fat_pct IS NULL
            AND carb_pct IS NULL AND protein_pct IS NULL))
    ```
  - Use `ALTER TABLE … ADD COLUMN` for the `foods` and `slot_templates` columns.
  - Finish with `UPDATE foods SET point_class = 'veggie' WHERE role = 'veg'`.

- [ ] **Step 4: Update `snapshot.py`.**
  - Add `point_rules` and `settings` after `people`, and `point_portions` after `food_units`.
  - In `import_database`, treat `point_rules` and `settings` as configuration: exclude them from the "already has data" refusal, and `DELETE FROM` both inside the import transaction before loading. Add a comment saying the migration seeds them, so a freshly migrated database is never empty there.

- [ ] **Step 5: Run** `uv run python -m pytest -q`. Expected: all pass, the 274 existing tests included.

- [ ] **Step 6: Commit** with the message `feat: migration 0003 adds point rules, portions, and points profiles`.

---

### Task 2: Points math (`yolk/points.py`)

**Files:**
- Create: `src/yolk/points.py`
- Modify: `src/yolk/macros.py` (add `sugar_alcohol_g`), `src/yolk/foods.py` (`macros_per_100g` reads it), `src/yolk/planning/plans.py` (`compare` carries it)
- Test: `tests/test_points.py`, `tests/test_macros.py`

**Interfaces:**
- Consumes: Task 1 tables.
- Produces:
  ```python
  # macros.py: Macros gains  sugar_alcohol_g: float = 0.0  (in __add__ and scale)
  @dataclass(frozen=True)
  class Points:
      fat: float = 0.0; carb: float = 0.0; protein: float = 0.0; veggie: float = 0.0
      def __add__(self, other: "Points") -> "Points": ...
      def scale(self, factor: float) -> "Points": ...
      @staticmethod
      def zero() -> "Points": ...
  @dataclass(frozen=True)
  class PointRules:
      fat_g: float; carb_g: float; protein_g: float; veggie_g: float
      carb_basis: str            # 'total' | 'net'
  POINT_TYPES = ("fat", "carb", "protein", "veggie")
  def load_rules(conn) -> PointRules
  def set_carb_basis(conn, basis: str) -> None          # ValueError unless 'total'/'net'; commits
  def counted_carbs(m: Macros, basis: str, *, fiber_known: bool = True) -> float
  def effective_class(point_class: str | None, per_100g: Macros, rules: PointRules) -> str
  def points_for(m: Macros, cls: str, rules: PointRules, *, fiber_known: bool = True) -> Points
  def format_points(p: Points) -> str
  def point_hints(planned: Points, allotment: Points, tolerance: float = 0.25) -> tuple[str, ...]
  ```

- [ ] **Step 1: Write the failing tests** in `tests/test_points.py`. Rules are the seeded defaults unless a test says otherwise, and all values are exact.
  - `test_fat_and_protein_points`: `points_for(Macros(fat_g=15, protein_g=25), 'protein', R) == Points(fat=1, protein=1)`.
  - `test_carbs_are_carb_points_unless_veggie`: `Macros(carb_g=25)` with `'carb'` gives `Points(carb=1)`. `Macros(carb_g=10)` with `'veggie'` gives `Points(veggie=1)` and `carb == 0`.
  - `test_free_foods_score_zero`: `points_for(Macros(fat_g=5, carb_g=3, protein_g=2), 'free', R) == Points.zero()`.
  - `test_net_carbs_subtract_fiber_and_sugar_alcohol`: `counted_carbs(Macros(carb_g=9, fiber_g=5, sugar_alcohol_g=2), 'net') == 2` and `counted_carbs(…, 'total') == 9`.
  - `test_net_carbs_floor_at_zero`: `counted_carbs(Macros(carb_g=3, fiber_g=5), 'net') == 0`.
  - `test_net_with_unknown_fiber_counts_total` (Review Focus 3): `counted_carbs(Macros(carb_g=30), 'net', fiber_known=False) == 30`.
  - `test_automatic_class_is_largest`: per-100 g `Macros(fat_g=30, protein_g=25)` with `None` gives `'fat'`. `point_class='veggie'` overrides and gives `'veggie'`.
  - `test_format_orders_by_size_then_f_c_p_v`:
    - `Points(fat=0.5, protein=1)` → `"1P + ½F"`;
    - `Points(1, 1, 1, 0)` → `"1F + 1C + 1P"`;
    - `Points(protein=1.5)` → `"1½P"`;
    - `Points(fat=0.1)` → `"—"`;
    - `Points(carb=0.76, protein=0.96)` → `"1P + ¾C"`.
  - `test_hints_name_shortfalls_and_excess`. Matched means within ±0.25 inclusive, so a hint appears only
    when a type is off by more than 0.25:
    - `point_hints(Points(1, 0.6, 1, 0), Points(1, 1, 1, 0)) == ("½C short",)`, since 0.4 rounds to ½;
    - `point_hints(Points(1.5, 1, 1, 0), Points(1, 1, 1, 0)) == ("½F over",)`;
    - `point_hints(Points(1, 0.75, 1, 0), Points(1, 1, 1, 0)) == ()`, since exactly ¼ off is matched.
  - `test_set_carb_basis_validates`: `'net'` round-trips through `load_rules(db).carb_basis`, and `'gross'` raises `ValueError`.
  - In `tests/test_macros.py`, `test_sugar_alcohol_adds_and_scales`.

- [ ] **Step 2: Run** `uv run python -m pytest tests/test_points.py tests/test_macros.py -q`. Expected: FAIL with an ImportError.

- [ ] **Step 3: Implement.**
  - `format_points` rounds each type to the nearest 0.25 (`round(x * 4) / 4`). It renders whole parts plus `¼ ½ ¾` with the letter suffix F, C, P or V, sorts by rounded value descending with ties in F, C, P, V order, joins with `" + "`, and returns `"—"` when every type rounds to 0.
  - `point_hints` compares exact values. Where `|planned − allotment| > tolerance`, it emits `"<rounded diff as fraction><letter> short|over"`, in F, C, P, V order.

- [ ] **Step 4: Run** `uv run python -m pytest -q`. Expected: all pass.

- [ ] **Step 5: Commit** with the message `feat: points math over macros and point rules`.

---

### Task 3: Food-level points and portions

**Files:**
- Modify: `src/yolk/points.py`, `src/yolk/foods.py` (`FoodSummary`, `search_library`)
- Test: `tests/test_food_points.py`, `tests/test_search.py`

**Interfaces:**
- Consumes: Task 2.
- Produces:
  ```python
  @dataclass(frozen=True)
  class Portion:
      qty: float; unit: str; grams: float; source: str; claimed: str
  @dataclass(frozen=True)
  class OnePoint:
      qty: float; unit: str; grams: float; label: str   # label like "4 oz (113 g) → 1P + ¼F"
  def food_points(conn, food_id: int, grams: float, rules: PointRules) -> Points
  def fiber_known(conn, food_id: int) -> bool          # False when fiber_g_100g IS NULL (items only)
  def portions(conn, food_id: int) -> list[Portion]     # ordered manual, coach, label, claude
  def preferred_portion(conn, food_id: int) -> Portion | None   # first of portions()
  def one_point(conn, food_id: int, rules: PointRules) -> OnePoint | None
  def add_portion(conn, food_id: int, *, source: str, qty: float, unit: str, claimed: str,
                  commit: bool = True) -> None          # validates unit via units.to_grams
  # FoodSummary gains: point_class: str | None; one_point: OnePoint | None;
  #   coach: Portion | None; coach_points: Points | None; disagrees: bool;
  #   fiber_known: bool
  ```

- [ ] **Step 1: Write the failing tests** in `tests/test_food_points.py`.
  - `test_item_points_scale_with_grams`: an item with fat 10 and protein 25 per 100 g, at 200 g, gives `Points(fat=2*10/15, protein=2)` (approx).
  - `test_recipe_points_sum_components_under_their_own_class`: a recipe (servings=1) of 100 g chicken (protein 25/100 g) and 200 g broccoli (`point_class='veggie'`, carb 5/100 g), eaten whole (300 g), gives `protein ≈ 1`, `veggie ≈ 1`, `carb == 0`.
  - `test_recipe_with_missing_yield_raises` (Review Focus 2): `MissingYieldError` propagates.
  - `test_one_point_portion_falls_back_to_ounces`: an item with protein 25/100 g and no units of its own gives `unit == 'oz'` and `qty == 3.5` (100 g is 3.53 oz, rounded to the nearest ¼). Grams are recomputed from the rounded qty (≈99.2), and the label starts with `"3½ oz (99 g) → 1P"`.
  - `test_one_point_portion_uses_own_unit`: an item with protein 20/100 g and a `scoop = 31 g` unit gives `unit == 'scoop'` and `qty == 4.0` (125 g ÷ 31 g = 4.03, rounded to the nearest ¼).
  - `test_one_point_is_none_for_free_and_zero_macro` (Review Focus 1): a `point_class='free'` food gives `None`, and so does an oil (fat 100, carb 0) classed `'carb'`.
  - `test_portions_order_manual_first`: coach and manual rows exist, so `preferred_portion(...).source == 'manual'`. With only coach, `'coach'`.
  - `test_add_portion_rejects_unknown_unit`: raises `UnknownUnitError` and writes nothing.
  - In `tests/test_search.py`, `test_summary_flags_coach_disagreement`: a coach portion of 4 oz on a food whose protein is 15 g/100 g (≈0.68P) gives `disagrees is True`. At 25 g/100 g (≈1.13P), `disagrees is False`. The rule is the main type outside 0.75–1.25.

- [ ] **Step 2: Run** `uv run python -m pytest tests/test_food_points.py tests/test_search.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement.**
  - `food_points` scales an item's per-100 g macros by `grams / 100` and calls `points_for` with its effective class and `fiber_known`.
  - For a recipe, it recurses into `food_components` with each child's grams × `grams / cooked_yield_g`, reusing the cycle-detection approach of `foods._macros_resolved`. A recipe's own `point_class` is ignored.
  - `one_point` picks the main type from the effective class (a recipe uses the largest of its summed points). grams = `100 × grams_per_point ÷ main-type grams per 100 g`, using counted carbs for carb and veggie.
  - The display unit is the food's first own unit, falling back to `oz` for items. Round qty to the nearest 0.25, then recompute grams and label from the rounded qty.
  - `search_library` fills the new `FoodSummary` fields with one `load_rules` call per search.

- [ ] **Step 4: Run** `uv run python -m pytest -q`. Expected: all pass.

- [ ] **Step 5: Commit** with the message `feat: food points, one-point portions, coach portions`.

---

### Task 4: Points profiles and targets

**Files:**
- Modify: `src/yolk/people.py`
- Test: `tests/test_people.py`

**Interfaces:**
- Consumes: Tasks 1–2.
- Produces:
  ```python
  def create_points_profile(conn, person_id: int, *, name: str, effective_on: str,
                            kcal_tol_pct: float = 5.0, protein_tol_g: float = 8.0,
                            macro_pct_tol: float = 3.0, commit: bool = True) -> int
  # create_slot gains keyword  allotment: Points | None = None  (writes the four *_pts columns)
  def slot_allotments(conn, profile_id: int) -> dict[int, Points]   # empty for a macros profile
  def profile_basis(conn, profile_id: int) -> str
  # targets_for_profile(conn, profile_id) -> Macros: points profiles derive from allotments × rules,
  #   kcal = 9·fat + 4·carb + 4·protein (KCAL_PER_G_* constants)
  # current_profiles: ProfileChoice.kcal comes from targets_for_profile for both kinds
  ```

- [ ] **Step 1: Write the failing tests.**
  - `test_active_recovery_targets_match_the_coach`: create the six slots from spec §5.1 with their allotments. `targets_for_profile` gives `fat_g == 90`, `carb_g == 85`, `protein_g == 150` and `kcal == 1750`.
  - `test_points_profile_defaults_to_wider_kcal_window`: the stored `kcal_tol_pct == 5.0`.
  - `test_current_profiles_lists_points_profile_kcal`: the choice for "Active recovery" has `kcal == 1750`.
  - `test_slot_allotments_empty_for_macros_profile`.

- [ ] **Step 2: Run** `uv run python -m pytest tests/test_people.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement** to the interfaces above.

- [ ] **Step 4: Run** `uv run python -m pytest -q`. Expected: all pass.

- [ ] **Step 5: Commit** with the message `feat: points profiles derive targets from meal allotments`.

---

### Task 5: Evaluation with points

**Files:**
- Modify: `src/yolk/planning/evaluate.py`, `src/yolk/planning/plans.py` (`PlanSlot`)
- Test: `tests/test_evaluate_points.py`

**Interfaces:**
- Consumes: Tasks 2–4.
- Produces:
  - `EntryEvaluation` gains `points: Points | None` and `counted_carb_g: float | None`. Both are None exactly when `error` is set.
  - `SlotEvaluation` gains:
    - `points: Points`;
    - `allotment: Points | None`, None under a macros profile or for a slot with no template;
    - `hints: tuple[str, ...]`.
  - `DayEvaluation` gains:
    - `basis: str`;
    - `points: Points`;
    - `allotment: Points | None`;
    - `label_kcal: float`;
    - `fat_pct` and `carb_pct` (actual, as judged);
    - `target_fat_pct` and `target_carb_pct`.
  - For a points profile, `totals.kcal` is counted (9/4/4) and `totals.carb_g` is the sum of `counted_carb_g`. For a macros profile, `totals` is unchanged and `label_kcal == totals.kcal`.
  - `PlanSlot` gains `allotment: Points | None` from `slot_allotments`, so empty meals show their target.

- [ ] **Step 1: Write the failing tests** in `tests/test_evaluate_points.py`. Use a helper that builds the active recovery profile and simple synthetic foods: pure fat (100 g fat), pure protein (100 g protein), pure carb (100 g carb), and a veggie with carb 10 g/100 g. Give each food a label kcal deliberately off from 9/4/4 by +4%.
  - `test_exact_allotments_pass_whatever_the_labels_say`: fill every meal exactly. `ok is True`, and `totals.kcal == 1750` while `label_kcal ≈ 1820`.
  - `test_points_day_outside_kcal_window_fails`: add 12 g of the pure fat (+108 kcal, more than 5% of 1750). `within_tolerance['kcal'] is False`.
  - `test_meal_hint_does_not_fail_the_day`: move ½C of carb from 7:00 to 12:30. Slot 1's `hints == ("½C short",)`, slot 3's `hints == ("½C over",)`, and `ok is True`.
  - `test_net_basis_changes_counted_carbs`: a carb food with fiber, after `set_carb_basis(db, 'net')`, has smaller `totals.carb_g` and `points.carb`.
  - `test_slot_without_template_has_no_allotment` (Review Focus 4): an entry at `slot_no=7` has `allotment is None` and `hints == ()`, and the evaluation completes.
  - `test_macros_profile_unchanged`: the Keto Plan A seed's `evaluate` totals equal the Macros sum computed before this task (reuse `test_golden_keto_a` expectations), with `basis == 'macros'`.

- [ ] **Step 2: Run** `uv run python -m pytest tests/test_evaluate_points.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement.**
  - Load rules once per `evaluate`. Per entry: grams → `food_points(conn, food_id, grams, rules)`, and `counted_carb_g` from `counted_carbs(macros, basis, fiber_known=…)`.
  - A macros profile always uses `'total'` for `counted_carb_g`.
  - Target percentages are computed from the target `Macros` for both kinds. That is identical to the stored percentages for macros profiles, so the tolerance check reads target pcts, not profile columns.
  - `partial=True` behaviour is unchanged: an entry that cannot be measured has `points=None` and is excluded.

- [ ] **Step 4: Run** `uv run python -m pytest -q`. Expected: all pass, the golden Keto A tests included.

- [ ] **Step 5: Commit** with the message `feat: evaluate points days by counted macros, with per-meal point hints`.

---

### Task 6: The point system fixture, seed and golden test

**Files:**
- Create: `tests/fixtures/point_system.json`, `tests/test_seed_points.py`, `tests/test_golden_points_sample1.py`
- Modify: `src/yolk/seed.py` (`seed_point_system`), `src/yolk/cli.py` (`seed points` subcommand; `init --seed` loads both)
- Test: as above, plus `tests/test_cli.py`

**Interfaces:**
- Consumes: Tasks 1–5, and `sources.usda.get_food` / `parse_macros` (a fixture-building aid only; nothing at runtime calls USDA).
- Produces:
  ```python
  POINT_FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "point_system.json"
  @dataclass(frozen=True)
  class SeedReport:
      profile_id: int; created: list[str]; attached: list[str]
      macro_differences: list[str]; flagged: list[str]; already_seeded: bool
  def seed_point_system(conn, fixture_path: Path = POINT_FIXTURE_PATH) -> SeedReport
  ```
- Fixture shape (top-level keys):
  - `person`;
  - `profile`: `{name, effective_on, kcal_tol_pct, protein_tol_g, macro_pct_tol}`;
  - `slots`: a list of `{slot_no, name, time_of_day, fat, carb, protein, veggie}`;
  - `foods`: a list of `{name, brand, role, point_class, macros_100g:{kcal, fat_g, carb_g, fiber_g, protein_g}, source, source_ref, verified, units:{unit: grams}, portions:[{source, qty, unit, claimed}], source_note}`;
  - `samples`: `{"Sample Option 1": [{slot_no, entries:[{food, qty, unit}]}]}`;
  - `expected_misses`: a list of `{sample, slot_no, points:{fat, carb, protein, veggie}, reason}`.

- [ ] **Step 1: Build the fixture (session work, not code).**
  - Read both tabs of the coach workbook (`uv run --with openpyxl python -I -X utf8 <script> <xlsx>`, where the script lives in the scratchpad, never the repo). If the file cannot be opened, stop and ask Jen to make it available offline.
  - Take the union of the *Meal plan guidelines* lists and the *Quick Food List*. Resolve the four conflicts per spec §3: 25 almonds, 2 tbsp nut butter, 1.5 tbsp mayo, and turkey bacon by the chosen product's macros.
  - Include the free foods, with roles: broth `beverage`, mustard `sauce`, jello `sauce`, celery and leafy greens `veg`.
  - Add the Claude workbook's beef, chicken and veggie additions and its eight Costco items (from that tab's label figures) with `source: claude` portions and `verified: false`.
  - Add the foods Sample Option 1 needs that are not on the lists.
  - For each generic food, find the matching USDA FDC entry (cooked vs raw as the coach means it; `.env` has the key). Record `source: usda` and `source_ref`. For branded products use the label.
  - Each coach line becomes a `portions` row with `source: coach` and `claimed` in the coach's terms ("1P", "1F", "1C", "1V").
  - Compute each coach portion's main-type points. Any line outside 0.75–1.25 gets `"FLAG: computes 0.68P at coach portion"` in its `source_note`, keeps the coach's portion, and is listed for Jen in the task report.
  - Mark coach-list foods with USDA or label macros whose portion checks out as `verified: true`.
  - Slots and profile follow spec §5.1, effective 2026-10-31.

- [ ] **Step 2: Write the failing tests.**
  - `tests/test_seed_points.py`:
    - `test_fixture_is_self_consistent`: every portion and sample unit resolves through `units.to_grams` once seeded, every role and point_class passes the CHECKs, and every FLAG'd food is in `report.flagged`.
    - `test_seed_attaches_to_existing_foods`: on a Keto-A-seeded database, a fixture food whose `(name, brand)` already exists is in `report.attached`, not duplicated, and its macros are unchanged.
    - `test_seed_twice_is_a_no_op`: a second run gives `already_seeded is True`, and the row counts of `foods`, `point_portions` and `slot_templates` are unchanged.
    - `test_seed_requires_jen` (Review Focus 5): on an empty database it raises `YolkError` naming the person, and `foods` is empty after.
  - `tests/test_golden_points_sample1.py`, `test_sample_option_1_meals_land_on_their_allotments`: for each sample meal, sum `food_points` of its entries. Meals not in `expected_misses` are within ±0.25 of the slot's allotment for every type. Meals in it match the recorded `points` to ±0.01.
  - In `tests/test_cli.py`:
    - `test_seed_points_command_reports`: `main(["seed", "points"])` on a Keto-A database prints created, attached and flagged counts and returns 0.
    - `test_init_seed_loads_both`: after `init --seed`, there are two profiles, `training` and `Active recovery`.

- [ ] **Step 3: Run** `uv run python -m pytest tests/test_seed_points.py tests/test_golden_points_sample1.py tests/test_cli.py -q`. Expected: FAIL.

- [ ] **Step 4: Implement `seed_point_system`.**
  - Do it in one transaction, using `commit=False` helpers and rolling back on any exception, like `seed_keto_plan_a`.
  - "Already seeded" means the person already has a profile with the fixture's name and `effective_on`. Return the report without writing.
  - An existing food gets `point_class` set and portions added with `INSERT OR IGNORE` semantics on `(food_id, source)`. Note any macro difference over 5% on fat, carb or protein in `macro_differences`.
  - Add the CLI `seed` subparser with a `points` choice. `init --seed` calls `seed_point_system` after `seed_keto_plan_a` and prints its counts.

- [ ] **Step 5: Run** `uv run python -m pytest -q`. Expected: all pass.

- [ ] **Step 6: Commit** with the message `feat: seed the coach's point system lists and active recovery day`.

---

### Task 7: Points on the screens

**Files:**
- Modify:
  - `src/yolk/web/templates/foods/_results.html`, `plans/_slot.html`, `plans/_totals.html`;
  - `src/yolk/web/routes/drafts.py` (`add_food` default portion);
  - `src/yolk/units.py` or `points.py` (`entry_default(conn, food_id) -> tuple[float, str]`);
  - `src/yolk/web/static/app.css` (only what the new columns need).
- Test: `tests/test_web_points.py`

**Interfaces:**
- Consumes: Tasks 3, 5 and 6. `FoodSummary.one_point`, `.coach`, `.disagrees`; `SlotEvaluation.points`, `.allotment`, `.hints`; `PlanSlot.allotment`; `DayEvaluation.points`, `.allotment`, `.label_kcal`, `.basis`.
- Produces: the template filter `points` registered in `web/templating.py`, which calls `format_points`. `entry_default` returns `preferred_portion` qty and unit when one exists, and otherwise the existing `default_portion`.

- [ ] **Step 1: Write the failing tests** in `tests/test_web_points.py`. Use a client fixture over a database seeded by `init --seed` equivalents (`seed_keto_plan_a` then `seed_point_system`).
  - `test_food_list_shows_one_point_and_coach_portion`: searching "chicken breast" shows the coach's "4 oz" and a `→ 1P` label.
  - `test_flagged_food_shows_a_flag`: a food in `report.flagged` shows the text "coach says".
  - `test_points_plan_shows_allotments_on_empty_meals`: a new blank plan on Active recovery shows "Target 1F + 1C + 1P" under 7:00 and "Target 1F + 1C + 1P + 1V" under 8:30.
  - `test_adding_a_coach_food_uses_its_portion`: adding chicken breast to slot 1 creates an entry with `qty == 4` and `unit == 'oz'`.
  - `test_entry_rows_and_day_show_points`: after adding, the slot shows a Points cell `"1P"`. The totals section shows the day's points against `6F + 3C + 6P + 1V`, and shows label kcal.
  - `test_meal_hint_appears`: a 7:00 meal of 4 oz chicken breast plus 1 coach portion of fat, with no carb, shows "1C short".
  - `test_keto_plan_has_no_allotments`: the Keto Meal Plan A page contains no "Target" allotment text.

- [ ] **Step 2: Run** `uv run python -m pytest tests/test_web_points.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement the templates per spec §8.**
  - Add a Points column to results (`one_point.label` or "—") and a Coach column (`coach.qty unit = claimed`, plus "coach says X, macros say Y" when `disagrees`).
  - Add a Points column to entry rows.
  - Give the meal header its allotment, planned points and hints.
  - Add a points row to the totals section, plus a "label kcal" line when `basis == 'points'`.
  - Point `add_food` at `entry_default`.

- [ ] **Step 4: Run** `uv run python -m pytest -q`, then preview: start `yolk serve` through `.claude/launch.json` (create a `yolk` entry: `uv run python -m yolk serve`, port 8000, if missing) against a copy of the real database that has had `yolk seed points` applied. Open a new Active recovery plan, add foods, and take a screenshot.

- [ ] **Step 5: Commit** with the message `feat: show points on foods, meals, and day totals`.

---

### Task 8: Settings page and carb-basis switch

**Files:**
- Create: `src/yolk/web/routes/settings.py`, `src/yolk/web/templates/settings.html`
- Modify: `src/yolk/web/app.py` (include router), `src/yolk/web/templates/base.html` (nav link "Settings")
- Test: `tests/test_web_settings.py`

**Interfaces:**
- Consumes: `load_rules`, `set_carb_basis`.
- Produces: `GET /settings` (point sizes read-only, current basis) and `POST /settings/carb-basis` (form field `basis`, 303 back to `/settings`; anything other than total or net gives 422 with the message on the page).

- [ ] **Step 1: Write the failing tests.**
  - `test_settings_shows_point_sizes`: the page shows "15 g", "25 g" and "10 g", plus "Total" selected.
  - `test_switching_to_net_changes_points`: POST `basis=net`, then `/foods?q=beans` shows a smaller carb point label than before the switch.
  - `test_bad_basis_is_rejected`: `basis=gross` gives 422.
  - `test_cross_site_post_refused`: the existing same-origin guard covers the new POST (a request with a foreign `origin` gives 403).

- [ ] **Step 2: Run** `uv run python -m pytest tests/test_web_settings.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement** the route, template and nav link. Follow `routes/people.py` for a form POST that redirects.

- [ ] **Step 4: Run** `uv run python -m pytest -q`. Expected: all pass.

- [ ] **Step 5: Commit** with the message `feat: settings page with total/net carb switch`.

---

### Task 9: README and real-database rollout

**Files:**
- Modify: `README.md`

- [ ] **Step 1:** Document the point system in the README:
  - `yolk seed points` in the command table;
  - a "Planning on points" section: allotments, hints, the ±5% kcal window, and the Settings switch.
- [ ] **Step 2:** Back up and seed the real database:
  - `uv run python -m yolk export --out data/backup-2026-10-31` (git-ignored);
  - `uv run python -m yolk migrate`;
  - `uv run python -m yolk seed points`.
  - Paste the report, including every flagged coach line and macro difference, into the task summary for Jen.
- [ ] **Step 3: Run** `uv run python -m pytest -q`. Expected: all pass.
- [ ] **Step 4: Commit** with the message `docs: planning on points`.
