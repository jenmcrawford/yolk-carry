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