import pytest

from yolk.errors import MissingYieldError, RecipeCycleError
from yolk.foods import (
    create_item, create_recipe, derived_tags, macros_per_100g,
    portion_macros, recompute_recipe, set_cooked_yield,
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


def test_create_recipe_nesting_unyielded_recipe_is_atomic(db, pantry):
    """create_recipe computes initial macros inside its own transaction. If a
    yield is given but a nested component recipe has no cooked_yield_g of its
    own, the whole insert must roll back -- not commit a parent recipe row
    with no macros."""
    unweighed_id = create_recipe(
        db, name="Unweighed Component", role="sauce",
        components=[{"food_id": pantry["oil"], "qty": 50, "unit": "g"}],
    )
    foods_before = db.execute("SELECT COUNT(*) AS n FROM foods").fetchone()["n"]
    components_before = db.execute(
        "SELECT COUNT(*) AS n FROM food_components"
    ).fetchone()["n"]

    with pytest.raises(MissingYieldError):
        create_recipe(
            db, name="Nests Unweighed", role="sauce", cooked_yield_g=100.0,
            components=[{"food_id": unweighed_id, "qty": 50, "unit": "g"}],
        )

    row = db.execute(
        "SELECT COUNT(*) AS n FROM foods WHERE name = 'Nests Unweighed'"
    ).fetchone()
    assert row["n"] == 0
    assert db.execute("SELECT COUNT(*) AS n FROM foods").fetchone()["n"] == foods_before
    assert (
        db.execute("SELECT COUNT(*) AS n FROM food_components").fetchone()["n"]
        == components_before
    )


def test_macros_per_100g_raises_on_uncomputed_recipe(db, pantry):
    recipe_id = create_recipe(
        db, name="Uncomputed", role="sauce",
        components=[{"food_id": pantry["oil"], "qty": 50, "unit": "g"}],
    )
    with pytest.raises(MissingYieldError):
        macros_per_100g(db, recipe_id)


def test_portion_macros_raises_on_uncomputed_recipe(db, pantry):
    recipe_id = create_recipe(
        db, name="Uncomputed 2", role="sauce",
        components=[{"food_id": pantry["oil"], "qty": 50, "unit": "g"}],
    )
    with pytest.raises(MissingYieldError):
        portion_macros(db, recipe_id, 10, "g")


# --- servings-derived yield ------------------------------------------------


def test_servings_derives_yield_from_summed_component_grams(db, pantry):
    """No scale involved: the yield is the raw input weight, which the
    library already knows from the components."""
    recipe_id = create_recipe(
        db, name="Counted Sauce", role="sauce", servings=4,
        components=[
            {"food_id": pantry["oil"], "qty": 100, "unit": "g"},
            {"food_id": pantry["garlic"], "qty": 100, "unit": "g"},
        ],
    )
    row = db.execute(
        "SELECT cooked_yield_g FROM foods WHERE id = ?", (recipe_id,)
    ).fetchone()
    assert row["cooked_yield_g"] == pytest.approx(200.0)


def test_servings_adds_a_serving_unit(db, pantry):
    recipe_id = create_recipe(
        db, name="Counted Sauce", role="sauce", servings=4,
        components=[
            {"food_id": pantry["oil"], "qty": 100, "unit": "g"},
            {"food_id": pantry["garlic"], "qty": 100, "unit": "g"},
        ],
    )
    row = db.execute(
        "SELECT grams FROM food_units WHERE food_id = ? AND unit = 'serving'",
        (recipe_id,),
    ).fetchone()
    assert row is not None, "no serving unit was created"
    assert row["grams"] == pytest.approx(50.0)


def test_one_serving_is_total_macros_divided_by_servings(db, pantry):
    """100 g oil (884 kcal) + 100 g garlic (149 kcal) = 1033 kcal total.
    Four servings must be 258.25 kcal each."""
    recipe_id = create_recipe(
        db, name="Counted Sauce", role="sauce", servings=4,
        components=[
            {"food_id": pantry["oil"], "qty": 100, "unit": "g"},
            {"food_id": pantry["garlic"], "qty": 100, "unit": "g"},
        ],
    )
    m = portion_macros(db, recipe_id, 1, "serving")
    assert m.kcal == pytest.approx(1033.0 / 4, abs=0.01)


def test_serving_macros_do_not_depend_on_the_yield_weight(db, pantry):
    """The load-bearing claim: for a count-portioned recipe the yield weight
    cancels. A raw-derived yield of 200 g and a measured cooked yield of
    140 g must give identical macros per serving, which is why weighing the
    finished dish is unnecessary when portioning by count."""
    components = [
        {"food_id": pantry["oil"], "qty": 100, "unit": "g"},
        {"food_id": pantry["garlic"], "qty": 100, "unit": "g"},
    ]
    raw_derived = create_recipe(
        db, name="Raw Derived", role="sauce", servings=4, components=components
    )
    measured = create_recipe(
        db, name="Measured", role="sauce", cooked_yield_g=140.0,
        components=components, units={"serving": 35.0},
    )
    assert portion_macros(db, raw_derived, 1, "serving").kcal == pytest.approx(
        portion_macros(db, measured, 1, "serving").kcal, abs=1e-9
    )


def test_servings_marks_the_yield_as_raw_derived(db, pantry):
    """per-100 g is nominal on these recipes — correct per serving, wrong per
    gram — so it must be distinguishable from a measured yield."""
    recipe_id = create_recipe(
        db, name="Counted Sauce", role="sauce", servings=4,
        components=[{"food_id": pantry["oil"], "qty": 100, "unit": "g"}],
    )
    row = db.execute(
        "SELECT yield_basis FROM foods WHERE id = ?", (recipe_id,)
    ).fetchone()
    assert row["yield_basis"] == "raw_derived"


def test_measured_yield_is_marked_measured(db, pantry):
    recipe_id = create_recipe(
        db, name="Weighed Sauce", role="sauce", cooked_yield_g=140.0,
        components=[{"food_id": pantry["oil"], "qty": 100, "unit": "g"}],
    )
    row = db.execute(
        "SELECT yield_basis FROM foods WHERE id = ?", (recipe_id,)
    ).fetchone()
    assert row["yield_basis"] == "measured"


def test_servings_and_cooked_yield_together_are_rejected(db, pantry):
    """Two sources for one number. Picking one silently would make the
    resulting macros depend on an undocumented precedence rule."""
    with pytest.raises(ValueError) as exc:
        create_recipe(
            db, name="Ambiguous", role="sauce", servings=4, cooked_yield_g=140.0,
            components=[{"food_id": pantry["oil"], "qty": 100, "unit": "g"}],
        )
    assert "servings" in str(exc.value).lower()


def test_zero_servings_rejected(db, pantry):
    with pytest.raises(ValueError):
        create_recipe(
            db, name="Zero", role="sauce", servings=0,
            components=[{"food_id": pantry["oil"], "qty": 100, "unit": "g"}],
        )


def test_rejected_servings_leaves_no_orphan_recipe(db, pantry):
    with pytest.raises(ValueError):
        create_recipe(
            db, name="Zero", role="sauce", servings=0,
            components=[{"food_id": pantry["oil"], "qty": 100, "unit": "g"}],
        )
    row = db.execute(
        "SELECT COUNT(*) AS n FROM foods WHERE name = 'Zero'"
    ).fetchone()
    assert row["n"] == 0


def test_servings_yield_uses_display_units_for_components(db, pantry):
    """Components given in tbsp/clove must be converted to grams before
    summing, not summed as raw quantities."""
    recipe_id = create_recipe(
        db, name="Unit Sauce", role="sauce", servings=2,
        components=[
            {"food_id": pantry["oil"], "qty": 2, "unit": "tbsp"},    # 27.0 g
            {"food_id": pantry["garlic"], "qty": 3, "unit": "clove"},  # 9.0 g
        ],
    )
    row = db.execute(
        "SELECT cooked_yield_g FROM foods WHERE id = ?", (recipe_id,)
    ).fetchone()
    assert row["cooked_yield_g"] == pytest.approx(36.0)


def test_servings_with_an_explicit_serving_unit_is_rejected(db, pantry):
    """servings=n and units={'serving': x} are two sources for one number,
    exactly like servings + cooked_yield_g. Accepting both silently produced
    a recipe whose four servings did not add up to the batch."""
    with pytest.raises(ValueError) as exc:
        create_recipe(
            db, name="Contradiction", role="sauce", servings=4,
            components=[{"food_id": pantry["oil"], "qty": 200, "unit": "g"}],
            units={"serving": 35.0},
        )
    assert "serving" in str(exc.value).lower()


def test_servings_still_accepts_other_explicit_units(db, pantry):
    """Only the 'serving' key conflicts. A souper_cube weight is unrelated."""
    recipe_id = create_recipe(
        db, name="Cubed", role="sauce", servings=4,
        components=[{"food_id": pantry["oil"], "qty": 200, "unit": "g"}],
        units={"souper_cube": 120.0},
    )
    rows = dict(
        db.execute(
            "SELECT unit, grams FROM food_units WHERE food_id = ?", (recipe_id,)
        ).fetchall()
    )
    assert rows["serving"] == pytest.approx(50.0)
    assert rows["souper_cube"] == pytest.approx(120.0)


# --- recording a yield after the fact --------------------------------------


def test_set_cooked_yield_computes_macros_on_a_deferred_recipe(db, pantry):
    """The create-now, cook-later flow: a recipe made without a yield must
    have a supported way to receive one, not a hand-written UPDATE."""
    recipe_id = create_recipe(
        db, name="Deferred", role="sauce",
        components=[{"food_id": pantry["oil"], "qty": 100, "unit": "g"}],
    )
    with pytest.raises(MissingYieldError):
        macros_per_100g(db, recipe_id)

    set_cooked_yield(db, recipe_id, 50.0)

    assert macros_per_100g(db, recipe_id).kcal == pytest.approx(1768.0, abs=0.01)


def test_set_cooked_yield_marks_the_basis_measured(db, pantry):
    recipe_id = create_recipe(
        db, name="Deferred", role="sauce",
        components=[{"food_id": pantry["oil"], "qty": 100, "unit": "g"}],
    )
    set_cooked_yield(db, recipe_id, 50.0)
    row = db.execute(
        "SELECT yield_basis FROM foods WHERE id = ?", (recipe_id,)
    ).fetchone()
    assert row["yield_basis"] == "measured"


def test_set_cooked_yield_rejects_non_positive(db, pantry):
    recipe_id = create_recipe(
        db, name="Deferred", role="sauce",
        components=[{"food_id": pantry["oil"], "qty": 100, "unit": "g"}],
    )
    with pytest.raises(ValueError):
        set_cooked_yield(db, recipe_id, 0.0)


def test_set_cooked_yield_rejects_items(db, pantry):
    """An item's macros come from its source, not from a yield division."""
    with pytest.raises(ValueError) as exc:
        set_cooked_yield(db, pantry["oil"], 50.0)
    assert "recipe" in str(exc.value).lower()
