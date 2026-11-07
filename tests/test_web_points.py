import pytest
from fastapi.testclient import TestClient

from yolk.db.connection import connect, create_schema
from yolk.seed import seed_keto_plan_a, seed_point_system
from yolk.web.app import create_app


@pytest.fixture
def library(tmp_path):
    path = tmp_path / "yolk.db"
    conn = connect(path)
    create_schema(conn)
    keto_plan, _ = seed_keto_plan_a(conn)
    report = seed_point_system(conn)
    conn.close()
    return path, keto_plan, report


@pytest.fixture
def app(library):
    return TestClient(
        create_app(library[0]),
        base_url="http://127.0.0.1",
        headers={"origin": "http://127.0.0.1"},
    )


def _food_id(path, name):
    conn = connect(path)
    try:
        return conn.execute("SELECT id FROM foods WHERE name = ?", (name,)).fetchone()["id"]
    finally:
        conn.close()


def _new_points_plan(app, library):
    path, _, report = library
    response = app.post(
        "/plans", data={"name": "Recovery day", "profile_id": report.profile_id},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return int(response.headers["location"].rsplit("/", 1)[1])


def _add(app, library, draft, slot_no, name):
    response = app.post(
        f"/drafts/{draft}/entries",
        data={"slot_no": slot_no, "food_id": _food_id(library[0], name)},
        follow_redirects=False,
    )
    assert response.status_code in (200, 303)


def test_food_list_shows_one_point_and_coach_portion(app):
    text = app.get("/foods", params={"q": "chicken breast, raw"}).text
    assert "→ 1P" in text
    assert "4 oz = 1P" in text


def test_flagged_food_shows_a_flag(app):
    text = app.get("/foods", params={"q": "hummus"}).text
    assert "coach says 1F, macros say ½F" in text


def test_points_plan_shows_allotments_on_empty_meals(app, library):
    draft = _new_points_plan(app, library)
    text = app.get(f"/drafts/{draft}").text
    assert "Target 1F + 1C + 1P" in text
    assert "Target 1F + 1C + 1P + 1V" in text


def test_adding_a_coach_food_uses_its_portion(app, library):
    draft = _new_points_plan(app, library)
    _add(app, library, draft, 1, "Chicken breast, raw")
    conn = connect(library[0])
    entry = conn.execute(
        "SELECT qty, unit FROM day_plan_entries WHERE day_plan_id = ?", (draft,)
    ).fetchone()
    conn.close()
    assert (entry["qty"], entry["unit"]) == (4, "oz")


def test_entry_rows_and_day_show_points(app, library):
    draft = _new_points_plan(app, library)
    _add(app, library, draft, 1, "Chicken breast, raw")
    text = app.get(f"/drafts/{draft}").text
    # 4 oz raw breast carries ~3 g fat, which rounds to a quarter point.
    assert '<td class="num points">1P + ¼F</td>' in text
    assert "6F + 6P + 3C + 1V" in text
    assert "Label calories" in text


def test_meal_hint_appears(app, library):
    draft = _new_points_plan(app, library)
    _add(app, library, draft, 1, "Chicken breast, raw")
    _add(app, library, draft, 1, "Coconut oil")
    assert "1C short" in app.get(f"/drafts/{draft}").text


def test_keto_plan_has_no_allotments(app, library):
    text = app.get(f"/plans/{library[1]}").text
    assert "Target 1" not in text
    assert "Label calories" not in text
