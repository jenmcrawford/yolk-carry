# Point System and Easier Food Entry — Design

**Date:** 2026-10-31
**Status:** Approved in brainstorming, not yet implemented
**Repo:** `yolk-carry` (package name: `yolk`)
**Builds on:** [`2026-10-01-plan-and-search-design.md`](2026-10-01-plan-and-search-design.md) (built and
merged as Part A and Part B). Where this document disagrees with an earlier one, this one wins.

---

## 1. Intent

Jen's coach has moved her from a calorie-and-percentage framework to a **point system**. One point is a
fixed number of grams of one macro: FAT = 15 g fat, CARB = 25 g carbs, PROTEIN = 25 g protein, VEGGIE =
10 g carbs from a vegetable. FREE foods are not counted. Each meal in the day gets an allotment such as
"1 FAT, 1 CARB, 1 PROTEIN."

The point system exists to make substitution easy and to keep her on plan when life is chaotic. "Swap the
chicken for something else worth about 1 protein" is a judgement she can make at a glance. "What is
25 g of protein?" is not. The math underneath is unchanged. Points are a human-scale view of the same
grams.

The roles of the two layers are Jen's own decision:

- **Macros judge the day.** Whether a day landed is still decided by calories, protein, fat and carbs
  against a target, using the app's existing tolerances.
