# YOLK CARRY

<img src="logo.svg" width="320">

Eat yolks to carry yokes!

## Setup

Requires Python 3.14 and [uv](https://docs.astral.sh/uv/).

```bash
python -m venv .venv
uv sync --extra dev
cp .env.example .env   # then add your USDA key
uv run python -m yolk init --seed
```

Create the virtual environment with `python -m venv`, not with uv. Windows
Smart App Control blocks the small launcher executables a tool generates
inside `Scripts/`, and uv's environments use one; a stdlib environment copies
the real interpreter instead. For the same reason, run everything as a module:
`uv run python -m pytest`, not `uv run pytest`.

`yolk init` creates the database and applies every migration. `--seed` loads
Keto Plan A so there is something real to look at. Get a free USDA key at
https://api.data.gov/signup.

The database file itself is not committed. `uv run python -m yolk export` writes every
table to `data/` as JSON, the durable text copy meant to be handed to another person
later. Committing it is a separate, deliberate decision that has not been made yet, so
`data/` is git-ignored for now. `uv run python -m yolk import` loads an export back
into an empty database.

| Command | Does |
|---|---|
| `uv run python -m yolk init [--seed]` | Create the database, apply migrations, optionally seed |
| `uv run python -m yolk migrate` | Apply pending migrations |
| `uv run python -m yolk seed points` | Add the coach's point system (Active recovery day and food lists) to an existing database |
| `uv run python -m yolk export [--out DIR]` | Write every table to JSON |
| `uv run python -m yolk import [--from DIR]` | Load JSON into an empty database |
| `uv run python -m yolk serve [--port N]` | Run the web app at http://127.0.0.1:8000 |

Set `YOLK_DB` to use a database somewhere other than `yolk.db` in the repo root.

## Looking at a plan

```bash
uv run python -m yolk serve
```

Open http://127.0.0.1:8000. The plan list shows each plan and whether the day lands
within the profile's tolerances. A plan page shows the day totals against the target,
then every slot with its foods. The app only listens on this machine and has no login.
If the database is missing or needs a migration, the page says which command to run;
the app never creates or migrates the database itself.

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

## Planning on points

Your coach's point system turns grams into points: one FAT is 15 g of fat, one CARB
25 g of carbs, one PROTEIN 25 g of protein, and one VEGGIE 10 g of carbs from a
vegetable. Free foods count nothing. Points are never typed in; they are worked out
from each food's macros every time, so a corrected label shows up everywhere.

`uv run python -m yolk seed points` adds the **Active recovery** profile, its six
meals and their allotments (7:00 is 1F 1C 1P, and so on), and the coach's food lists.
`init --seed` on a new database does this too.

- **Foods** shows how much of each food is one point ("4 oz (113 g) → 1P + ¼F") and the
  coach's portion beside it. Where the macros disagree with the coach, the line is
  flagged ("coach says 1F, macros say ½F"); the coach's portion is never changed.
  Adding a food to a meal uses the coach's portion.
- Each meal shows its target, what is planned, and a hint such as "½C short" when a
  point type is off by more than a quarter. Hints never fail the day.
- The day is judged by macros, as before, against targets the points add up to:
  90 g fat, 85 g carbs, 150 g protein, 1,750 kcal. On a points day, calories are
  counted from grams (9/4/4), with a ±5% window; label calories are shown beside them.
- **Settings** switches carbs between total (the default, as the coach's portions
  are written) and net (minus fiber and sugar alcohols).

After updating to this version, run `uv run python -m yolk migrate` once (migration 3),
then `uv run python -m yolk seed points`.
