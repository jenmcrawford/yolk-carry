"""Golden-file test: reproduce a coach-authored plan from its own ingredients.

This validates the whole chain — unit conversion, per-100 g normalization, and
aggregation — against known-good hand-authored output.
"""

import json
from pathlib import Path

import pytest

from yolk.foods import create_item
from yolk.macros import Macros
from yolk.people import create_person, create_profile
from yolk.planning.evaluate import add_entry, create_day_plan, evaluate

FIXTURE = Path(__file__).parent / "fixtures" / "keto_plan_a.json"


@pytest.fixture
def keto_a(db):
    """Build the plan described by the fixture and return its id."""
    spec = json.loads(FIXTURE.read_text(encoding="utf-8"))

    person_id = create_person(db, "Jen")
    profile_id = create_profile(
        db, person_id,
        name=spec["profile"]["name"],
        effective_on=spec["profile"]["effective_on"],
        kcal=spec["profile"]["kcal"],
        fat_pct=spec["profile"]["fat_pct"],
        carb_pct=spec["profile"]["carb_pct"],
        protein_pct=spec["profile"]["protein_pct"],
    )
    plan_id = create_day_plan(db, person_id, profile_id, name=spec["plan_name"])

    food_ids: dict[str, int] = {}
    for slot in spec["slots"]:
        for entry in slot["entries"]:
            name = entry["food"]
            if name not in food_ids:
                m = entry["macros_100g"]
                food_ids[name] = create_item(
                    db,
                    name=name,
                    role=entry["role"],
                    macros=Macros(
                        kcal=m["kcal"],
                        protein_g=m["protein_g"],
                        fat_g=m["fat_g"],
                        carb_g=m["carb_g"],
                    ),
                    source=entry.get("source", "manual"),
                    units=entry.get("units") or None,
                )
            add_entry(
                db, plan_id,
                slot_no=slot["slot_no"],
                food_id=food_ids[name],
                qty=entry["qty"],
                unit=entry["unit"],
            )
    return plan_id, spec


def test_golden_plan_reproduces_reported_calories(db, keto_a):
    plan_id, spec = keto_a
    result = evaluate(db, plan_id)
    reported = spec["reported_totals"]["kcal"]
    # 1% of the day's calories, matching the profile's kcal tolerance
    assert result.totals.kcal == pytest.approx(reported, rel=0.01)


def test_golden_plan_reproduces_reported_protein(db, keto_a):
    plan_id, spec = keto_a
    result = evaluate(db, plan_id)
    assert result.totals.protein_g == pytest.approx(
        spec["reported_totals"]["protein_g"], abs=2.0
    )


def test_golden_plan_reproduces_reported_fat_and_carb(db, keto_a):
    plan_id, spec = keto_a
    result = evaluate(db, plan_id)
    assert result.totals.fat_g == pytest.approx(
        spec["reported_totals"]["fat_g"], rel=0.03
    )
    assert result.totals.carb_g == pytest.approx(
        spec["reported_totals"]["carb_g"], rel=0.03
    )


def test_golden_plan_has_every_slot_from_the_source(db, keto_a):
    plan_id, spec = keto_a
    result = evaluate(db, plan_id)
    assert [s.slot_no for s in result.slots] == [s["slot_no"] for s in spec["slots"]]


def test_golden_plan_lands_within_profile_tolerance(db, keto_a):
    """The coach's own plan should pass the tolerances we chose."""
    plan_id, _ = keto_a
    result = evaluate(db, plan_id)
    assert result.ok, (
        f"Coach-authored plan failed our tolerances: {result.within_tolerance}. "
        f"Totals {result.totals}, target {result.target}."
    )