- **Points break the day into meals** and give each planned meal a quick human check ("this came out to
  1P + ½F").

Jen asked that this round produce **a usable prototype**, and said the moment she most wants made easier
is **bringing new foods in**. After her last Costco run, she gave her Instacart receipt to Claude and asked
for the items in points. The answer was good, but it landed in a spreadsheet tab, with unconfirmed numbers,
and never reached the app. Today Yolk Carry has no way to add a food from the web app at all. Every food
came in through code.

### Source material

- `C:\Users\jcraw\OneDrive\Documents\meal_planning\Jen Crawford Point System Plan.xlsx` is **from the
  coach and is the source of truth.** It has two tabs: *Meal plan guidelines* (the day grid, sample meals,
  and portion lists by point type) and *Quick Food List*.
- `...\Jen Crawford Point System Plan Claude.xlsx` is a copy Claude extended. It adds beef, chicken and
  veggie options, a third sample column and a *Costco Items* tab. Those additions are **not** from the
  coach. They are approximate (labels, retailer listings, USDA averages) and go in as unverified.
- A schema handoff note from a 2026-10-31 session proposed a 13-table design. This document keeps its
  principles (store macros per 100 g, derive every point value, make point sizes data, let a
  veggie/carb override exist) and drops most of its tables for now (§9).

Neither workbook is in the repo, and neither should be committed. They hold a coach's paid work.

The workbooks live in OneDrive and may be cloud-only. A subagent could not open them, though the main
session could. Whoever builds the fixture must be able to read them, or Jen pastes the lists in.

---

## 2. Goals, non-goals, anti-goals

### Success criteria

1. Every food shown in the app (food list, picker, plan entries) shows its points, computed from stored
   macros, for example "5 oz birria = 1P + ½F".
2. The active recovery day exists as a profile with six meals and their point allotments. A plan on it
   shows each meal's points against its allotment, and judges the day with the existing macro tolerances
   against targets derived from the points.
3. The coach's portion lists are in the library as foods. Each has its coach portion and point class,
   and is flagged wherever its macros disagree with the coach.
4. A new food can be added in the web app, from USDA or by typing a label, with its points previewed
   before saving.
5. A receipt handled by Claude in a session ends as a CSV file that one command imports into the
   library.
6. Switching carbs from total to net is one setting, and every point value and carb figure follows it
   with no food edited.

### Non-goals for this round

- Purchases, prices, cost per point.
- Stock on hand and "inventory points." The existing `inventory` table is untouched.
- Generating the Excel workbook from the database.
- Calling Claude from inside the app (receipt reading, "describe a recipe"). That work stays in a Claude
  Code session. The app only imports what the session writes.
- Training-day and rest-day point profiles. They will be added later as data, through the same seed
  mechanism, with no code change.
- Raw-to-cooked yield factors, food versioning by UPC, a separate `food_sources` table, a staging
  `food_inbox` table.
- Composite tolerance rules beyond the per-meal hint in §5.4.
- The deferred web-app follow-ups recorded after Part B. They stay deferred unless one blocks this work.

### Anti-goals: it fails even if it works when

- **The app quietly overrides the coach.** Where computed points disagree with a coach portion, the app
  shows both and flags the line. It never rewrites the coach's portion.
- **Points become a second source of truth.** Points are never stored on a food or an entry. They are
  computed from macros and the point rules every time.
- **Adding a food takes longer than typing a label.** If the add-a-food page needs more than the label's
  numbers, a name and a class, it is too heavy.
- **Unchecked data looks checked.** Anything not confirmed against a package or the coach's sheet carries
  the existing "unchecked" badge.

---

## 3. Decisions made in brainstorming

| Question | Decision | Whose |
|---|---|---|
| Role of points vs macros | Macros judge the day; points split it into meals and check each meal | Jen |
| Day types this round | Active recovery only | Jen |
| Day tolerance | Same as the existing macro tolerances (protein ±8 g, fat and carb ±3 percentage points), except calories | Jen |
| Calories on a points day | Counted from grams (9/4/4), with a wider window than ±1%. Seeded at ±5% | Jen; the 5% is Claude's call |
| Source of truth for portions | The coach's original workbook | Jen |
| When the coach's tabs disagree | Use the macro definition of a point to decide | Jen |
| Total or net carbs | **Total** for now, with an easy switch to net | Jen |
| Scope of this round | The four-part prototype in §4 to §7 | Jen |
| Per-meal check | Within ¼ point per point type, shown as a hint, never a failure | Claude's call |
| Receipts | Read by Claude in a session, written to a CSV the app imports | Claude's call, from the agreed scope |

### The coach's conflicting lines, resolved by macros

The two coach tabs disagree on four portions. Each resolves to the version that matches the point
definition:

| Food | Guidelines tab | Quick Food List | Kept | Why |
|---|---|---|---|---|
| Almonds | 25 | 15 | **25 almonds** | ~0.6 g fat each, so 25 ≈ 15 g |
| Nut butter | 2 tbsp | 1.5 tbsp | **2 tbsp** | ~8 g fat per tbsp |
| Mayo | 1.5 tbsp | 1 tbsp | **1.5 tbsp** | ~10 g fat per tbsp |
| Turkey bacon | 7 slices | 6 slices | **check by macros** | Decide from the chosen product's label |

Items that appear on only one coach tab (orange, grapefruit, sashimi, Premier shake, egg yolks, Quest Bar)
are included.

---

## 4. Points: rules and computation

### 4.1 Schema (migration `0003_points.sql`)

Migrations stay forward-only, use only portable SQL types (INTEGER, TEXT, REAL), use CHECK constraints
for enums, and store dates as ISO-8601 TEXT. The runner owns transactions and the foreign-key pragma, as
before.

```sql
CREATE TABLE point_rules (
    point_type      TEXT PRIMARY KEY
                    CHECK (point_type IN ('fat', 'carb', 'protein', 'veggie')),
    grams_per_point REAL NOT NULL CHECK (grams_per_point > 0)
);
-- seeded: fat 15, carb 25, protein 25, veggie 10

CREATE TABLE settings (
    key     TEXT PRIMARY KEY,
    value   TEXT NOT NULL
);
-- seeded: ('carb_basis', 'total'); the library validates the value is 'total' or 'net'
```

`foods` gains:

- `point_class TEXT` with `CHECK (point_class IS NULL OR point_class IN ('fat', 'carb', 'protein',
  'veggie', 'free'))`. NULL means automatic (§4.2). The migration sets `point_class = 'veggie'` on
  existing foods whose `role = 'veg'`. Veggie vs carb is a judgement, not something the macros can
  decide, so the class is an override.
- `sugar_alcohol_g_100g REAL`, nullable, used only when carbs are counted net.

A new table records the portion a source says is one serving of points:

```sql
CREATE TABLE point_portions (
    food_id     INTEGER NOT NULL REFERENCES foods(id) ON DELETE CASCADE,
    source      TEXT NOT NULL CHECK (source IN ('coach', 'claude', 'label', 'manual')),
    qty         REAL NOT NULL CHECK (qty > 0),
    unit        TEXT NOT NULL,          -- must resolve through units.to_grams
    claimed     TEXT NOT NULL,          -- what the source says it counts as, e.g. '1P + 1/2F'
    PRIMARY KEY (food_id, source)
);
```

A food can carry one portion per source, so the coach's portion is never lost:

- **Coach rows are read-only in the app.** Only the seed writes them.
- Jen's own portion is a `manual` row beside the coach row.
- The portion used when adding the food to a meal is the first that exists, in this order: `manual`,
  `coach`, `label`, `claude`.

`claimed` is kept as the source wrote it so the app can show the coach's words beside the computed
points. The builder may store it structured (four numbers) instead, as long as the original text stays
visible. *(Claude's call, from the builder check.)*

Point sizes are global, not per person. A second person on different sizes is a later change.

`snapshot.TABLES` gains `point_rules`, `settings` and `point_portions`, in parent-before-child order.

### 4.2 Computing points

A new module, `yolk/points.py`, holds pure functions over `Macros` plus the rules. The existing rule that
the web layer does no arithmetic and no SQL still holds.

- **Carbs counted.** Under `total`, carbs = `carb_g`. Under `net`, carbs = `carb_g − fiber_g −
  sugar_alcohol_g`, floored at zero. Under `net`, a food whose fiber is NULL falls back to total carbs and
  is flagged "fiber unknown." `Macros` gains a `sugar_alcohol_g` field (default 0) so net carbs add up
  correctly across a meal.
- **Effective class.** It is `point_class` when set. Otherwise it is whichever of fat, carb or protein
  gives the most points for the food.
- **Points for a portion:**
  - fat = fat_g ÷ 15 and protein = protein_g ÷ 25, for every food.
  - Carbs count as **veggie** points (carbs ÷ 10) when the effective class is veggie. Otherwise they
    count as carb points (carbs ÷ 25).
  - **Free** foods score zero points of every type. Their macros still count toward the day's totals.
- **Points add up linearly**, so a meal's points are the sum of its entries' points, and a day's points
  are the sum of its meals' points.
- **Recipes** (`kind = 'recipe'`) score the sum of their components' points, each component under its
  own class, scaled to the portion eaten. That way a stir-fry's broccoli stays veggie rather than turning
  into carb points. A recipe's own `point_class` is ignored. *(Claude's call, from the builder check.)*
- **Display.** Round to the nearest ¼ and show quarters as fractions: "1P + ½F", "1F + 1C + 1P". Leave
  out any type that rounds to zero. Exact values are available for the checks in §5.4.
- **One point's portion.** For the food's main macro (the effective class, or the largest when the class
  is automatic): grams = 100 × grams_per_point ÷ that macro's grams per 100 g. Show it in the food's
  default unit, rounded to the nearest ¼ of that unit, plus grams. If the food has no unit of its own,
  show ounces for solids. Free foods, and foods with zero of their main macro, have no one-point portion.

### 4.3 The carb setting

A small **Settings** page, linked in the header, shows the point sizes (read only) and a total/net switch.
Switching is a POST that changes `settings.carb_basis`. Every page computes from the setting at request
time, so nothing is recomputed or stored.

Under the macro profiles that already exist (the `training` profile behind Keto Meal Plan A), the day
evaluation always uses total carbs, as the coach who wrote those plans did. The setting only affects points, and the carb figures of point
profiles.

---

## 5. The active recovery day

### 5.1 Profile and meals

`macro_profiles` gains `basis TEXT NOT NULL DEFAULT 'macros' CHECK (basis IN ('macros', 'points'))`.
Changing the table's CHECKs means rebuilding it, using the procedure migration 0002 used for `day_plans`.
After the rebuild:

- A `macros` profile requires `kcal`, `fat_pct`, `carb_pct` and `protein_pct`, as today.
- A `points` profile requires all four to be NULL. Its targets are always derived (§5.2), so nothing
  stored can drift from the points.
- The tolerance columns stay on both kinds.

`slot_templates` gains `fat_pts`, `carb_pts`, `protein_pts` and `veggie_pts`, all `REAL NOT NULL DEFAULT
0 CHECK (… >= 0)`. These are each meal's allotment. Under a macros profile they stay zero.

The active recovery day, from the coach's sheet:

| Slot | Time | Name | Allotment |
|---|---|---|---|
| 1 | 07:00 | 7:00 | 1F 1C 1P |
| 2 | 10:00 | 10:00 | 1F 1P |
| 3 | 12:30 | 12:30 | 1F 1C 1P |
| 4 | 15:00 | 3:00 | 1F 1P |
| 5 | 17:30 | 5:30 | 1F 1P |
| 6 | 20:30 | 8:30 | 1F 1C 1P 1V |

The profile is named "Active recovery", belongs to the existing person Jen, and takes effect 2026-10-31.

### 5.2 Targets

For a points profile, `targets_for_profile` adds up its slots' allotments and multiplies by the point
rules:

- fat 6 × 15 = 90 g; carbs 3 × 25 + 1 × 10 = 85 g; protein 6 × 25 = 150 g.
- kcal = 9 × fat + 4 × carbs + 4 × protein = 1,750.
- Target percentages are computed from those grams (about 46% fat, 19% carb, 34% protein).

These numbers reproduce the totals the coach wrote in column G of the guidelines tab (90, 75 + 10, 150).
A test pins them.

### 5.3 Judging the day

`evaluate()` is unchanged for macros profiles. For a points profile:

- The carb total follows the carb setting.
- **Calories are counted from grams**: 9 × fat + 4 × carbs + 4 × protein, using the carbs the setting
  counts. That is the same arithmetic that builds the target, so a day that hits every allotment exactly
  always passes on calories. Label calories are still stored and shown, but not judged. *(Jen's
  decision.)*
- Fat and carb percentages compare the actual share of those counted calories against the **derived**
  target percentages, not stored columns.
- Tolerances come from the profile's own columns. A points profile uses a **wider calorie window**
  (Jen's decision): the active recovery profile is seeded with `kcal_tol_pct = 5.0`, about ±88 kcal.
  The 5% figure is Claude's call, and it is a data value Jen can change. Protein stays ±8 g, and fat and
  carb stay ±3 points.

Macros profiles keep label calories and ±1%, unchanged.

`DayEvaluation` gains each slot's points and allotment, and the day's total points and allotment, so
templates do not compute them.

### 5.4 Checking each meal

Each meal shows its allotment and its actual points, for example "Target 1F 1C 1P · Planned 1F ¾C 1P."
A point type counts as matched when the exact value is within **±0.25** of the allotment. A meal off by
more shows a gentle "off by ¼C" hint. It never marks the day failed. The day's pass or fail is §5.3
alone.

---

## 6. Loading the coach's lists

### 6.1 The seed file

The coach's lists become a committed fixture, `tests/fixtures/point_system.json`, in the style of
`keto_plan_a.json`. It holds:

- the active recovery profile and its six slots;
- every food from both coach tabs, and the free foods (§3 gives the union and the four resolved
  conflicts). Each food gets per-100 g macros (kcal, fat, total carbs, fiber, protein), a point class,
  its unit conversions, its coach portion (`qty`, `unit`, `claimed`, `source: coach`) and a
  `source_note`;
- the Claude-added beef, chicken and veggie options and the eight Costco items, with `source: claude` on
  their portions;
- sample options are **not** seeded as plans.

**Building the fixture is session work, not code.** For each coach line, find the USDA FoodData Central
entry that matches what the coach means: cooked or raw, the stated cut, plain or prepared. Record its FDC
ID. Use the label for branded products (Quest Bar, Premier shake, Crepini, Kevin's). Use the earlier
Costco tab's label figures for the Costco items. Then check each coach portion against the point
definition. A line whose main macro computes outside 0.75 to 1.25 points at the coach's portion is kept
as the coach wrote it, flagged in its `source_note`, and listed for Jen in the implementation summary.
Coach portions on the guidelines tab look like they count total carbs, which is why total is the
default.

Coach-list foods are marked **verified** where the macros came from USDA or a label and the coach's
portion checks out. Claude-added foods and the Costco items are **unverified**.

### 6.2 Getting it into the real database

The real `yolk.db` already holds Jen, Keto Plan A and its foods. A new command, **`yolk seed points`**,
adds the fixture to an existing database:

- Jen is looked up by name; the command fails clearly if she does not exist.
- A food is matched on `(name, brand)`. An existing food gets its point class and coach portion attached
  instead of a duplicate. Its macros are left alone, and any disagreement goes in the command's report.
- It runs in one transaction and is safe to run twice: the second run changes nothing.
- `yolk init --seed` also loads it after Keto Plan A, so a fresh database has both.

---

## 7. Adding a food

### 7.1 In the app

A **New food** button on the Foods page opens `/foods/new`, which has two ways in.

**From a label.** Fields:

- name and brand;
- serving size in grams, plus an optional household unit for that serving (for example "4 pancakes",
  "1 pouch");
- kcal, fat, total carbs, fiber, sugar alcohols (optional) and protein, **per serving, as printed**;
- **counts as:** fat, carb, protein, veggie, free or automatic (the default). This sets `point_class`;
- optional notes.

**Role.** `foods.role` stays NOT NULL, and the form does not ask for it separately. It comes from "counts
as":

- fat, carb or protein → the same role;
- veggie → `veg`;
- automatic → the role of the macro that gives the most points.

Only when "free" is chosen does a second small choice appear: veg, sauce or beverage. Broth is a
beverage, mustard a sauce, celery a veg. The CSV and the fixture follow the same rule. *(Claude's call,
from the builder check.)*

The library converts per-serving figures to per-100 g. While she types, an htmx preview shows the
serving's points and the one-point portion, so "4 pancakes = 1C + ¾P" is visible before she saves.
Saving creates an unverified item with `source = 'label'`. The household unit becomes a `food_units`
row and the food's `point_portions` row (`source: label`, `claimed` = the computed points at save time).

**From USDA.** A search box calls the existing `sources.usda.search_foods`. Choosing a result previews
its per-100 g macros and points. Saving calls `import_food`, then records the chosen point class. A
missing USDA key shows a plain message pointing at `.env`, not an error page.

Both paths go through library functions. Routes stay thin, as in Part B.

### 7.2 Checking and fixing a food

Each food gets a page, `/foods/{id}`, showing its macros, units, points, coach portion with any
disagreement, source and verified state. Two actions:

- **Mark checked** sets `verified = 1` and `verified_on` to today.
- **Edit** changes name, brand, macros, point class, units and Jen's own (`manual`) portion. It never
  touches the coach's row. An edit applies everywhere the food is used. That is correct, since a
  corrected label should correct every plan. Editing a checked food clears its checked state.

Recipes (`kind = 'recipe'`) are read-only on this page. Their macros come from components.

### 7.3 From a receipt, through Claude

Receipts stay a Claude Code session activity, as last time. The difference is where the answer lands.

- A template, `docs/food-inbox-template.csv`, defines the columns: `name, brand, store, serving_text,
  serving_g, kcal, fat_g, carb_g, fiber_g, sugar_alcohol_g, protein_g, point_class, unit, unit_g,
  source_note`. Figures are per serving, matching the label form.
- `docs/food-inbox.md` is a short runbook for the session. Read the receipt, find each product's label
  figures, fill the CSV, and note where each number came from.
- **`yolk import-foods FILE.csv`** validates every row first. If any row is bad, it reports every bad row
  with its line number and imports nothing. If all rows are valid, it creates them as unverified
  `label` foods and skips any `(name, brand)` that already exists, naming each skip.

---

## 8. What the screens show

Text in this section describes intent. Layout and styling are the builder's, within the existing
`app.css`.

- **Food list and picker** (`foods/_results.html`): adds a points column for the one-point portion, for
  example "4 oz (113 g) → 1P" or "5 oz → 1P + ½F". Adds a coach column showing the coach portion, and a
  flag when the computed points disagree with it. The per-100 g macro columns stay.
- **Adding to a meal:** a food with a `point_portions` row is added at that portion, and the entry's unit
  is the portion's unit. Other foods keep today's default (one of their own unit, or 100 g).
- **Plan entry rows** (`plans/_slot.html`): add a Points column ("1P ½F").
- **Meal header:** the allotment, the planned points and the ±¼ hint (§5.4). Meals under a macros
  profile show no allotment.
- **Day totals** (`plans/_totals.html`): the existing macro table, plus a row showing the day's points
  against the day's allotment (6F 3C 6P 1V).
- **Header nav:** Foods, Plans and a new Settings link.

---

## 9. What the handoff note proposed that is deferred

| Handoff table or idea | This round |
|---|---|
| `food_nutrients`, `food_sources` (several sources per food) | One set of macros per food, with `source` and `source_ref` as today |
| `food_inbox` staging table | Unverified foods plus the CSV import. The "unchecked" badge is the inbox |
| `yield_factors` | Deferred |
| `purchases`, prices | Deferred |
| `inventory` points | Deferred |
| `recipes`, `recipe_items` | Already exist as `kind = 'recipe'` and `food_components` |
| `meal_slots` | Already exist as `slot_templates`; they gain point allotments |
| `plans`, `plan_items` | Already exist as `day_plans`, `day_plan_entries` |
| `tags`, `food_tags`, client constraints | Already exist with protocols; unchanged |
| Views computing points in SQL | Points are computed in Python (`yolk/points.py`), the same way macros already are |
| Excel output | Deferred |

The handoff's open questions on sugar alcohol types, missing fiber, veggie size, canonical source,
reformulations and dairy taxonomy are settled here only as far as the prototype needs:

- all sugar alcohols are subtracted under net;
- missing fiber falls back to total carbs and is flagged;
- veggie stays at 10 g;
- the coach is canonical for portions, and labels are canonical for branded macros.

The rest stay open.

---

## 10. Testing

The existing style holds: a fresh in-memory database built by applying every migration, library tests
for the math, web tests through the TestClient.

- Points math: each point type, veggie vs carb by class, free foods score zero, net vs total, missing
  fiber under net, ¼ rounding and fraction display, one-point portion in units.
- Targets: the active recovery profile derives 90 / 85 / 150 g and 1,750 kcal.
- Evaluation: a points-profile day inside and outside each tolerance, and the per-meal ±0.25 match. A
  day that hits every allotment exactly passes, whatever its foods' label calories say.
- Migration 0003: existing foods and profiles survive the rebuild, and `role = 'veg'` foods become
  veggie.
- Seed: `yolk seed points` on a database with Keto Plan A attaches to existing foods, and is a no-op the
  second time.
- Golden check: the points-world counterpart of the Keto Plan A golden test. The fixture stores the
  coach's *Sample Option 1* as data (`samples` in `point_system.json`, not seeded as a plan):

  | Meal | Coach's Sample Option 1 |
  |---|---|
  | 7:00 | ~1 cup potatoes + 2 eggs + 2 bacon |
  | 10:00 | 1 scoop protein + 2 tbsp almond butter |
  | 12:30 | Quest Bar + ½ orange |
  | 3:00 | 3 slices deli turkey + 2 oz sharp cheddar |
  | 5:30 | 25 almonds + 1 scoop whey protein |
  | 8:30 | 4 oz salmon + 1 cup steamed broccoli + ½ cup rice |

  The test builds each meal and asserts that **each meal's total** is within ±0.25 of its allotment for
  every point type. The coach's samples are rough ("~1 cup"), so a meal may miss honestly. Any meal that
  misses is listed in the fixture under `expected_misses`, with its computed points and the reason. The
  test asserts those meals miss by the recorded amount, so a later data change that fixes or worsens one
  shows up. *(Claude's call, from the builder check.)*

  Foods the samples need that are not on the coach's lists (eggs, cheddar, potatoes, bacon) go into the
  fixture with the other foods.
- Food entry: label form converts per serving to per 100 g, preview shows points, save is unverified,
  mark checked works, editing a checked food clears it.
- CSV import: one bad row imports nothing and names the line; duplicates are skipped and named.
- Settings: switching to net changes a high-fiber food's carb points on the next page load.

---

## 11. Left to the builder

- Module boundaries beyond `yolk/points.py`, function names, and how `DayEvaluation` carries points.
- Whether `claimed` is stored as text or as four numbers (the original text must stay visible).
- Page layout, wording of hints and flags, and whether the label preview updates on each keystroke or on
  change.
- How the USDA search results are paged or limited.
- The exact FDC entry chosen for each coach line, subject to §6.1.
- Splitting the work into implementation plans. A natural split is (A) points, migration, profile and
  seed, then (B) adding, checking and importing foods.
