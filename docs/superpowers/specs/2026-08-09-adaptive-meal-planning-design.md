# Adaptive Meal Planning — Design

**Date:** 2026-08-09
**Status:** Approved, not yet implemented
**Repo:** `yolk-carry` (package name: `yolk`)

---

## 1. Goal

Jen follows a fixed nutritional framework authored by a coach: two daily macro profiles,
six meal slots, defined fasting windows, and dietary constraints. The current delivery
mechanism is hand-authored Excel workbooks (dated 7.14.26) exported to PDF.

The working pattern is a **small rotation that persists** — three or four day-plans reused
for roughly a month — not a freshly generated week. The coach's own naming reflects this:
Keto A / B / C, plus Emergency plans for January, February, and April.

The system's job is **to keep her on framework while allowing improvisation.** Not to
dictate meals from inventory, and not merely to compute macros. Specifically:

- Hold the rotation as durable, named, editable objects.
- Make *changing* something cheap: swap a protein, run out of a sauce, take a grocery-store
  find and know where it fits — and immediately know whether the day still lands on target.
- Make *adding a food* a single uniform operation, so the food library grows without friction.

### Success criteria

1. A day-plan can be evaluated against its profile in one call, with per-slot breakdown,
   deltas, and any protocol violations.
2. Substituting one food for another produces a valid variant with flex quantities
   re-solved, without mutating the parent plan.
3. Given a new food, the system can say which slots it fits and at what quantity.
4. The engine reproduces the macro totals of an existing coach-authored plan within
   tolerance, from that plan's own ingredients.
5. Adding a food from USDA, a barcode, or a label is one operation with the same result shape.

### Explicit non-goals for v1

These were in the original brief and are **deliberately cut**, because inventory biases
plans rather than dictating them, so a thin inventory still yields valid plans:

- **Receipt ingestion and `store_aliases`.** The riskiest, least-verified part of the
  original design — no one has confirmed that Costco's receipt export format exists or is
  parseable. Build later if manual entry proves to be the real friction.
- **Barcode scanning as a routine capture path.** Reserved for onboarding new SKUs.
- **Continuous depletion tracking.** Inventory is updated when convenient, not maintained.
- **Bulk import of the existing xlsx workbooks.** Selective, opportunistic import only.
- **Cronometer as a data layer.** Rejected: no public API; community MCP servers mimic the
  internal GWT-RPC protocol with per-deploy hardcoded hashes that break on each new build.
  It may remain a logging surface. It is not a store.
- **Instacart / cart integration.**
- **Multi-person shared inventory contention.** The schema carries a person dimension;
  allocating one freezer across competing plans is a separate problem.

---

## 2. Fixed requirements

These come from the coach's framework and are treated as given.

### Macro profiles

| Profile | kcal | Fat % | Carb % | Protein % | Fat g | Carb g | Protein g |
|---|---|---|---|---|---|---|---|
| Training day | 2150 | 34 | 28 | 38 | 81.2 | 150.5 | 204.3 |
| Rest / no-prep | 2115 | 39 | 18 | 43 | 91.7 | 95.2 | 227.4 |

Gram targets are derived (`kcal × pct ÷ 9` for fat, `÷ 4` for carb and protein) and stored
as derived values, not hand-entered.

**Profiles are data, not constants.** Rows carry `effective_on`, so recalculation as body
composition changes is a new row — not a code edit, and not a loss of history.

### Tolerance

| Target | Tolerance | Treatment |
|---|---|---|
| Calories | ±1% | Hard — heavily weighted in the solver |
| Protein | ±8 g | Moderate — see measurement below |
| Fat % | ±3 points | Band — lightly weighted |
| Carb % | ±3 points | Band — lightly weighted |

Rationale: calories are what the framework is actually defending. Fat and carb trade against
each other and matter directionally.

**Measured against the source material.** Keto Plan A's own stated totals are 2146.35 kcal,
83.54 g fat, 150.94 g carb, 197.455 g protein, against a 2150 kcal / 34-28-38 profile:

| Target | Goal | Actual | Delta |
|---|---|---|---|
| Calories | 2150 | 2146.35 | −3.65 (0.17%) |
| Protein | 204.25 g | 197.455 g | **−6.80 g (3.33%)** |
| Fat % | 34.00% | 35.03% | +1.03 points |
| Carb % | 28.00% | 28.13% | +0.13 points |

