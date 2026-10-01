"""The `yolk` command: create, migrate, export, import, and serve the database."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import uvicorn

from yolk.config import database_path
from yolk.db.connection import connect
from yolk.db.migrate import apply_migrations
from yolk.errors import YolkError
from yolk.seed import seed_keto_plan_a
from yolk.snapshot import DEFAULT_DIR, export_database, import_database
from yolk.web.app import create_app


def _require_existing_database() -> Path:
    path = database_path()
    if not path.is_file():
        raise YolkError(
            f"No database at {path}. Run `yolk init` first, or set YOLK_DB to "
            f"point at an existing one."
        )
    return path


def _cmd_init(args: argparse.Namespace) -> int:
    path = database_path()
    existed = path.is_file()
    conn = connect(path)
    try:
        applied = apply_migrations(conn)
        if not existed:
            print(f"Created {path}")
        print(
            f"Applied migrations: {', '.join(str(v) for v in applied)}"
            if applied
            else "Already up to date."
        )
        if args.seed:
            if conn.execute("SELECT count(*) AS n FROM day_plans").fetchone()["n"]:
                raise YolkError(
                    f"{path} already has plans in it, so seeding would duplicate "
                    f"them. Seed only an empty database."
                )
            plan_id, _ = seed_keto_plan_a(conn)
            print(f"Seeded Keto Plan A as plan {plan_id}.")
    finally:
        conn.close()
    return 0


def _cmd_migrate(args: argparse.Namespace) -> int:
    conn = connect(_require_existing_database())
    try:
        applied = apply_migrations(conn)
        print(
            f"Applied migrations: {', '.join(str(v) for v in applied)}"
            if applied
            else "Already up to date."
        )
    finally:
        conn.close()
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    conn = connect(_require_existing_database())
    try:
        written = export_database(conn, Path(args.out))
        print(f"Wrote {len(written)} file(s) to {args.out}")
    finally:
        conn.close()
    return 0


def _cmd_import(args: argparse.Namespace) -> int:
    conn = connect(_require_existing_database())
    try:
        counts = import_database(conn, Path(getattr(args, "from")))
        print(f"Loaded {sum(counts.values())} row(s) from {getattr(args, 'from')}")
    finally:
        conn.close()
    return 0


# The app has no authentication, so it must never listen beyond this machine.
LOCALHOST = "127.0.0.1"


def _cmd_serve(args: argparse.Namespace) -> int:
    path = database_path()
    print(f"Serving {path} at http://{LOCALHOST}:{args.port} (Ctrl+C to stop)")
    uvicorn.run(create_app(path), host=LOCALHOST, port=args.port)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="yolk", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="create the database and apply migrations")
    init.add_argument(
        "--seed", action="store_true", help="also load the Keto Plan A fixture"
    )
    init.set_defaults(func=_cmd_init)

    migrate = sub.add_parser("migrate", help="apply pending migrations")
    migrate.set_defaults(func=_cmd_migrate)

    export = sub.add_parser("export", help="write every table to JSON")
    export.add_argument("--out", default=str(DEFAULT_DIR))
    export.set_defaults(func=_cmd_export)

    load = sub.add_parser("import", help="load JSON into an empty database")
    load.add_argument("--from", dest="from", default=str(DEFAULT_DIR))
    load.set_defaults(func=_cmd_import)

    serve = sub.add_parser("serve", help="run the web app on this machine")
    serve.add_argument("--port", type=int, default=8000)
    serve.set_defaults(func=_cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return args.func(args)
    except (YolkError, sqlite3.Error, OSError, json.JSONDecodeError) as error:
        # These are ordinary, expected failure modes -- a constraint the
        # fixture violates, an export with a malformed JSON file, a database
        # path that cannot be written -- not bugs. A user should see the
        # message, not a traceback.
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
