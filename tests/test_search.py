from yolk.foods import create_item, search_library
from yolk.macros import Macros

SOME = Macros(kcal=100, protein_g=10, fat_g=5, carb_g=2)


def _names(results):
    return [food.name for food in results]


def test_search_matches_the_name_case_insensitively(db):
    create_item(db, name="Chicken Breast", role="protein", macros=SOME)
    create_item(db, name="Pork Rinds", role="protein", macros=SOME)
    assert _names(search_library(db, "chicken")) == ["Chicken Breast"]
    assert _names(search_library(db, "CHICK")) == ["Chicken Breast"]


def test_search_matches_the_brand(db):
    create_item(db, name="Mayonnaise", brand="Primal Kitchen", role="fat", macros=SOME)
    create_item(db, name="Olive Oil", role="fat", macros=SOME)
    assert _names(search_library(db, "primal")) == ["Mayonnaise"]


def test_an_empty_query_lists_everything_ordered_by_name_ignoring_case(db):
    create_item(db, name="Chicken", role="protein", macros=SOME)
    create_item(db, name="beef jerky", role="protein", macros=SOME)
    create_item(db, name="Avocado", role="fat", macros=SOME)
    expected = ["Avocado", "beef jerky", "Chicken"]
    assert _names(search_library(db, "")) == expected
    assert _names(search_library(db, "   ")) == expected


def test_wildcard_characters_in_the_query_match_themselves(db):
    create_item(db, name="Milk 2%", role="beverage", macros=SOME)
    create_item(db, name="Oats", role="carb", macros=SOME)
    assert _names(search_library(db, "%")) == ["Milk 2%"]
    assert _names(search_library(db, "_")) == []


def test_a_summary_carries_macros_units_and_review_state(db):
    create_item(
        db, name="Mayonnaise", brand="Primal Kitchen", role="fat",
        macros=Macros(kcal=680, protein_g=0, fat_g=75, carb_g=0),
        units={"tbsp": 14.0, "cup": 224.0},
    )
    [food] = search_library(db, "mayo")
    assert (food.kind, food.role, food.brand, food.verified) == (
        "item", "fat", "Primal Kitchen", False
    )
    assert food.per_100g.kcal == 680
    assert food.per_100g.fat_g == 75
    assert food.units == [("cup", 224.0), ("tbsp", 14.0)]


def test_a_recipe_without_computed_macros_is_listed_without_them(db):
    db.execute(
        "INSERT INTO foods (kind, name, role, source) "
        "VALUES ('recipe', 'Chili', 'protein', 'computed')"
    )
    db.commit()
    [food] = search_library(db, "chili")
    assert food.kind == "recipe"
    assert food.per_100g is None
    assert food.units == []