So the earlier assumption that the hand-authored plans hit ±1.5% on all four **was wrong.**
Calories are tight — 0.17% — but protein is off by 6.8 g. An original ±2 g protein rule
would have classified a professionally authored plan as out of band, which would make the
tolerance model describe an aspiration rather than the framework.

Protein tolerance is therefore **±8 g** (~4% of target, with headroom). Calories stay hard at
±1%; that is the constraint doing the real work.

**Tolerance is stored per profile**, so tightening it later is a data change, not a code edit.

### Meal slots

| Slot | Time | Character |
|---|---|---|
| Meal 1 | 6:30am | Wake. Buff Chick Coffee. Effectively fixed. |
| Meal 2 | 8:30am | Breakfast |
| Meal 3 | 11:00am | Snack — must be portable, no prep |
| Meal 4 | 2:00pm | Lunch |
| Meal 5 | 3:00pm | **Intraworkout, training days only.** Fixed, non-negotiable: 0.5 scoop Karbolyn + 1 packet Liquid IV + 0.75 scoop highly branched cyclic dextrin |
| Meal 6 | 6:00pm | Dinner — hot meal: protein anchor + vegetable + sauce, optional carb |

Training days: 3pm session, 60–90 minutes, four days per week. The fast extends two hours
past waking; before Meal 1, only water, lemon, BCAAs, black coffee, or tea.

Slot 5 exists only on the training profile. Slots marked `fixed` are excluded from
substitution and flex adjustment.

### Dietary constraints

- Gluten-free.
- Mostly dairy-free — **fermented dairy is acceptable** (kefir, skyr, Greek yogurt).
- Whole-foods oriented, hormone-supportive.
- **Hard-boiled eggs excluded.** Other egg preparations are fine.

These are not special-cased in code. They are seeded as protocol rows like any other:
`gluten-free` as a built-in protocol excluding the `gluten` tag; a personal protocol owned by
Jen excluding the `dairy` tag with an exception for the `fermented-dairy` tag, and excluding
the hard-boiled-egg food by id. Adding candida, gut-health, or PCOS protocols later uses the
identical mechanism.

### Sourcing and prep

- Stores: Sprouts, Whole Foods, Costco, Trader Joe's.
- Souper cubes for frozen portions; bulk proteins cooked in pre-measured portions.
- Meals assembled from combinations of pre-cooked freezer components.
- **Flavor and spice matter a great deal.** Sauces are the primary variety driver.
  Macro-friendly takes on popular dishes are explicitly welcome.

### Client data note

The source plan headers list Weight 198 lb, Fat Mass 148.5 lb, LBM 49.5 lb. **Confirmed
transposed** — the correct values are LBM 148.5 lb, Fat Mass 49.5 lb (~25% body fat). The
corrected figures are what get stored.

---

## 3. Architecture

### Operating model

Python library plus SQLite, with Claude Code as the primary front door.

The split is deliberate: **code owns the arithmetic, Claude owns the judgment.** Macro math,
unit conversion, flex solving, protocol resolution, gap lists, and Excel output are
deterministic and belong in tested code. Choosing a sauce, judging whether a week has enough
variety, deciding whether a grocery find is worth a variant — that is judgment, done in
session against the library's callable surface.

This means the library must expose **structured return values, not printed text**. Every
operation returns dataclasses. A thin CLI wraps the few operations Jen would run herself.

### Environment

- Local Windows machine, `uv`-managed Python environment.
- SQLite file lives in the repo, under git. No upload/download ritual between sessions.
- Network access confirmed working: USDA FoodData Central (key in `.env` as `USDA_API_KEY`,
  verified HTTP 200) and Open Food Facts (no key required).
- `.env` is gitignored (`.gitignore:151`).

### Layout

```
src/yolk/
  db/
    schema.sql          -- portable SQL: explicit types, explicit PKs, FKs on
    connection.py
    migrations/
  models.py             -- dataclasses mirroring the schema
  units.py              -- unit → gram resolution
  macros.py             -- per-100g normalization, aggregation
  foods.py              -- food CRUD, recipe composition, derived tags, cycle detection
  protocols.py          -- rule resolution, violation reporting
  inventory.py
  planning/
    evaluate.py         -- evaluate()
    solve.py            -- resolve_flex()
    substitute.py       -- substitute()
    fit.py              -- fit()
    gaps.py             -- gap_list()
  sources/
    usda.py
    openfoodfacts.py
    cache.py            -- raw response cache on disk
  export/excel.py
  cli.py
tests/
examples/               -- six coach-authored plan PDFs
docs/superpowers/specs/
```

