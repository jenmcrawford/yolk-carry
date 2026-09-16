import pytest

from yolk.people import (
    active_profile, create_person, create_profile, create_slot, targets_for_profile,
)


def test_profile_targets_derive_grams(db):
    pid = create_person(db, "Jen")
    profile_id = create_profile(
        db, pid, name="training", effective_on="2026-07-14",
        kcal=2150, fat_pct=34, carb_pct=28, protein_pct=38,
    )
    t = targets_for_profile(db, profile_id)
    assert t.kcal == 2150
    assert t.protein_g == pytest.approx(204.25, abs=0.01)


def test_active_profile_picks_latest_on_or_before_date(db):
    pid = create_person(db, "Jen")
    create_profile(
        db, pid, name="training", effective_on="2026-01-01",
        kcal=2000, fat_pct=34, carb_pct=28, protein_pct=38,
    )
    create_profile(
        db, pid, name="training", effective_on="2026-07-14",
        kcal=2150, fat_pct=34, carb_pct=28, protein_pct=38,
    )
    row = active_profile(db, pid, "training", "2026-08-09")
    assert row["kcal"] == 2150


def test_active_profile_ignores_future_rows(db):
    pid = create_person(db, "Jen")
    create_profile(
        db, pid, name="training", effective_on="2026-01-01",
        kcal=2000, fat_pct=34, carb_pct=28, protein_pct=38,
    )
    create_profile(
        db, pid, name="training", effective_on="2026-12-01",
        kcal=2300, fat_pct=34, carb_pct=28, protein_pct=38,
    )
    row = active_profile(db, pid, "training", "2026-08-09")
    assert row["kcal"] == 2000


def test_active_profile_missing_raises(db):
    pid = create_person(db, "Jen")
    with pytest.raises(LookupError):
        active_profile(db, pid, "training", "2026-08-09")


def test_tolerances_default_to_spec_values(db):
    """create_profile always passes all three tolerances explicitly, so
    calling it here would read back Python's defaults, not schema.sql's.
    Insert the row via raw SQL, omitting the tolerance columns, so the
    values under test are the ones the schema itself supplies."""
    pid = create_person(db, "Jen")
    row = db.execute(
        "INSERT INTO macro_profiles (person_id, name, effective_on, kcal, "
        "fat_pct, carb_pct, protein_pct) VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING id",
        (pid, "rest", "2026-07-14", 2115, 39, 18, 43),
    ).fetchone()
    db.commit()
    profile_id = row["id"]
    row = db.execute(
        "SELECT kcal_tol_pct, protein_tol_g, macro_pct_tol FROM macro_profiles "
        "WHERE id = ?", (profile_id,)
    ).fetchone()
    assert row["kcal_tol_pct"] == 1.0
    assert row["protein_tol_g"] == 8.0
    assert row["macro_pct_tol"] == 3.0


def test_failed_role_insert_leaves_no_orphan_slot(db):
    """A duplicate role violates slot_template_roles' UNIQUE (slot_template_id,
    role) constraint. That failure must roll back the slot_templates row too,
    not leave a slot claiming fewer roles than requested."""
    import sqlite3

    pid = create_person(db, "Jen")
    profile_id = create_profile(
        db, pid, name="training", effective_on="2026-07-14",
        kcal=2150, fat_pct=34, carb_pct=28, protein_pct=38,
    )
    with pytest.raises(sqlite3.IntegrityError):
        create_slot(
            db, pid, profile_id, slot_no=6, name="Dinner", time_of_day="18:00",
            roles=("protein", "protein"),
        )
    count = db.execute(
        "SELECT COUNT(*) AS n FROM slot_templates WHERE name = 'Dinner'"
    ).fetchone()["n"]
    assert count == 0


def test_slot_with_roles(db):
    pid = create_person(db, "Jen")
    profile_id = create_profile(
        db, pid, name="training", effective_on="2026-07-14",
        kcal=2150, fat_pct=34, carb_pct=28, protein_pct=38,
    )
    slot_id = create_slot(
        db, pid, profile_id, slot_no=6, name="Dinner", time_of_day="18:00",
        roles=("protein", "veg", "sauce"),
    )
    rows = db.execute(
        "SELECT role FROM slot_template_roles WHERE slot_template_id = ? ORDER BY role",
        (slot_id,),
    ).fetchall()
    assert [r["role"] for r in rows] == ["protein", "sauce", "veg"]
