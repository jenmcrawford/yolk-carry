import shutil
import sqlite3

import pytest

from yolk.db.connection import connect
from yolk.db.migrate import MIGRATIONS_DIR, apply_migrations
from yolk.planning.evaluate import evaluate
from yolk.seed import seed_keto_plan_a

_OLD_PROFILE_COLUMNS = (
    "id, person_id, name, effective_on, kcal, fat_pct, carb_pct, protein_pct, "
    "kcal_tol_pct, protein_tol_g, macro_pct_tol"
)


def _rows(conn, table, columns="*"):
    return [tuple(row) for row in conn.execute(f"SELECT {columns} FROM {table} ORDER BY id")]


def _at_version_2(tmp_path):
    for name in ("0001_baseline.sql", "0002_draft_status.sql"):
        shutil.copy(MIGRATIONS_DIR / name, tmp_path / name)
    conn = connect(":memory:")
    apply_migrations(conn, tmp_path)
    return conn


def test_0003_keeps_profiles_plans_and_evaluation(tmp_path):
    conn = _at_version_2(tmp_path)
    plan_id, _ = seed_keto_plan_a(conn)
    profiles = _rows(conn, "macro_profiles", _OLD_PROFILE_COLUMNS)
    slots = _rows(conn, "slot_templates")
    plans, entries = _rows(conn, "day_plans"), _rows(conn, "day_plan_entries")
    totals = evaluate(conn, plan_id).totals

    assert 3 in apply_migrations(conn)

    assert _rows(conn, "macro_profiles", _OLD_PROFILE_COLUMNS) == profiles
    assert [row[: len(slots[0])] for row in _rows(conn, "slot_templates")] == slots
    assert _rows(conn, "day_plans") == plans
    assert _rows(conn, "day_plan_entries") == entries
    assert evaluate(conn, plan_id).totals == totals
    bases = {row["basis"] for row in conn.execute("SELECT basis FROM macro_profiles")}
    assert bases == {"macros"}
    conn.close()


def test_0003_makes_veg_foods_veggie(tmp_path):
    conn = _at_version_2(tmp_path)
    for name, role in (("Broccoli", "veg"), ("Olive oil", "fat")):
        conn.execute(
            "INSERT INTO foods (kind, name, role, kcal_100g, protein_g_100g, "
            "fat_g_100g, carb_g_100g, source) VALUES ('item', ?, ?, 1, 1, 1, 1, 'manual')",
            (name, role),
        )
    conn.commit()

    apply_migrations(conn)

    classes = {
        row["name"]: row["point_class"]
        for row in conn.execute("SELECT name, point_class FROM foods")
    }
    assert classes == {"Broccoli": "veggie", "Olive oil": None}
    conn.close()


def test_0003_seeds_point_rules_and_carb_basis(db):
    rules = {
        row["point_type"]: row["grams_per_point"]
        for row in db.execute("SELECT point_type, grams_per_point FROM point_rules")
    }
    assert rules == {"fat": 15.0, "carb": 25.0, "protein": 25.0, "veggie": 10.0}
    basis = db.execute(
        "SELECT value FROM settings WHERE key = 'carb_basis'"
    ).fetchone()["value"]
    assert basis == "total"


def _profile(db, person, basis, kcal, pcts):
    db.execute(
        "INSERT INTO macro_profiles (person_id, name, effective_on, basis, kcal, "
        "fat_pct, carb_pct, protein_pct) VALUES (?, 'p', '2026-10-31', ?, ?, ?, ?, ?)",
        (person, basis, kcal, *pcts),
    )


def test_points_profile_must_not_store_kcal(db, person):
    with pytest.raises(sqlite3.IntegrityError):
        _profile(db, person, "points", 1750, (46, 19, 35))


def test_macros_profile_must_store_kcal(db, person):
    with pytest.raises(sqlite3.IntegrityError):
        _profile(db, person, "macros", None, (None, None, None))


def test_points_profile_without_kcal_is_accepted(db, person):
    _profile(db, person, "points", None, (None, None, None))


def test_one_portion_per_food_and_source(db):
    food_id = db.execute(
        "INSERT INTO foods (kind, name, role, kcal_100g, protein_g_100g, fat_g_100g, "
        "carb_g_100g, source) VALUES ('item', 'Chicken', 'protein', 1, 1, 1, 1, "
        "'manual') RETURNING id"
    ).fetchone()["id"]
    insert = (
        "INSERT INTO point_portions (food_id, source, qty, unit, claimed) "
        "VALUES (?, ?, 4, 'oz', '1P')"
    )
    db.execute(insert, (food_id, "coach"))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(insert, (food_id, "coach"))
    db.execute(insert, (food_id, "manual"))