**Portable SQL throughout** — explicit types, explicit primary keys, no reliance on implicit
rowids — so a later move to Postgres stays open. SQLite is correct now: single file, real
joins and foreign keys, zero ops. Postgres's advantages (concurrency, JSONB, hosted access)
do not bite at a few thousand rows and one user.

---

## 4. Data model

### Core decision: one `foods` table

Purchased mayo and homemade chimichurri are both sauces. Both are measured by the tablespoon
and both go into dinners. Splitting them across separate `items` and `sauces` tables forces a
polymorphic reference or a parallel join table, and creates a seam where the same concept must
be kept in sync in two places. That seam is what produces the `#N/A` rows in the current
workbooks.

So: **one `foods` table with a `kind` discriminator.** `kind='item'` means purchased;
`kind='recipe'` means composed from other foods. Components point at foods, so recipes nest
for free. "Sauce" is a `role`, not a table. The freezer bank is a query, not a table.

Cost, accepted: recipe macros require walking the component tree, needing cycle detection and
a cached per-100g value invalidated on edit. Contained, and realistic depth is 2–3.

### Tables

```sql
people                 id, name

tags                   id, name, kind('allergen'|'ingredient_class'|'diet'|'attribute')
food_tags              food_id, tag_id

protocols              id, name, owner_person_id NULL, description
                       -- NULL owner = built-in, shareable ('candida', 'low-FODMAP',
                       --   'gut-health', 'PCOS'). Owned = personal sensitivities.
                       --   One mechanism, both cases.
protocol_rules         protocol_id, rule('exclude'|'limit'|'prefer'),
                       target('tag'|'food'), target_id, limit_g_per_day NULL,
                       hard_exclude, note
                       -- hard_exclude=true suppresses the candidate entirely.
                       --   Default false: violations surface with a reason attached.
person_protocols       person_id, protocol_id, active, started_on, ended_on
                       -- dated, so a finished 8-week protocol is history
                       --   and old plans stay interpretable

macro_profiles         id, person_id, name('training'|'rest'), effective_on,
                       kcal, fat_pct, carb_pct, protein_pct,
                       kcal_tol_pct, protein_tol_g, macro_pct_tol
                       -- macro_pct_tol applies to both fat_pct and carb_pct

slot_templates         id, person_id, profile_id, slot_no, name, time_of_day,
                       portable, fixed, notes
slot_template_roles    slot_template_id, role, min_count
                       -- a join table rather than a delimited string, so
                       --   "protein anchor + veg + sauce" is queryable

foods                  id, kind('item'|'recipe'), name, brand,
                       role('protein'|'carb'|'fat'|'veg'|'sauce'|'beverage'|'supplement'),
                       kcal_100g, protein_g_100g, fat_g_100g, carb_g_100g, fiber_g_100g,
                       cooked_yield_g NULL, instructions NULL,
                       source('usda'|'off'|'label'|'manual'|'computed'), source_ref,
                       verified, verified_on, computed_at, notes

food_units             food_id, unit, grams, is_default_display
                       -- 'tbsp'|'tsp'|'cup'|'scoop'|'packet'|'patty'|'package'|'souper_cube'
                       -- keyed to the specific food: a scoop of Karbolyn is not
                       --   a scoop of cyclic dextrin

food_components        parent_food_id, child_food_id, qty, unit,
                       flex, flex_min_g, flex_max_g, note

day_plans              id, person_id, profile_id, name, status('active'|'archived'),
                       parent_plan_id NULL, created_at, notes
                       -- parent_plan_id gives variants lineage.
                       -- The rotation is simply status='active'. No rotations table:
                       --   three or four plans do not need a container.

day_plan_entries       id, day_plan_id, slot_no, food_id, qty, unit,
                       flex, flex_min_g, flex_max_g, sort_order

inventory              id, person_id, food_id, location('pantry'|'fridge'|'freezer'),
                       qty_g NULL, portions NULL, status('have'|'low'|'out'),
                       updated_at, note
                       -- two-tier: exact quantities for macro-driving items,
                       --   status flags for staples (oil, vinegar, spices)
```

### Design properties

**Everything normalizes to macros per 100 g.** Servings, scoops, tablespoons, and patties are
conversions layered on top via `food_units`. Exactly one canonical number per food; every
display unit derives from it. This is the primary defense against the `#N/A` failure class.

