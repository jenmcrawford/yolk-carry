import pytest

from yolk.food_entry import (
    LabelInput,
    LabelInputError,
    create_label_food,
    per_100g,
    preview,
    role_for,
    validate,
)
from yolk.points import load_rules, portions

CREPINI = LabelInput(
    name="Crepini", brand="Crepini", serving_g=116, kcal=240, fat_g=4, carb_g=25,
    fiber_g=1, sugar_alcohol_g=None, protein_g=20, unit="pancake", unit_qty=4,
)


def _with(**changes):
    from dataclasses import replace

    return replace(CREPINI, **changes)


def test_per_serving_converts_to_per_100g():
    m = per_100g(CREPINI)
    assert m.fat_g == pytest.approx(3.448, abs=0.001)
    assert m.carb_g == pytest.approx(21.552, abs=0.001)
    assert m.protein_g == pytest.approx(17.241, abs=0.001)
    assert m.kcal == pytest.approx(206.9, abs=0.1)


def test_blank_fiber_is_unknown_not_zero(db):
    food_id = create_label_food(db, _with(fiber_g=None))
    row = db.execute("SELECT fiber_g_100g FROM foods WHERE id = ?", (food_id,)).fetchone()
    assert row["fiber_g_100g"] is None


def test_sugar_alcohol_is_stored_per_100g(db):
    food_id = create_label_food(db, _with(sugar_alcohol_g=2.32))
    row = db.execute(
        "SELECT sugar_alcohol_g_100g FROM foods WHERE id = ?", (food_id,)
    ).fetchone()
    assert row["sugar_alcohol_g_100g"] == pytest.approx(2.0)


def test_role_follows_counts_as(db):
    rules = load_rules(db)
    m = per_100g(CREPINI)
    assert role_for("veggie", None, m, rules) == "veg"
    assert role_for("protein", None, m, rules) == "protein"
    assert role_for("free", "beverage", m, rules) == "beverage"
    birria = per_100g(_with(serving_g=142, fat_g=9, carb_g=1, protein_g=25))
    assert role_for("auto", None, birria, rules) == "protein"


def test_free_requires_free_role():
    assert "free_role" in validate(_with(counts_as="free"))
    assert validate(_with(counts_as="free", free_role="sauce")) == {}
    assert "free_role" in validate(_with(counts_as="free", free_role="dessert"))


def test_serving_must_be_positive():
    for bad in (0, None, -5):
        assert "serving_g" in validate(_with(serving_g=bad))


def test_macros_cannot_exceed_serving():
    errors = validate(_with(serving_g=30, fat_g=300))
    assert "30" in errors["fat_g"]


def test_fiber_cannot_exceed_carbs():
    assert "fiber_g" in validate(_with(fiber_g=30))


def test_required_numbers_and_name():
    errors = validate(_with(name="  ", kcal=None, protein_g=-1))
    assert set(errors) >= {"name", "kcal", "protein_g"}


def test_unit_needs_a_count():
    assert "unit_qty" in validate(_with(unit_qty=None))
    assert "unit_qty" in validate(_with(unit_qty=0))


def test_preview_shows_points_and_one_point(db):
    p = preview(db, CREPINI)
    assert p.errors == {}
    assert p.serving_points == "1C + ¾P + ¼F"
    assert p.serving_text == "4 pancake (116 g)"
    assert p.one_point.startswith("4 pancake (116 g) → 1C")


def test_preview_reports_errors_without_raising(db):
    p = preview(db, _with(serving_g=0))
    assert "serving_g" in p.errors
    assert p.serving_points == ""


def test_create_writes_unit_and_label_portion(db):
    food_id = create_label_food(db, CREPINI)
    unit = db.execute(
        "SELECT grams FROM food_units WHERE food_id = ? AND unit = 'pancake'", (food_id,)
    ).fetchone()
    assert unit["grams"] == pytest.approx(29.0)
    [portion] = portions(db, food_id)
    assert (portion.source, portion.qty, portion.unit, portion.claimed) == (
        "label", 4, "pancake", "1C + ¾P + ¼F"
    )
    row = db.execute(
        "SELECT verified, source, role, point_class FROM foods WHERE id = ?", (food_id,)
    ).fetchone()
    assert tuple(row) == (0, "label", "carb", None)


def test_no_unit_means_one_serving(db):
    food_id = create_label_food(db, _with(unit=None, unit_qty=None))
    unit = db.execute(
        "SELECT grams FROM food_units WHERE food_id = ? AND unit = 'serving'", (food_id,)
    ).fetchone()
    assert unit["grams"] == 116
    [portion] = portions(db, food_id)
    assert (portion.qty, portion.unit) == (1, "serving")


def test_create_rejects_duplicate_name_brand(db):
    create_label_food(db, CREPINI)
    with pytest.raises(LabelInputError) as caught:
        create_label_food(db, CREPINI)
    assert set(caught.value.errors) == {"name"}
    assert db.execute("SELECT count(*) AS n FROM foods").fetchone()["n"] == 1


def test_create_rejects_invalid_input(db):
    with pytest.raises(LabelInputError) as caught:
        create_label_food(db, _with(serving_g=0))
    assert "serving_g" in caught.value.errors
    assert db.execute("SELECT count(*) AS n FROM foods").fetchone()["n"] == 0
