import json

import pytest

from yolk.errors import YolkError
from yolk.points import portions
from yolk.seed import POINT_FIXTURE_PATH, seed_keto_plan_a, seed_point_system
from yolk.units import to_grams

FIXTURE = json.loads(POINT_FIXTURE_PATH.read_text(encoding="utf-8"))


def _food_id(db, name, brand=""):
    return db.execute(
        "SELECT id FROM foods WHERE name = ? AND brand = ?", (name, brand)
    ).fetchone()["id"]


def _counts(db):
    return {
        table: db.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]
        for table in ("foods", "point_portions", "slot_templates", "macro_profiles")
    }


@pytest.fixture
def keto_db(db):
    seed_keto_plan_a(db)
    return db


def test_fixture_is_self_consistent(keto_db):
    report = seed_point_system(keto_db)

    for food in FIXTURE["foods"]:
        food_id = _food_id(keto_db, food["name"], food["brand"])
        assert len(portions(keto_db, food_id)) == len(food["portions"]), food["name"]
    for meal in FIXTURE["samples"]["Sample Option 1"]:
        for entry in meal["entries"]:
            food_id = keto_db.execute(
                "SELECT id FROM foods WHERE name = ?", (entry["food"],)
            ).fetchone()["id"]
            to_grams(keto_db, food_id, entry["qty"], entry["unit"])

    flagged = {f["name"] for f in FIXTURE["foods"] if f["source_note"].startswith("FLAG")}
    assert set(report.flagged) == flagged
    assert flagged, "the coach's lists have known disagreements; none found means a bug"


def test_seed_creates_the_active_recovery_day(keto_db):
    report = seed_point_system(keto_db)
    row = keto_db.execute(
        "SELECT name, basis, kcal_tol_pct FROM macro_profiles WHERE id = ?",
        (report.profile_id,),
    ).fetchone()
    assert tuple(row) == ("Active recovery", "points", 5.0)
    slots = keto_db.execute(
        "SELECT slot_no, name, fat_pts, carb_pts, protein_pts, veggie_pts "
        "FROM slot_templates WHERE profile_id = ? ORDER BY slot_no",
        (report.profile_id,),
    ).fetchall()
    assert [tuple(s) for s in slots] == [
        (1, "7:00", 1, 1, 1, 0), (2, "10:00", 1, 0, 1, 0), (3, "12:30", 1, 1, 1, 0),
        (4, "3:00", 1, 0, 1, 0), (5, "5:30", 1, 0, 1, 0), (6, "8:30", 1, 1, 1, 1),
    ]


def test_seed_attaches_to_existing_foods(keto_db):
    before = keto_db.execute(
        "SELECT * FROM foods WHERE name = 'Peanut butter'"
    ).fetchone()
    count = keto_db.execute(
        "SELECT count(*) AS n FROM foods WHERE name = 'Peanut butter'"
    ).fetchone()["n"]

    report = seed_point_system(keto_db)

    assert "Peanut butter" in report.attached
    assert "Peanut butter" not in report.created
    after = keto_db.execute("SELECT * FROM foods WHERE name = 'Peanut butter'").fetchone()
    assert keto_db.execute(
        "SELECT count(*) AS n FROM foods WHERE name = 'Peanut butter'"
    ).fetchone()["n"] == count
    for column in ("kcal_100g", "fat_g_100g", "carb_g_100g", "protein_g_100g"):
        assert after[column] == before[column]
    assert after["point_class"] == "fat"
    assert [p.source for p in portions(keto_db, after["id"])] == ["coach"]


def test_seed_keeps_unknown_fiber_unknown(keto_db):
    seed_point_system(keto_db)
    row = keto_db.execute(
        "SELECT fiber_g_100g, sugar_alcohol_g_100g FROM foods WHERE name = 'Quest Bar'"
    ).fetchone()
    assert row["sugar_alcohol_g_100g"] == pytest.approx(5 * 100 / 60, abs=0.001)
    zuppa = keto_db.execute(
        "SELECT fiber_g_100g FROM foods WHERE name = 'Rustic Zuppa Toscana'"
    ).fetchone()
    assert zuppa["fiber_g_100g"] is None


def test_seed_marks_claude_foods_unverified(keto_db):
    seed_point_system(keto_db)
    verified = {
        row["name"]: row["verified"]
        for row in keto_db.execute("SELECT name, verified FROM foods")
    }
    assert verified["Chicken breast, raw"] == 1
    assert verified["Grassfed Beef Stroganoff"] == 0
    assert verified["Bitchin' Sauce"] == 0


def test_seed_twice_is_a_no_op(keto_db):
    seed_point_system(keto_db)
    counts = _counts(keto_db)
    again = seed_point_system(keto_db)
    assert again.already_seeded is True
    assert _counts(keto_db) == counts


def test_seed_requires_jen(db):
    with pytest.raises(YolkError, match="Jen"):
        seed_point_system(db)
    assert db.execute("SELECT count(*) AS n FROM foods").fetchone()["n"] == 0
