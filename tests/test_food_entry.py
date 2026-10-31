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


SEARCH_HIT = {
    "fdcId": 171077,
    "description": "Chicken, broiler or fryers, breast, skinless, boneless, meat only, raw",
    "foodNutrients": [
        {"nutrientId": 1008, "value": 120.0},
        {"nutrientId": 1003, "value": 22.5},
        {"nutrientId": 1004, "value": 2.62},
        {"nutrientId": 1005, "value": 0.0},
    ],
}


def _fake_usda(monkeypatch, *, search=None):
    from yolk.sources import usda
    from test_usda import SAMPLE_PAYLOAD

    monkeypatch.setattr(usda, "search_foods", search or (lambda q, page_size=10: [SEARCH_HIT]))
    monkeypatch.setattr(usda, "get_food", lambda fdc_id: SAMPLE_PAYLOAD)


def test_usda_search_lists_points_per_100g(db, monkeypatch):
    from yolk.food_entry import usda_search

    _fake_usda(monkeypatch)
    [choice] = usda_search("chicken", load_rules(db))
    assert choice.fdc_id == 171077
    assert choice.per_100g.protein_g == 22.5
    assert choice.points_100g == "1P + ¼F"


def test_usda_unavailable_wraps_missing_key(db, monkeypatch):
    from yolk.food_entry import UsdaUnavailable, usda_search

    def no_key(q, page_size=10):
        raise RuntimeError("USDA_API_KEY is not set. Add it to .env")

    _fake_usda(monkeypatch, search=no_key)
    with pytest.raises(UsdaUnavailable, match=".env"):
        usda_search("chicken", load_rules(db))


def test_create_usda_food_sets_class_and_role(db, monkeypatch):
    from yolk.food_entry import create_usda_food

    _fake_usda(monkeypatch)
    food_id = create_usda_food(db, 171077, counts_as="protein", free_role=None)
    row = db.execute(
        "SELECT role, point_class, source, source_ref, verified FROM foods WHERE id = ?",
        (food_id,),
    ).fetchone()
    assert tuple(row) == ("protein", "protein", "usda", "171077", 0)


def test_create_usda_food_free_needs_kind(db, monkeypatch):
    from yolk.food_entry import create_usda_food

    _fake_usda(monkeypatch)
    with pytest.raises(LabelInputError) as caught:
        create_usda_food(db, 171077, counts_as="free", free_role=None)
    assert "free_role" in caught.value.errors
    assert db.execute("SELECT count(*) AS n FROM foods").fetchone()["n"] == 0
