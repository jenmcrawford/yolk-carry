"""Findings from the final branch review, each pinned by a test."""

import json

import pytest

from yolk.food_entry import FoodEdit, LabelInputError, food_detail, update_food
from yolk.foods import create_item, create_recipe, macros_per_100g
from yolk.inbox import INBOX_COLUMNS, InboxError, import_inbox
from yolk.macros import Macros
from yolk.points import load_rules, set_carb_basis
from yolk.seed import POINT_FIXTURE_PATH


def _edit(conn, food_id, **changes):
    d = food_detail(conn, food_id)
    m = d.summary.per_100g
    base = dict(
        name=d.summary.name, brand=d.summary.brand, kcal=m.kcal, fat_g=m.fat_g,
        carb_g=m.carb_g, fiber_g=m.fiber_g if d.summary.fiber_known else None,
        sugar_alcohol_g=d.sugar_alcohol_g_100g, protein_g=m.protein_g,
        counts_as=d.summary.point_class or "auto", free_role=None,
        units=dict(d.summary.units), manual_portion=None,
    )
    return FoodEdit(**{**base, **changes})


@pytest.fixture
def bar_in_recipe(db):
    bar = create_item(
        db, name="Bar", role="carb",
        macros=Macros(kcal=200, fat_g=10, carb_g=20, protein_g=10), units={"bar": 50.0},
    )
    recipe = create_recipe(
        db, name="Snack plate", role="carb", servings=1,
        components=[{"food_id": bar, "qty": 2, "unit": "bar"}],
    )
    return bar, recipe


def test_editing_a_food_recomputes_recipes_that_contain_it(db, bar_in_recipe):
    bar, recipe = bar_in_recipe
    update_food(db, bar, _edit(db, bar, fat_g=30.0, kcal=380.0))
    assert macros_per_100g(db, recipe).fat_g == pytest.approx(30.0)
    assert macros_per_100g(db, recipe).kcal == pytest.approx(380.0)


def test_a_unit_a_recipe_uses_cannot_be_removed(db, bar_in_recipe):
    bar, _ = bar_in_recipe
    with pytest.raises(LabelInputError) as caught:
        update_food(db, bar, _edit(db, bar, units={}))
    assert "Snack plate" in caught.value.errors["units"]


def test_editing_keeps_a_role_the_class_did_not_change(db):
    karbolyn = create_item(
        db, name="Karbolyn", role="supplement",
        macros=Macros(kcal=400, carb_g=100), units={"scoop": 50.0},
    )
    update_food(db, karbolyn, _edit(db, karbolyn, name="Karbolyn powder"))
    row = db.execute("SELECT role FROM foods WHERE id = ?", (karbolyn,)).fetchone()
    assert row["role"] == "supplement"


def test_changing_the_class_still_sets_the_role(db):
    food_id = create_item(
        db, name="Mystery", role="supplement", macros=Macros(kcal=100, protein_g=25),
    )
    update_food(db, food_id, _edit(db, food_id, counts_as="protein"))
    assert db.execute("SELECT role FROM foods WHERE id = ?", (food_id,)).fetchone()["role"] == "protein"


def test_flagged_coach_foods_are_not_seeded_as_checked():
    fixture = json.loads(POINT_FIXTURE_PATH.read_text(encoding="utf-8"))
    flagged_and_checked = [
        f["name"] for f in fixture["foods"]
        if f["source_note"].startswith("FLAG") and f["verified"]
    ]
    assert flagged_and_checked == []


def test_a_cp1252_csv_is_refused_with_a_message(db, tmp_path):
    path = tmp_path / "excel.csv"
    path.write_bytes(
        (",".join(INBOX_COLUMNS) + "\r\n"
         "Jalapeño dip,,,2 tbsp,30,60,5,2,0,,1,fat,,,\r\n").encode("cp1252")
    )
    with pytest.raises(InboxError) as caught:
        import_inbox(db, path)
    assert "UTF-8" in str(caught.value)


def test_fiber_unknown_shows_on_the_food_list(client, seeded):
    from yolk.db.connection import connect

    conn = connect(seeded[0])
    create_item(
        conn, name="Zuppa", role="carb", macros=Macros(kcal=83, fat_g=4.6, carb_g=7.4),
        fiber_known=False,
    )
    conn.close()
    assert "fiber unknown" in client.get("/foods", params={"q": "zuppa"}).text
    assert "fiber unknown" not in client.get("/foods", params={"q": "pork rinds"}).text


def test_fiber_unknown_shows_on_plan_rows(db):
    from yolk.planning.evaluate import evaluate
    from yolk.seed import seed_keto_plan_a

    plan_id, _ = seed_keto_plan_a(db)
    food_id = db.execute("SELECT food_id FROM day_plan_entries LIMIT 1").fetchone()["food_id"]
    db.execute("UPDATE foods SET fiber_g_100g = NULL WHERE id = ?", (food_id,))
    entries = [e for s in evaluate(db, plan_id).slots for e in s.entries if e.food_id == food_id]
    assert entries and all(e.fiber_known is False for e in entries)