**Recipe tags are computed, not stored.** A recipe's tags are the union of its components',
derived on read. Only purchased items are ever tagged by hand, so tagging burden stays
proportional to items bought rather than dishes invented. USDA and Open Food Facts return
ingredient lists for branded products, which can *suggest* tags at import.

**Exclusions propagate through the component tree.** Garlic inside chimichurri inside
steak-with-chimichurri flags the dish. This falls out of the nested model and is the most
likely place a sensitivity system would otherwise silently fail.

**Violations are reported, not enforced.** Candidates that break a protocol are surfaced with
the reason attached, not silently dropped — a filter that hides things without explaining
itself fights the improvisation goal. `protocol_rules.hard_exclude` opts a specific rule into
true suppression, for things that should never surface at all.

**The person dimension is present throughout but invisible in use.** Jen is person 1.
Retrofitting a person dimension through plans, inventory, templates, and profiles later is a
painful migration; carrying it now costs almost nothing.

---

## 5. Engine

Five operations. The first is the foundation; the rest wrap it.

### `evaluate(day_plan) -> DayEvaluation`

Pure, no mutation. Returns per-slot and whole-day totals, deltas against the profile target,
tolerance pass/fail per macro, and protocol violations with reasons. Purity is what makes the
system testable: given a plan, the numbers are the numbers.

### `resolve_flex(day_plan) -> DayPlan`

Replaces hand-tuning. Each flex ingredient contributes linearly per gram across all four
macros within a min/max bound — a **bounded least-squares problem**, solved by
`scipy.optimize.lsq_linear` in one deterministic call. For the 3–6 flex items a day actually
has, this is less code than a hand-rolled greedy loop and strictly better at satisfying four
simultaneous targets over coupled variables.

Solver weights encode the tolerance decision: heavy on kcal and protein, light on fat and carb.
The solver sits behind one function, so replacing it later is a contained change.

**Then it snaps to kitchen-realistic increments** from `food_units` — 0.25 tbsp for oils, 5 g
for proteins — and re-evaluates *after* snapping, so reported numbers match what will actually
be eaten. The existing plans specify 0.33 tbsp olive oil and 1.66 tbsp mayo; nobody measures
that. Marginally worse on paper, meaningfully better in the kitchen.

**On infeasibility, report and diagnose** — closest achievable plus the reason, e.g. *"protein
is 12 g short; no flex item in this day carries meaningful protein — consider unfixing the
chicken portion."* Never fail silently, never fail uninformatively.

### `substitute(plan, slot, old_food, new_food) -> (DayPlan, Diff)`

Derives a variant (`parent_plan_id` set), applies the swap, re-solves flex, evaluates.
Never mutates the parent, so Keto A survives experimentation.

### `fit(new_food, person) -> list[FitResult]`

The improvisation valve, and the headline feature. For each active plan and each slot whose
`required_roles` match the food's role, try the substitution, re-solve, rank by resulting
deviation. Answers *"I found this at Sprouts — where does it go, and how much?"*

Ranking incorporates inventory as a preference: freezer portions rank highest, being already
portioned and already macro-known.

### `gap_list(plans, inventory) -> list[GapItem]`

Plan requirements minus what inventory says is on hand. Freezer portions draw first.

**Inventory is a ranking signal, never a filter.** It orders candidates. It never removes an
option, because the goal is adaptability rather than obedience.

---

## 6. Adding foods

Four paths, one resulting row shape.

| Path | Source | Notes |
|---|---|---|
| USDA FDC by name | `source='usda'` | Foundation and SR Legacy for whole foods; already per-100g. Nutrient IDs map: 1008 kcal, 1003 protein, 1004 fat, 1005 carb, 1079 fiber. |
| Open Food Facts by barcode | `source='off'` | Branded items USDA misses. Community-contributed, so lands `verified=false` until checked against the label. |
| Manual from label | `source='label'` | Supplements — Karbolyn, Liquid IV, cyclic dextrin — plus their scoop and packet gram conversions. |
| Compose a recipe | `source='computed'` | Component foods plus a cooked yield weight yields per-100g. |
| Cronometer recipe CSV | `source='cronometer'` | One row per recipe, ~100 nutrient columns, **no ingredient breakdown**. Imports as `kind='item'`, not `kind='recipe'`. |

