# Bringing in a haul from a receipt

How a grocery receipt (an Instacart order, a Costco run) becomes foods in the library,
each with its points, without typing labels one at a time.

This is a **runbook for a Claude Code session, not a code path.** Reading a receipt and
finding each product's label is judgment work: matching "KS ORG LENTIL 8PK" to a real
product, choosing between two recipes sold under one name, deciding which figures to trust.
The app does the last step only: it imports a CSV of label figures as unchecked foods.

---

## The spine

1. **Hand the receipt to Claude** in a session in this repo: a screenshot, a PDF, or the
   pasted order. Ask for the new foods as an inbox CSV.
2. **Claude finds each product's label.** It prefers, in this order: a photo of the label
   you took, the maker's own site, the retailer's listing, then USDA FoodData Central for
   unbranded foods (produce, plain meat). Every row's `source_note` says where its numbers
   came from and anything assumed ("fiber not listed", "pancake weight assumed 30 g").
3. **Claude writes the CSV** with the columns of
   [`food-inbox-template.csv`](food-inbox-template.csv), one row per food, figures **per
   serving as printed**.
4. **Import it:**

   ```bash
   uv run python -m yolk import-foods inbox.csv
   ```

   Every row is checked first. If any row is wrong, nothing is imported and each problem is
   named by line and column (`line 4, fat_g: ...`). Fix the file and run it again. A food
   already in the library (same name and brand) is skipped and named, so running a file
   twice is safe.
5. **Check each food against its package** on its page in the app (**Foods**, then the
   food's name). Fix anything that differs with **Edit**, then **Mark checked**. Until then
   it carries the "unchecked" badge.

---

## The columns

| Column | What goes in it |
|---|---|
| `name`, `brand` | As on the package. Together they must be unique in the library. |
| `store` | Where it was bought. Kept in the food's notes. |
| `serving_text` | The serving as the label words it, e.g. `1/3 cup (30 g)`. Kept in the notes. |
| `serving_g` | The serving in grams. Required. |
| `kcal`, `fat_g`, `carb_g`, `protein_g` | Per serving. Required; write `0` for zero. |
| `fiber_g`, `sugar_alcohol_g` | Per serving. **Leave blank when the label does not say**, never `0`. Blank fiber means "unknown", and under net carbs the food then counts its total carbs. |
| `point_class` | What it counts as: `fat`, `carb`, `protein`, `veggie`, or blank/`auto` for its biggest macro. A free food is `free:veg`, `free:sauce` or `free:beverage`. |
| `unit`, `unit_g` | A household unit and its grams, e.g. `pancake` and `30`. The serving is then that many units. Leave both blank to use `serving`. |
| `source_note` | Where the numbers came from, and anything assumed. Kept in the notes. |

Plain numbers only: `12`, not `12g` or `12 g`, and a point for decimals (`1.5`, not `1,5`).
A file saved from Excel is fine.

---

## Why a CSV and not the app

Reading a receipt well needs a model and a web search, and the app deliberately makes no
calls to Claude, to keep it free to run and simple to trust. The CSV is the hand-off: the
session does the judgment, the app does the bookkeeping, and you check what came in
against the packages in your kitchen.
