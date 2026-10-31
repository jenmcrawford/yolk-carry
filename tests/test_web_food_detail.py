from datetime import date

import pytest
from fastapi.testclient import TestClient

from yolk.db.connection import connect, create_schema
from yolk.food_entry import FoodEdit, LabelInputError, food_detail, mark_checked, update_food
from yolk.foods import create_recipe
from yolk.points import portions, preferred_portion
from yolk.seed import seed_keto_plan_a, seed_point_system
from yolk.web.app import create_app


@pytest.fixture
def library(tmp_path):
    path = tmp_path / "yolk.db"
    conn = connect(path)
    create_schema(conn)
    seed_keto_plan_a(conn)
    seed_point_system(conn)
    conn.close()
    return path


@pytest.fixture
def app(library):
    return TestClient(
        create_app(library),
        base_url="http://127.0.0.1",
        headers={"origin": "http://127.0.0.1"},
    )


@pytest.fixture
def conn(library):
    c = connect(library)
    yield c
    c.close()


def _id(conn, name):
    return conn.execute("SELECT id FROM foods WHERE name = ?", (name,)).fetchone()["id"]


def _edit(conn, food_id, **changes):
    d = food_detail(conn, food_id)
    m = d.summary.per_100g
    base = dict(
        name=d.summary.name, brand=d.summary.brand, kcal=m.kcal, fat_g=m.fat_g,
        carb_g=m.carb_g, fiber_g=m.fiber_g, sugar_alcohol_g=d.sugar_alcohol_g_100g,
        protein_g=m.protein_g, counts_as=d.summary.point_class or "auto", free_role=None,
        units=dict(d.summary.units), manual_portion=None,
    )
    return FoodEdit(**{**base, **changes})


def test_detail_shows_coach_and_computed_points(app, conn):
    text = app.get(f"/foods/{_id(conn, 'Hummus')}").text
    assert "3 tbsp = 1F" in text
    assert "coach says 1F, macros say ½F" in text
    assert "USDA FDC 174289" in text
    assert "Mark checked" not in text  # coach foods from USDA come in checked


def test_food_names_link_to_their_page(app, conn):
    assert f'href="/foods/{_id(conn, "Hummus")}"' in app.get("/foods", params={"q": "hummus"}).text


def test_mark_checked_sets_today(app, conn):
    food_id = _id(conn, "Grassfed Beef Stroganoff")
    assert "Mark checked" in app.get(f"/foods/{food_id}").text
    response = app.post(f"/foods/{food_id}/check", follow_redirects=False)
    assert response.status_code == 303
    row = conn.execute(
        "SELECT verified, verified_on FROM foods WHERE id = ?", (food_id,)
    ).fetchone()
    assert tuple(row) == (1, date.today().isoformat())


def test_edit_clears_checked(conn):
    food_id = _id(conn, "Hummus")
    update_food(conn, food_id, _edit(conn, food_id, fat_g=20.0))
    row = conn.execute(
        "SELECT verified, verified_on, fat_g_100g FROM foods WHERE id = ?", (food_id,)
    ).fetchone()
    assert tuple(row) == (0, None, 20.0)


def test_edit_never_touches_coach_portion(conn):
    food_id = _id(conn, "Chicken breast, raw")
    coach = [p for p in portions(conn, food_id) if p.source == "coach"]
    update_food(conn, food_id, _edit(conn, food_id, manual_portion=(5, "oz")))
    assert [p for p in portions(conn, food_id) if p.source == "coach"] == coach
    assert preferred_portion(conn, food_id).source == "manual"
    assert preferred_portion(conn, food_id).qty == 5


def test_edit_can_remove_the_manual_portion(conn):
    food_id = _id(conn, "Chicken breast, raw")
    update_food(conn, food_id, _edit(conn, food_id, manual_portion=(5, "oz")))
    update_food(conn, food_id, _edit(conn, food_id, manual_portion=None))
    assert preferred_portion(conn, food_id).source == "coach"


def test_edit_refuses_removing_a_unit_in_use(conn):
    food_id = _id(conn, "Hummus")
    with pytest.raises(LabelInputError) as caught:
        update_food(conn, food_id, _edit(conn, food_id, units={"cup": 246.0}))
    assert "tbsp" in caught.value.errors["units"]
    assert conn.execute(
        "SELECT count(*) AS n FROM food_units WHERE food_id = ? AND unit = 'tbsp'", (food_id,)
    ).fetchone()["n"] == 1


def test_edit_validates_numbers(conn):
    food_id = _id(conn, "Hummus")
    with pytest.raises(LabelInputError) as caught:
        update_food(conn, food_id, _edit(conn, food_id, fiber_g=99.0))
    assert "fiber_g" in caught.value.errors


def test_edit_via_the_page(app, conn):
    food_id = _id(conn, "Hummus")
    form = app.get(f"/foods/{food_id}/edit").text
    assert 'name="units"' in form
    response = app.post(
        f"/foods/{food_id}/edit",
        data={
            "name": "Hummus", "brand": "", "kcal": "237", "fat_g": "17.82", "carb_g": "15",
            "fiber_g": "5.5", "sugar_alcohol_g": "", "protein_g": "7.78", "counts_as": "fat",
            "free_role": "", "units": "tbsp = 15\ncup = 246", "manual_qty": "6",
            "manual_unit": "tbsp",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert preferred_portion(conn, food_id).qty == 6


def test_edit_page_keeps_input_on_error(app, conn):
    food_id = _id(conn, "Hummus")
    response = app.post(
        f"/foods/{food_id}/edit",
        data={
            "name": "Hummus", "brand": "", "kcal": "237", "fat_g": "lots", "carb_g": "15",
            "fiber_g": "5.5", "sugar_alcohol_g": "", "protein_g": "7.78", "counts_as": "fat",
            "free_role": "", "units": "tbsp = 15\ncup = 246", "manual_qty": "", "manual_unit": "",
        },
    )
    assert response.status_code == 422
    assert 'value="lots"' in response.text


def test_recipe_is_read_only(app, conn):
    chicken = _id(conn, "Chicken breast, raw")
    recipe = create_recipe(
        conn, name="Chicken bowl", role="protein", servings=1,
        components=[{"food_id": chicken, "qty": 100, "unit": "g"}],
    )
    page = app.get(f"/foods/{recipe}").text
    assert "Chicken bowl" in page
    assert f'href="/foods/{recipe}/edit"' not in page
    assert app.post(f"/foods/{recipe}/edit", data={}).status_code == 409


def test_unknown_food_is_404(app):
    assert app.get("/foods/999999").status_code == 404


def test_foods_search_still_routes(app):
    # /foods/{id} must not swallow /foods/search or /foods/new.
    assert app.get("/foods/new").status_code == 200


def test_mark_checked_library(conn):
    food_id = _id(conn, "Grassfed Beef Stroganoff")
    mark_checked(conn, food_id)
    assert food_detail(conn, food_id).summary.verified is True
