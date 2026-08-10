import pytest

from yolk.foods import create_item
from yolk.macros import Macros
from yolk.people import create_person, create_profile
from yolk.planning.evaluate import add_entry, create_day_plan, evaluate


@pytest.fixture
def simple_plan(db):
    """A one-slot plan whose totals are trivially checkable by hand."""
    pid = create_person(db, "Jen")
    profile_id = create_profile(
        db, pid, name="training", effective_on="2026-07-14",
        kcal=2150, fat_pct=34, carb_pct=28, protein_pct=38,
    )
    chicken = create_item(
        db, name="Chicken Breast", role="protein",
        macros=Macros(kcal=120, protein_g=22.5, fat_g=2.6, carb_g=0), source="usda",
    )
    rice = create_item(
        db, name="White Rice, cooked", role="carb",
        macros=Macros(kcal=130, protein_g=2.7, fat_g=0.3, carb_g=28), source="usda",
    )
    plan_id = create_day_plan(db, pid, profile_id, name="Test Plan")
    add_entry(db, plan_id, slot_no=4, food_id=chicken, qty=200, unit="g")
    add_entry(db, plan_id, slot_no=4, food_id=rice, qty=150, unit="g")
    return plan_id


def test_evaluate_totals(db, simple_plan):
    result = evaluate(db, simple_plan)
    # 200 g chicken = 240 kcal, 45 g protein; 150 g rice = 195 kcal, 4.05 g protein
    assert result.totals.kcal == pytest.approx(435.0, abs=0.01)
    assert result.totals.protein_g == pytest.approx(49.05, abs=0.01)
    assert result.totals.carb_g == pytest.approx(42.0, abs=0.01)


def test_evaluate_groups_by_slot(db, simple_plan):
    result = evaluate(db, simple_plan)
    assert len(result.slots) == 1
    assert result.slots[0].slot_no == 4
    assert len(result.slots[0].entries) == 2
    assert result.slots[0].totals.kcal == pytest.approx(435.0, abs=0.01)


def test_evaluate_reports_deltas_against_target(db, simple_plan):
    result = evaluate(db, simple_plan)
    assert result.target.kcal == 2150
    # deltas are actual minus target, so a short day is negative
    assert result.deltas.kcal == pytest.approx(435.0 - 2150.0, abs=0.01)


def test_underfed_day_fails_tolerance(db, simple_plan):
    result = evaluate(db, simple_plan)
    assert result.within_tolerance["kcal"] is False
    assert result.within_tolerance["protein_g"] is False
    assert result.ok is False


def test_on_target_day_passes_tolerance(db):
    pid = create_person(db, "Jen")
    profile_id = create_profile(
        db, pid, name="test", effective_on="2026-01-01",
        kcal=1000, fat_pct=36, carb_pct=24, protein_pct=40,
    )
    # Target: 1000 kcal, 40 g fat, 60 g carb, 100 g protein.
    # One synthetic food at exactly those macros per 100 g, eaten 100 g.
    food = create_item(
        db, name="Exactly Target", role="protein",
        macros=Macros(kcal=1000, protein_g=100, fat_g=40, carb_g=60), source="manual",
    )
    plan_id = create_day_plan(db, pid, profile_id, name="Perfect")
    add_entry(db, plan_id, slot_no=1, food_id=food, qty=100, unit="g")

    result = evaluate(db, plan_id)
    assert result.within_tolerance == {
        "kcal": True, "protein_g": True, "fat_pct": True, "carb_pct": True,
    }
    assert result.ok is True


def test_fat_and_carb_judged_as_percentages_not_grams(db):
    """Fat and carb are banded on percent of calories, per the spec."""
    pid = create_person(db, "Jen")
    profile_id = create_profile(
        db, pid, name="test", effective_on="2026-01-01",
        kcal=1000, fat_pct=36, carb_pct=24, protein_pct=40,
    )
    # 1000 kcal, 100 g protein, but fat/carb swapped away from target:
    # 30 g fat (27%) and 87 g carb (34.8%) -> both outside the 3-point band.
    food = create_item(
        db, name="Skewed", role="protein",
        macros=Macros(kcal=1000, protein_g=100, fat_g=30, carb_g=87), source="manual",
    )
    plan_id = create_day_plan(db, pid, profile_id, name="Skewed Day")
    add_entry(db, plan_id, slot_no=1, food_id=food, qty=100, unit="g")

    result = evaluate(db, plan_id)
    assert result.within_tolerance["kcal"] is True
    assert result.within_tolerance["protein_g"] is True
    assert result.within_tolerance["fat_pct"] is False
    assert result.within_tolerance["carb_pct"] is False


def test_evaluate_does_not_mutate(db, simple_plan):
    before = db.execute(
        "SELECT id, qty, unit FROM day_plan_entries WHERE day_plan_id = ? "
        "ORDER BY id", (simple_plan,)
    ).fetchall()
    evaluate(db, simple_plan)
    after = db.execute(
        "SELECT id, qty, unit FROM day_plan_entries WHERE day_plan_id = ? "
        "ORDER BY id", (simple_plan,)
    ).fetchall()
    assert [tuple(r) for r in before] == [tuple(r) for r in after]


def test_evaluate_uses_display_units(db):
    pid = create_person(db, "Jen")
    profile_id = create_profile(
        db, pid, name="test", effective_on="2026-01-01",
        kcal=2000, fat_pct=34, carb_pct=28, protein_pct=38,
    )
    oil = create_item(
        db, name="Olive Oil", role="fat",
        macros=Macros(kcal=884, protein_g=0, fat_g=100, carb_g=0),
        source="usda", units={"tbsp": 13.5},
    )
    plan_id = create_day_plan(db, pid, profile_id, name="Oil Only")
    add_entry(db, plan_id, slot_no=6, food_id=oil, qty=1.5, unit="tbsp")

    result = evaluate(db, plan_id)
    # 1.5 tbsp = 20.25 g -> 179.01 kcal
    assert result.totals.kcal == pytest.approx(179.01, abs=0.01)
    assert result.slots[0].entries[0].grams == pytest.approx(20.25, abs=0.001)
