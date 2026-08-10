import pytest

from yolk.errors import MissingYieldError, RecipeCycleError
from yolk.foods import (
    create_item, create_recipe, derived_tags, macros_per_100g,
    portion_macros, recompute_recipe,
)
from yolk.macros import Macros


@pytest.fixture
def pantry(db):
    """A few items with round numbers, so expected values are checkable by hand."""
    ids = {}
    ids["oil"] = create_item(
        db, name="Olive Oil", role="fat",
        macros=Macros(kcal=884, protein_g=0, fat_g=100, carb_g=0),
        source="usda", units={"tbsp": 13.5},
    )
    ids["garlic"] = create_item(
        db, name="Garlic", role="veg",
        macros=Macros(kcal=149, protein_g=6.4, fat_g=0.5, carb_g=33),
        source="usda", units={"clove": 3.0},
    )
    ids["parsley"] = create_item(
        db, name="Parsley", role="veg",
        macros=Macros(kcal=36, protein_g=3.0, fat_g=0.8, carb_g=6.3),
        source="usda", units={"cup": 60.0},
    )
    ids["steak"] = create_item(
        db, name="Sirloin Steak, raw", role="protein",
        macros=Macros(kcal=201, protein_g=21.6, fat_g=12.7, carb_g=0),
        source="usda",
    )
    return ids


def test_recipe_computes_macros_from_components_and_yield(db, pantry):
    # 100 g oil + 100 g garlic, yielding 200 g of finished sauce.
    # Per 100 g: (884 + 149) / 2 = 516.5 kcal
    recipe_id = create_recipe(
        db, name="Test Sauce", role="sauce", cooked_yield_g=200.0,
        components=[
            {"food_id": pantry["oil"], "qty": 100, "unit": "g"},
            {"food_id": pantry["garlic"], "qty": 100, "unit": "g"},
        ],
    )
    m = macros_per_100g(db, recipe_id)
    assert m.kcal == pytest.approx(516.5, abs=0.01)
    assert m.fat_g == pytest.approx(50.25, abs=0.01)


def test_recipe_yield_smaller_than_input_concentrates_macros(db, pantry):
    """Cooking off water raises macro density. This is why yield weight matters."""
    recipe_id = create_recipe(
        db, name="Reduced Sauce", role="sauce", cooked_yield_g=100.0,
        components=[
            {"food_id": pantry["oil"], "qty": 100, "unit": "g"},
            {"food_id": pantry["garlic"], "qty": 100, "unit": "g"},
        ],
    )
    m = macros_per_100g(db, recipe_id)
    assert m.kcal == pytest.approx(1033.0, abs=0.01)


def test_recipe_without_yield_refuses_to_compute(db, pantry):
    recipe_id = create_recipe(
        db, name="Unyielded", role="sauce",
        components=[{"food_id": pantry["oil"], "qty": 50, "unit": "g"}],
    )
    with pytest.raises(MissingYieldError) as exc:
        recompute_recipe(db, recipe_id)
    assert "Unyielded" in str(exc.value)


def test_recipe_components_accept_display_units(db, pantry):
    # 2 tbsp oil = 27 g; 4 cloves garlic = 12 g; yield 39 g
    recipe_id = create_recipe(
        db, name="Garlic Oil", role="sauce", cooked_yield_g=39.0,
        components=[
            {"food_id": pantry["oil"], "qty": 2, "unit": "tbsp"},
            {"food_id": pantry["garlic"], "qty": 4, "unit": "clove"},
        ],
    )
    m = macros_per_100g(db, recipe_id)
    expected_kcal = (884 * 0.27 + 149 * 0.12) / 39.0 * 100
    assert m.kcal == pytest.approx(expected_kcal, abs=0.01)


