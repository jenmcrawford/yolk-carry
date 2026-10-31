"""Judging a day planned on points.

The foods here are pure macros, so a point is a round number of grams:
15 g of pure fat is one fat point, 25 g of pure protein one protein point.
Each food's label calories are deliberately 4% above 9/4/4, the way real
labels drift, to prove a points day is judged on grams, not labels.
"""

import pytest

from yolk.foods import create_item
from yolk.macros import Macros
from yolk.people import create_person, create_points_profile, create_slot
from yolk.planning.evaluate import add_entry, create_day_plan, evaluate
from yolk.planning.plans import plan_slots
from yolk.points import Points, set_carb_basis
from yolk.seed import seed_keto_plan_a

LABEL_DRIFT = 1.04

ALLOTMENTS = {
    1: Points(1, 1, 1, 0),
    2: Points(fat=1, protein=1),
    3: Points(1, 1, 1, 0),
    4: Points(fat=1, protein=1),
    5: Points(fat=1, protein=1),
    6: Points(1, 1, 1, 1),
}


@pytest.fixture
def day(db):
    person = create_person(db, "Jen")
    profile = create_points_profile(
        db, person, name="Active recovery", effective_on="2026-10-31"
    )
    for slot_no, pts in ALLOTMENTS.items():
        create_slot(
            db, person, profile, slot_no=slot_no, name=f"Meal {slot_no}",
            time_of_day="12:00", allotment=pts,
        )
    foods = {
        "fat": create_item(db, name="Fat", role="fat",
                           macros=Macros(kcal=900 * LABEL_DRIFT, fat_g=100)),
        "carb": create_item(db, name="Carb", role="carb",
                            macros=Macros(kcal=400 * LABEL_DRIFT, carb_g=100)),
        "protein": create_item(db, name="Protein", role="protein",
                               macros=Macros(kcal=400 * LABEL_DRIFT, protein_g=100)),
        "veggie": create_item(db, name="Veggie", role="veg",
                              macros=Macros(kcal=40 * LABEL_DRIFT, carb_g=10)),
    }
    plan = create_day_plan(db, person, profile, name="Exact day")
    return db, plan, foods


GRAMS_PER_POINT = {"fat": 15, "carb": 25, "protein": 25, "veggie": 100}


def _fill_exactly(db, plan, foods, *, carb_moves=0.0):
    """Every meal at its allotment; carb_moves points of carb go from 1 to 3."""
    for slot_no, pts in ALLOTMENTS.items():
        for name in ("fat", "carb", "protein", "veggie"):
            count = getattr(pts, name)
            if name == "carb" and slot_no == 1:
                count -= carb_moves
            if name == "carb" and slot_no == 3:
                count += carb_moves
            if count:
                add_entry(db, plan, slot_no=slot_no, food_id=foods[name],
                          qty=count * GRAMS_PER_POINT[name], unit="g")


def _slot(result, slot_no):
    return next(s for s in result.slots if s.slot_no == slot_no)


def test_exact_allotments_pass_whatever_the_labels_say(day):
    db, plan, foods = day
    _fill_exactly(db, plan, foods)
    result = evaluate(db, plan)
    assert result.basis == "points"
    assert result.totals.kcal == pytest.approx(1750)
    assert result.label_kcal == pytest.approx(1820)
    assert result.points == Points(6, 3, 6, 1)
    assert result.allotment == Points(6, 3, 6, 1)
    assert all(not s.hints for s in result.slots)
    assert result.fat_pct == pytest.approx(result.target_fat_pct)
    assert result.ok is True


def test_points_day_outside_kcal_window_fails(day):
    db, plan, foods = day
    _fill_exactly(db, plan, foods)
    add_entry(db, plan, slot_no=2, food_id=foods["fat"], qty=12, unit="g")
    result = evaluate(db, plan)
    assert result.deltas.kcal == pytest.approx(108)
    assert result.within_tolerance["kcal"] is False


def test_points_day_inside_kcal_window_passes_kcal(day):
    db, plan, foods = day
    _fill_exactly(db, plan, foods)
    add_entry(db, plan, slot_no=2, food_id=foods["protein"], qty=20, unit="g")
    assert evaluate(db, plan).within_tolerance["kcal"] is True


def test_meal_hint_does_not_fail_the_day(day):
    db, plan, foods = day
    _fill_exactly(db, plan, foods, carb_moves=0.5)
    result = evaluate(db, plan)
    assert _slot(result, 1).hints == ("½C short",)
    assert _slot(result, 3).hints == ("½C over",)
    assert _slot(result, 1).allotment == ALLOTMENTS[1]
    assert result.ok is True


def test_net_basis_changes_counted_carbs(day):
    db, plan, _ = day
    beans = create_item(db, name="Beans", role="carb",
                        macros=Macros(kcal=130, carb_g=30, fiber_g=10, protein_g=8))
    add_entry(db, plan, slot_no=1, food_id=beans, qty=100, unit="g")
    total = evaluate(db, plan)
    set_carb_basis(db, "net")
    net = evaluate(db, plan)
    assert total.totals.carb_g == pytest.approx(30)
    assert net.totals.carb_g == pytest.approx(20)
    assert net.points.carb == pytest.approx(0.8)
    assert net.slots[0].entries[0].counted_carb_g == pytest.approx(20)


def test_slot_without_template_has_no_allotment(day):
    db, plan, foods = day
    add_entry(db, plan, slot_no=7, food_id=foods["protein"], qty=25, unit="g")
    result = evaluate(db, plan)
    slot = _slot(result, 7)
    assert slot.allotment is None
    assert slot.hints == ()
    assert slot.points == Points(protein=1)


def test_empty_meals_carry_their_allotment(day):
    db, plan, _ = day
    slots = plan_slots(db, plan, evaluate(db, plan))
    assert [s.allotment for s in slots] == list(ALLOTMENTS.values())
    assert all(s.slot is None for s in slots)


def test_macros_profile_unchanged(db):
    plan_id, spec = seed_keto_plan_a(db)
    result = evaluate(db, plan_id)
    assert result.basis == "macros"
    assert result.label_kcal == result.totals.kcal
    assert result.totals.kcal == pytest.approx(spec["reported_totals"]["kcal"], rel=0.01)
    assert result.allotment is None
    assert all(s.allotment is None and s.hints == () for s in result.slots)
    assert result.target_fat_pct == pytest.approx(spec["profile"]["fat_pct"])
