import pytest

from yolk.foods import add_unit, create_item, macros_per_100g, portion_macros
from yolk.macros import Macros


def test_create_item_returns_id_and_round_trips(db):
    food_id = create_item(
        db,
        name="Chicken Breast, raw",
        role="protein",
        macros=Macros(kcal=120, protein_g=22.5, fat_g=2.6, carb_g=0.0),
        source="usda",
        source_ref="171077",
    )
    assert isinstance(food_id, int)
    m = macros_per_100g(db, food_id)
    assert m.kcal == 120
    assert m.protein_g == pytest.approx(22.5)


def test_create_item_with_units(db):
    food_id = create_item(
        db,
        name="Mayonnaise",
        brand="Primal Kitchen",
        role="fat",
        macros=Macros(kcal=680, protein_g=0, fat_g=75, carb_g=0),
        source="label",
        units={"tbsp": 14.0},
    )
    row = db.execute(
        "SELECT grams FROM food_units WHERE food_id = ? AND unit = 'tbsp'", (food_id,)
    ).fetchone()
    assert row["grams"] == 14.0


def test_portion_macros_scales_by_grams(db):
    food_id = create_item(
        db,
        name="Olive Oil",
        role="fat",
        macros=Macros(kcal=884, protein_g=0, fat_g=100, carb_g=0),
        source="usda",
        units={"tbsp": 13.5},
    )
    # 2 tbsp = 27 g = 0.27 x per-100g values
    m = portion_macros(db, food_id, 2, "tbsp")
    assert m.kcal == pytest.approx(238.68, abs=0.01)
    assert m.fat_g == pytest.approx(27.0, abs=0.01)


def test_portion_macros_in_grams_needs_no_unit_row(db):
    food_id = create_item(
        db,
        name="Ground Turkey 93/7",
        role="protein",
        macros=Macros(kcal=170, protein_g=21, fat_g=9.4, carb_g=0),
        source="usda",
    )
    m = portion_macros(db, food_id, 150, "g")
    assert m.kcal == pytest.approx(255.0)
    assert m.protein_g == pytest.approx(31.5)


def test_duplicate_name_and_brand_rejected(db):
    import sqlite3

    create_item(
        db, name="Skyr", brand="Siggi's", role="protein",
        macros=Macros(kcal=63, protein_g=11, fat_g=0.2, carb_g=4), source="label",
    )
    with pytest.raises(sqlite3.IntegrityError):
        create_item(
            db, name="Skyr", brand="Siggi's", role="protein",
            macros=Macros(kcal=99, protein_g=9, fat_g=1, carb_g=5), source="label",
        )


def test_same_name_different_brand_allowed(db):
    a = create_item(
        db, name="Skyr", brand="Siggi's", role="protein",
        macros=Macros(kcal=63, protein_g=11, fat_g=0.2, carb_g=4), source="label",
    )
    b = create_item(
        db, name="Skyr", brand="Icelandic Provisions", role="protein",
        macros=Macros(kcal=70, protein_g=12, fat_g=0.3, carb_g=4), source="label",
    )
    assert a != b


def test_add_unit_sets_default_display(db):
    food_id = create_item(
        db, name="Karbolyn", role="supplement",
        macros=Macros(kcal=380, protein_g=0, fat_g=0, carb_g=95), source="label",
    )
    add_unit(db, food_id, "scoop", 50.0, is_default_display=True)
    row = db.execute(
        "SELECT is_default_display FROM food_units WHERE food_id = ?", (food_id,)
    ).fetchone()
    assert row["is_default_display"] == 1


def test_failed_unit_insert_leaves_no_orphan_food(db):
    import sqlite3

    # Attempt to create a food with a unit that violates the grams > 0 CHECK constraint.
    # This should raise IntegrityError and roll back the entire transaction,
    # leaving no food row behind.
    with pytest.raises(sqlite3.IntegrityError):
        create_item(
            db, name="Bad Measurement", role="protein",
            macros=Macros(kcal=100, protein_g=20, fat_g=1, carb_g=0),
            source="test",
            units={"invalid": 0},  # Violates food_units.grams > 0
        )
    # Verify the food row was rolled back, not just the unit insert.
    count = db.execute(
        "SELECT COUNT(*) as cnt FROM foods WHERE name = 'Bad Measurement'"
    ).fetchone()["cnt"]
    assert count == 0
