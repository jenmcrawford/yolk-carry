import pytest

from yolk.errors import MissingYieldError, UnknownUnitError
from yolk.foods import create_item, create_recipe
from yolk.macros import Macros
from yolk.points import (
    Points,
    add_portion,
    fiber_known,
    food_points,
    load_rules,
    one_point,
    portions,
    preferred_portion,
)


def _item(db, name, role="protein", **macros):
    return create_item(db, name=name, role=role, macros=Macros(kcal=100, **macros))


def test_item_points_scale_with_grams(db):
    food_id = _item(db, "Thigh", fat_g=10, protein_g=25)
    p = food_points(db, food_id, 200, load_rules(db))
    assert p.fat == pytest.approx(2 * 10 / 15)
    assert p.protein == pytest.approx(2)
    assert p.carb == 0


def test_veg_role_defaults_to_veggie_class(db):
    food_id = _item(db, "Broccoli", role="veg", carb_g=5)
    row = db.execute("SELECT point_class FROM foods WHERE id = ?", (food_id,)).fetchone()
    assert row["point_class"] == "veggie"


def test_recipe_points_sum_components_under_their_own_class(db):
    chicken = _item(db, "Chicken", protein_g=25)
    broccoli = _item(db, "Broccoli", role="veg", carb_g=5)
    stir_fry = create_recipe(
        db, name="Stir fry", role="protein", servings=1,
        components=[
            {"food_id": chicken, "qty": 100, "unit": "g"},
            {"food_id": broccoli, "qty": 200, "unit": "g"},
        ],
    )
    p = food_points(db, stir_fry, 300, load_rules(db))
    assert p.protein == pytest.approx(1)
    assert p.veggie == pytest.approx(1)
    assert p.carb == 0


def test_recipe_with_missing_yield_raises(db):
    chicken = _item(db, "Chicken", protein_g=25)
    unweighed = create_recipe(
        db, name="Soup", role="protein",
        components=[{"food_id": chicken, "qty": 100, "unit": "g"}],
    )
    with pytest.raises(MissingYieldError):
        food_points(db, unweighed, 100, load_rules(db))


def test_one_point_portion_falls_back_to_ounces(db):
    food_id = _item(db, "Chicken breast", protein_g=25)
    portion = one_point(db, food_id, load_rules(db))
    assert portion.unit == "oz"
    assert portion.qty == 3.5
    assert portion.grams == pytest.approx(3.5 * 28.349523125)
    assert portion.label.startswith("3½ oz (99 g) → 1P")


def test_one_point_portion_uses_own_unit(db):
    food_id = create_item(
        db, name="Whey", role="protein",
        macros=Macros(kcal=100, protein_g=20), units={"scoop": 31.0},
    )
    portion = one_point(db, food_id, load_rules(db))
    assert portion.unit == "scoop"
    assert portion.qty == 4.0


def test_one_point_is_none_for_free_and_zero_macro(db):
    broth = create_item(
        db, name="Broth", role="beverage", macros=Macros(kcal=5, protein_g=1),
        point_class="free",
    )
    oil = create_item(
        db, name="Oil", role="fat", macros=Macros(kcal=884, fat_g=100),
        point_class="carb",
    )
    rules = load_rules(db)
    assert one_point(db, broth, rules) is None
    assert one_point(db, oil, rules) is None


def test_portions_order_manual_first(db):
    food_id = _item(db, "Chicken", protein_g=25)
    add_portion(db, food_id, source="coach", qty=4, unit="oz", claimed="1P")
    assert preferred_portion(db, food_id).source == "coach"
    add_portion(db, food_id, source="manual", qty=5, unit="oz", claimed="1P")
    assert preferred_portion(db, food_id).source == "manual"
    assert [p.source for p in portions(db, food_id)] == ["manual", "coach"]
    assert portions(db, food_id)[1].grams == pytest.approx(4 * 28.349523125)


def test_no_portion_means_none(db):
    assert preferred_portion(db, _item(db, "Chicken", protein_g=25)) is None


def test_add_portion_rejects_unknown_unit(db):
    food_id = _item(db, "Chicken", protein_g=25)
    with pytest.raises(UnknownUnitError):
        add_portion(db, food_id, source="coach", qty=1, unit="breast", claimed="1P")
    assert portions(db, food_id) == []


def test_fiber_known_tracks_null_fiber(db):
    food_id = _item(db, "Beans", role="carb", carb_g=20)
    assert fiber_known(db, food_id) is True
    db.execute("UPDATE foods SET fiber_g_100g = NULL WHERE id = ?", (food_id,))
    assert fiber_known(db, food_id) is False


def test_unknown_fiber_under_net_counts_total(db):
    food_id = _item(db, "Beans", role="carb", carb_g=25)
    db.execute("UPDATE foods SET fiber_g_100g = NULL WHERE id = ?", (food_id,))
    db.execute("UPDATE settings SET value = 'net' WHERE key = 'carb_basis'")
    assert food_points(db, food_id, 100, load_rules(db)) == Points(carb=1)


def test_one_point_portion_picks_the_unit_that_fits(db):
    # One fat point of almond butter is ~27 g: 1¾ tbsp, not ¼ cup (62 g).
    food_id = create_item(
        db, name="Almond butter", role="fat",
        macros=Macros(kcal=614, fat_g=55.5, carb_g=18.8, protein_g=21.0),
        units={"cup": 250.0, "tbsp": 16.0},
    )
    portion = one_point(db, food_id, load_rules(db))
    assert portion.unit == "tbsp"
    assert portion.qty == 1.75