**Resolved: the real export is a flattened CSV, not structured JSON.** Two genuine samples
now sit in `examples/`. They contain a single aggregate row per recipe — the finished dish's
nutrients — with no components. So this path *cannot* populate `food_components`, and the
earlier assumption that it carries ingredient structure was wrong.

It remains worth building, because the `Amount` column carries both the serving label and its
gram weight in one string (`"servings  — 169g"`, `"pita quarter  — 54g"`). That yields the
per-100 g normalization *and* a `food_units` row in one parse. A finished dish with known
macros and a known portion weight is behaviorally identical to a purchased item, which is why
these land as items.

Two hard requirements on the parser:

- **Map columns by header name, never by position.** The macro columns are scattered among
  roughly a hundred nutrient columns. Positional parsing produces plausible-looking garbage —
  reading `Fat (g)` off the wrong offset yields 43.09 g where the true value is 7.59 g.
- **Derive per-100 g from the `Amount` gram weight**, never from an assumed serving size.

Recipes whose *composition* matters — where changing an ingredient should change the macros —
are still built through the compose path. The CSV import is for dishes treated as fixed units.

Cronometer's **cooked-recipe-weight** concept remains worth adopting regardless: raw ingredient
macros divided by cooked yield weight is exactly the `cooked_yield_g` mechanism above, and it
is what makes souper-cube portions accurate rather than estimated.

Every food carries `source`, `source_ref`, and `verified`, so provenance is auditable and
guessed values are distinguishable from label-confirmed ones.

**Raw API responses cache to disk**, keyed by request. Imports stay reproducible and a network
blip never blocks work.

### Ingredient capture is a session activity, not a code path

Ingredient lists and macros have different reliability requirements, and conflating them
leads to the wrong build.

**Macros must be trustworthy**, which is why they are always computed from the item table
and never taken from a recipe's own claims. **Ingredient lists do not** — they are names and
quantities, cheap to verify by eye, and every gram gets priced against foods already curated.

So an ingredient list may come from anywhere: a screenshot, a food blog, a Cronometer
explode-recipe export, handwriting. Converting one into a recipe is the same operation
regardless of source — match each line to a food in the library, resolve units, call
`create_recipe`. That matching is judgment work and happens in session, against the library's
callable surface. **No scraper, no parser, no importer is built for this.** Revisit only if
it becomes repetitive enough to be worth automating.

This does not contradict the rejection of a scraped recipe library. That rejection stands:
planning is not driven by a corpus of web recipes, and web-sourced *macros* are never used.

**Consequence worth tracking.** A dish imported as an opaque item — the Cronometer CSV path —
contributes macros to a plan but cannot be flex-adjusted, cannot appear in the gap list, and
cannot draw from inventory, because nothing knows what it consumes. Batch-prep dishes whose
ingredients get shopped for should be composed with real components. Dishes eaten as a fixed
unit are fine left opaque.

### Seeding

Priority is a robust schema, not a large import. In order:

1. A curated starter set from USDA FDC — roughly 60–80 canonical whole foods covering the
   protein anchors, vegetables, fats, and carbs actually in the rotation.
2. Selective, opportunistic entries from the existing xlsx workbooks. Not a bulk import.
3. Cronometer recipe CSVs, imported as items. One export per recipe; there is no bulk export.

---

## 7. Output

Excel becomes **output-only**, generated via `openpyxl`, matching the coach's layout: client
profile header, per-slot rows, macro check row. Generated, never hand-edited.

This is the core structural fix. The current workbooks are simultaneously the store *and* the
interface, which is why lookup keys drift and `#N/A` rows appear. Separating them removes the
failure mode while preserving the deliverable format.

---

## 8. Error handling

Every case below is one where a quiet default would produce a plausible wrong number — worse
than a stack trace.

| Condition | Behavior |
|---|---|
| Missing unit conversion | Raise, naming the food and the unit. Never guess a default. |
| Recipe without `cooked_yield_g` | Refuse to compute per-100g. Never estimate. |
| Cycle in `food_components` | Detected and rejected at insert. |
| Untagged food | Surfaced by a standing check, so tagging debt is visible rather than silently wrong. |
| Solver infeasible | Closest achievable plus a diagnosis of which target is unreachable and why. |
| Protocol violation | Reported with the rule and the offending component, including nested ones. |
| API failure | Fall back to cache; if absent, raise. Never insert a partial food row. |

---

## 9. Testing

Test-driven throughout.

