"""Golden check: the coach's Sample Option 1, rebuilt from the library's foods.

The points-world counterpart of the Keto Plan A golden test. Each sample meal
should land on its meal's allotment within the ±¼-point hint. The coach's
samples are rough ("~1 cup potatoes"), so some meals miss honestly; those are
recorded in the fixture's expected_misses with their computed points, and
this test pins them too, so a data change that fixes or worsens one shows.
"""

import json

import pytest

from yolk.points import POINT_TYPES, Points, food_points, load_rules
from yolk.seed import POINT_FIXTURE_PATH, seed_keto_plan_a, seed_point_system
from yolk.units import to_grams

FIXTURE = json.loads(POINT_FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def library(db):
    seed_keto_plan_a(db)
    seed_point_system(db)
    return db


def _meal_points(db, entries):
    rules = load_rules(db)
    total = Points.zero()
    for entry in entries:
        food_id = db.execute(
            "SELECT id FROM foods WHERE name = ?", (entry["food"],)
        ).fetchone()["id"]
        grams = to_grams(db, food_id, entry["qty"], entry["unit"])
        total = total + food_points(db, food_id, grams, rules)
    return total


def test_sample_option_1_meals_land_on_their_allotments(library):
    slots = {s["slot_no"]: s for s in FIXTURE["slots"]}
    misses = {
        m["slot_no"]: m["points"]
        for m in FIXTURE["expected_misses"]
        if m["sample"] == "Sample Option 1"
    }
    for meal in FIXTURE["samples"]["Sample Option 1"]:
        planned = _meal_points(library, meal["entries"])
        slot_no = meal["slot_no"]
        for name in POINT_TYPES:
            actual = getattr(planned, name)
            if slot_no in misses:
                assert actual == pytest.approx(misses[slot_no][name], abs=0.01), (slot_no, name)
            else:
                assert abs(actual - slots[slot_no][name]) <= 0.25, (slot_no, name)