def test_recipe_nests_inside_another_recipe(db, pantry):
    sauce_id = create_recipe(
        db, name="Chimichurri", role="sauce", cooked_yield_g=100.0,
        components=[
            {"food_id": pantry["oil"], "qty": 50, "unit": "g"},
            {"food_id": pantry["parsley"], "qty": 50, "unit": "g"},
        ],
    )
    dinner_id = create_recipe(
        db, name="Steak with Chimichurri", role="protein", cooked_yield_g=200.0,
        components=[
            {"food_id": pantry["steak"], "qty": 170, "unit": "g"},
            {"food_id": sauce_id, "qty": 30, "unit": "g"},
        ],
    )
    m = macros_per_100g(db, dinner_id)
    sauce_kcal_100g = (884 * 0.5 + 36 * 0.5)
    expected = (201 * 1.70 + sauce_kcal_100g * 0.30) / 200.0 * 100
    assert m.kcal == pytest.approx(expected, abs=0.01)


def test_direct_self_reference_rejected_by_schema(db, pantry):
    """A recipe containing itself is caught by the CHECK constraint, before
    any Python-level cycle detection is reached."""
    import sqlite3

    recipe_id = create_recipe(
        db, name="Loop", role="sauce", cooked_yield_g=100.0,
        components=[{"food_id": pantry["oil"], "qty": 100, "unit": "g"}],
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO food_components (parent_food_id, child_food_id, qty, unit) "
            "VALUES (?, ?, 1, 'g')",
            (recipe_id, recipe_id),
        )


def test_mutually_recursive_recipes_rejected(db, pantry):
    a_id = create_recipe(
        db, name="A", role="sauce", cooked_yield_g=100.0,
        components=[{"food_id": pantry["oil"], "qty": 100, "unit": "g"}],
    )
    b_id = create_recipe(
        db, name="B", role="sauce", cooked_yield_g=100.0,
        components=[{"food_id": a_id, "qty": 50, "unit": "g"}],
    )
    # Now make A depend on B, closing the loop.
    db.execute(
        "INSERT INTO food_components (parent_food_id, child_food_id, qty, unit) "
        "VALUES (?, ?, 10, 'g')",
        (a_id, b_id),
    )
    db.commit()
    with pytest.raises(RecipeCycleError):
        recompute_recipe(db, a_id)


def test_derived_tags_union_components_including_nested(db, pantry):
    db.execute("INSERT INTO tags (name, kind) VALUES ('allium', 'ingredient_class')")
    db.execute("INSERT INTO tags (name, kind) VALUES ('nightshade', 'ingredient_class')")
    db.commit()
    allium = db.execute("SELECT id FROM tags WHERE name = 'allium'").fetchone()["id"]
    db.execute(
        "INSERT INTO food_tags (food_id, tag_id) VALUES (?, ?)",
        (pantry["garlic"], allium),
    )
    db.commit()

    sauce_id = create_recipe(
        db, name="Allium Sauce", role="sauce", cooked_yield_g=100.0,
        components=[
            {"food_id": pantry["oil"], "qty": 50, "unit": "g"},
            {"food_id": pantry["garlic"], "qty": 50, "unit": "g"},
        ],
    )
    dinner_id = create_recipe(
        db, name="Steak with Allium Sauce", role="protein", cooked_yield_g=200.0,
        components=[
            {"food_id": pantry["steak"], "qty": 170, "unit": "g"},
            {"food_id": sauce_id, "qty": 30, "unit": "g"},
        ],
    )
    # Two levels deep: garlic -> sauce -> dinner
    assert "allium" in derived_tags(db, dinner_id)
    assert "nightshade" not in derived_tags(db, dinner_id)


def test_flex_component_requires_bounds(db, pantry):
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        create_recipe(
            db, name="Bad Flex", role="sauce", cooked_yield_g=100.0,
            components=[
                {"food_id": pantry["oil"], "qty": 50, "unit": "g", "flex": True},
            ],
        )


def test_rejected_component_leaves_no_orphan_recipe(db, pantry):
    """A failed create must roll back the food row, not leave an empty recipe."""
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        create_recipe(
            db, name="Bad Flex 2", role="sauce", cooked_yield_g=100.0,
            components=[
                {"food_id": pantry["oil"], "qty": 50, "unit": "g", "flex": True},
            ],
        )
    row = db.execute(
        "SELECT COUNT(*) AS n FROM foods WHERE name = 'Bad Flex 2'"
    ).fetchone()
    assert row["n"] == 0