**Golden file — highest value.** Take a coach-authored plan from `examples/`, enter its
ingredients, and confirm the engine reproduces the PDF's own stated macro totals within
tolerance. Keto Meal Plan A is the first target; the Emergency plans exercise the rest-day
profile.

**What it proves, precisely.** Aggregation across slots, per-food unit lookup (the Keto A
fixture has `packet` meaning 22 g for one food and 16 g for another, and `scoop` meaning 32 g,
50 g, and 34 g for three), the per-100 g scale convention, and completeness of the transcribed
plan.

**What it cannot prove.** That any individual gram-per-unit weight is factually correct. The
fixture's `macros_100g` is derived by dividing the PDF's per-serving figures *by that same
weight*, which the engine then multiplies back — so a self-consistent error cancels exactly.
This was verified by mutation: changing a packet weight from 22 g to 40 g while rescaling
`macros_100g` to match left the computed totals bit-for-bit identical. Changing it *without*
rescaling moved totals 3% and failed the test, which is where the test has teeth.

Gram-weight accuracy comes from provenance, not from this test: every entry's `source_note`
cites a product label or a USDA `fdcId`, and `verified` marks whether a human checked it.

**Property tests.**
- `resolve_flex` never returns a quantity outside `[flex_min_g, flex_max_g]`.
- Snapping never pushes a value out of range.
- `evaluate` is deterministic and free of side effects.
- Unit conversions round-trip.

**Fixture requirement.** `examples/` holds the real artifacts the importers and golden-file
tests run against: six coach-authored plan PDFs and two genuine Cronometer recipe CSVs.
Import tests run against those real files, not hand-written approximations of them.

**Unit tests.**
- Cycle detection rejects self-referential and mutually-referential recipes.
- Cronometer import round-trips a real sample: ingredients, quantities, units, and cooked
  yield weight all land in the expected `foods` and `food_components` rows.
- A tag two levels deep in a nested recipe trips a protocol violation.
- Dated profile rows resolve to the correct profile for a given date.
- `substitute` leaves the parent plan byte-identical.

---

## 10. Sequencing

Do not build the whole system before proving it.

1. Schema, migrations, and `models.py`.
2. `units.py` and `macros.py` with round-trip tests.
3. `foods.py` — CRUD, composition, derived tags, cycle detection.
4. USDA source plus cache; seed the curated starter set.
5. `evaluate()` and the golden-file test against Keto Plan A. **This is the checkpoint** —
   if the engine can reproduce a known plan, the foundation is sound.
6. `resolve_flex()` with snapping.
7. `substitute()` and `fit()`.
8. Protocols and violation reporting.
9. Inventory and `gap_list()`.
10. Excel export.

Then run two or three real weeks through it by hand. The item table, tag vocabulary, and
freezer bank accumulate as a byproduct of work already being done, and what deserves
automation becomes obvious rather than speculative.

---

## 11. Resolved and remaining questions

### Resolved in this session

| Question | Resolution |
|---|---|
| Operating model | Claude front door, tested library underneath |
| Macro tolerance | Hard on kcal and protein, ±3-point band on fat and carb |
| Solver approach | Bounded least-squares (`lsq_linear`), snapped to kitchen units |
| Multi-person | Person dimension throughout; used for one |
| Profiles fixed or recalculated | Data, with `effective_on` dates |
| Items / recipes / sauces modeling | One `foods` table with `kind` discriminator |
| Seeding | Curated USDA starter set; selective workbook and Cronometer entries |
| Body composition figures | Confirmed transposed; LBM 148.5 lb, fat mass 49.5 lb |
| Cronometer as data layer | Rejected. May remain a logging surface. |
| Store | SQLite, portable SQL, Postgres door left open |

### Remaining, none blocking

1. ~~**Is ±1.5% on all four macros a coach requirement or an artifact of hand-tuning?**~~
   **Resolved by measurement** — see §2. Keto Plan A misses protein by 6.8 g (3.33%), so
   ±1.5% on all four was never achieved. Protein tolerance set to ±8 g. Worth confirming with
   the coach whether that 6.8 g is intentional slack, but it no longer blocks anything.
2. **Which store receipts are digitally accessible, and in what format?** Deferred with the
   whole capture pipeline.
3. **Does the freezer bank have a known current state, or start empty?** Assume empty and
   accumulate unless told otherwise.
4. **How many Cronometer recipes are worth exporting?** The format question is resolved
   (see §6) — what remains is volume, which decides whether the CSV path is worth running in
   bulk or whether a handful of hand-composed recipes covers it.
