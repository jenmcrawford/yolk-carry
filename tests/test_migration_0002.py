import shutil
import sqlite3

import pytest

from yolk.db.connection import connect
from yolk.db.migrate import MIGRATIONS_DIR, apply_migrations
from yolk.planning.evaluate import evaluate
from yolk.seed import seed_keto_plan_a


def _rows(conn, table):
    return [tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY id")]


def _insert_draft(db, plan_id, name, parent):
    plan = db.execute(
        "SELECT person_id, profile_id FROM day_plans WHERE id = ?", (plan_id,)
    ).fetchone()
    db.execute(
        "INSERT INTO day_plans (person_id, profile_id, name, status, parent_plan_id, "
        "created_at) VALUES (?, ?, ?, 'draft', ?, '2026-10-01')",
        (plan["person_id"], plan["profile_id"], name, parent),
    )


def test_0002_keeps_every_plan_and_entry(tmp_path):
    """Build a database at version 1, fill it, then upgrade it in place."""
    shutil.copy(MIGRATIONS_DIR / "0001_baseline.sql", tmp_path / "0001_baseline.sql")
    conn = connect(":memory:")
    apply_migrations(conn, tmp_path)
    plan_id, _ = seed_keto_plan_a(conn)
    plans, entries = _rows(conn, "day_plans"), _rows(conn, "day_plan_entries")
    totals = evaluate(conn, plan_id).totals

    assert 2 in apply_migrations(conn)

    assert _rows(conn, "day_plans") == plans
    assert _rows(conn, "day_plan_entries") == entries
    assert evaluate(conn, plan_id).totals == totals
    conn.close()


def test_a_plan_may_be_a_draft(db):
    plan_id, _ = seed_keto_plan_a(db)
    _insert_draft(db, plan_id, "Draft one", plan_id)
    db.commit()
    count = db.execute(
        "SELECT count(*) AS n FROM day_plans WHERE status = 'draft'"
    ).fetchone()["n"]
    assert count == 1


def test_an_unknown_status_is_still_rejected(db):
    plan_id, _ = seed_keto_plan_a(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE day_plans SET status = 'bogus' WHERE id = ?", (plan_id,))


def test_a_saved_plan_may_have_only_one_open_draft(db):
    plan_id, _ = seed_keto_plan_a(db)
    _insert_draft(db, plan_id, "Draft one", plan_id)
    with pytest.raises(sqlite3.IntegrityError):
        _insert_draft(db, plan_id, "Draft two", plan_id)


def test_several_blank_drafts_may_coexist(db):
    plan_id, _ = seed_keto_plan_a(db)
    _insert_draft(db, plan_id, "Blank one", None)
    _insert_draft(db, plan_id, "Blank two", None)
    db.commit()
    count = db.execute(
        "SELECT count(*) AS n FROM day_plans WHERE status = 'draft'"
    ).fetchone()["n"]
    assert count == 2
