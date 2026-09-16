import pytest

from yolk.errors import UnknownUnitError
from yolk.units import to_grams


@pytest.fixture
def olive_oil(db):
    row = db.execute(
        "INSERT INTO foods (kind, name, role, kcal_100g, protein_g_100g, "
        "fat_g_100g, carb_g_100g, source) "
        "VALUES ('item', 'Olive Oil', 'fat', 884, 0, 100, 0, 'usda') RETURNING id"
    ).fetchone()
    food_id = row["id"]
    db.execute(
        "INSERT INTO food_units (food_id, unit, grams, is_default_display) "
        "VALUES (?, 'tbsp', 13.5, 1)",
        (food_id,),
    )
    db.commit()
    return food_id


def test_grams_pass_through(db, olive_oil):
    assert to_grams(db, olive_oil, 25, "g") == 25


def test_kilograms_convert(db, olive_oil):
    assert to_grams(db, olive_oil, 1.5, "kg") == 1500


def test_food_specific_unit(db, olive_oil):
    assert to_grams(db, olive_oil, 2, "tbsp") == pytest.approx(27.0)


def test_fractional_quantity(db, olive_oil):
    assert to_grams(db, olive_oil, 0.25, "tbsp") == pytest.approx(3.375)


def test_unknown_unit_raises_naming_food_and_unit(db, olive_oil):
    with pytest.raises(UnknownUnitError) as exc:
        to_grams(db, olive_oil, 1, "scoop")
    message = str(exc.value)
    assert "Olive Oil" in message
    assert "scoop" in message


def test_unit_is_not_shared_between_foods(db, olive_oil):
    """A tbsp of one food is not a tbsp of another. Conversions are per-food."""
    row = db.execute(
        "INSERT INTO foods (kind, name, role, kcal_100g, protein_g_100g, "
        "fat_g_100g, carb_g_100g, source) "
        "VALUES ('item', 'Mayo', 'fat', 680, 1, 75, 0, 'label') RETURNING id"
    ).fetchone()
    mayo_id = row["id"]
    db.commit()
    with pytest.raises(UnknownUnitError):
        to_grams(db, mayo_id, 1, "tbsp")


def test_round_trip_grams_to_unit_and_back(db, olive_oil):
    from yolk.units import from_grams

    grams = to_grams(db, olive_oil, 3, "tbsp")
    assert from_grams(db, olive_oil, grams, "tbsp") == pytest.approx(3.0)
