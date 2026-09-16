"""Golden-file test: reproduce a coach-authored plan from its own ingredients.

This validates aggregation across slots, per-food unit lookup (the fixture reuses
unit names like "packet" and "scoop" with different gram weights per food), the
per-100 g scale convention, and completeness of the transcribed plan — all against
a real coach-authored plan's own stated totals.

It does NOT validate that any individual gram-per-unit weight is factually correct.
Each fixture entry's `macros_100g` was derived as `PDF_per_serving / grams * 100`
using that same `units` weight, so a uniformly wrong weight is a divide-then-multiply
identity and cancels out invisibly — only an *inconsistent* error (grams changed on
one side but not the other) moves the totals enough to fail. The factual accuracy of
each gram weight is instead asserted by that entry's `source_note` in the fixture,
citing a product label or a USDA `fdcId`.
"""

import pytest

from yolk.planning.evaluate import evaluate
from yolk.seed import seed_keto_plan_a


@pytest.fixture
def keto_a(db):
    """Build the plan described by the fixture and return its id."""
    return seed_keto_plan_a(db)


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
