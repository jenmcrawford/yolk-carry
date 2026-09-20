import json
import sqlite3

import pytest

from yolk.planning.evaluate import evaluate
from yolk.seed import FIXTURE_PATH, parse_time_of_day, seed_keto_plan_a


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Meal 1 - 6:30am Wake Up", "06:30"),
        ("Meal 2 - 8:30am Breakfast - Yogurt + granola", "08:30"),
        ("Meal 4 - 2:00pm Lunch - Salad", "14:00"),
        ("Meal 6 - 6:00pm Dinner - Pasta", "18:00"),
        ("Meal 7 - 12:00am Midnight", "00:00"),
        ("Meal 8 - 12:00pm Noon", "12:00"),
    ],
)
def test_time_of_day_is_parsed_from_the_slot_name(name, expected):
    assert parse_time_of_day(name) == expected


def test_a_slot_name_without_a_time_raises():
    with pytest.raises(ValueError, match="no time"):
        parse_time_of_day("Meal 9 - whenever")


def test_seed_creates_one_slot_template_per_slot(db):
    plan_id, spec = seed_keto_plan_a(db)
    rows = db.execute(
        "SELECT slot_no, name, time_of_day FROM slot_templates ORDER BY slot_no"
    ).fetchall()
    assert [r["slot_no"] for r in rows] == [s["slot_no"] for s in spec["slots"]]
    assert [r["name"] for r in rows] == [s["name"] for s in spec["slots"]]
    assert rows[0]["time_of_day"] == "06:30"


def test_seeded_foods_are_approved_with_their_source_note(db):
    seed_keto_plan_a(db)
    row = db.execute(
        "SELECT verified, verified_on, notes FROM foods WHERE name = ?",
        ("Buff Chick Coffee",),
    ).fetchone()
    assert row["verified"] == 1
    assert row["verified_on"] is not None
    assert "22 g" in row["notes"]


def test_seed_reproduces_the_reported_calories(db):
    plan_id, spec = seed_keto_plan_a(db)
    result = evaluate(db, plan_id)
    assert result.totals.kcal == pytest.approx(spec["reported_totals"]["kcal"], rel=0.01)


def test_seeding_twice_raises_rather_than_duplicating(db):
    """The second Jen violates people.name's UNIQUE constraint."""
    seed_keto_plan_a(db)
    with pytest.raises(sqlite3.IntegrityError):
        seed_keto_plan_a(db)


def test_a_failed_seed_leaves_the_database_empty(db, tmp_path):
    """The whole seed is one transaction: a fixture problem partway through
    (here, the last slot's unparseable name) must not leave the person,
    profile, plan, and foods from the slots before it behind. If it did, the
    day_plans guard in `yolk init --seed` would refuse to retry, and deleting
    the database file would be the only way out."""
    spec = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert len(spec["slots"]) > 1, "need at least one good slot before the bad one"
    spec["slots"][-1]["name"] = "Meal Whenever - no time here"
    broken = tmp_path / "broken_keto_plan_a.json"
    broken.write_text(json.dumps(spec), encoding="utf-8")

    with pytest.raises(ValueError, match="no time"):
        seed_keto_plan_a(db, fixture_path=broken)

    for table in ("people", "macro_profiles", "day_plans", "slot_templates", "foods"):
        assert db.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"] == 0
