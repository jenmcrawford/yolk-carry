from yolk.db.connection import connect
from yolk.foods import create_item
from yolk.macros import Macros


def _add_food(path, **kwargs):
    conn = connect(path)
    create_item(conn, **kwargs)
    conn.close()


def test_the_foods_page_lists_seeded_foods(client):
    response = client.get("/foods")
    assert response.status_code == 200
    assert "Grilled or baked chicken breast" in response.text
    assert "Pork Rinds" in response.text


def test_a_query_narrows_the_list(client):
    response = client.get("/foods", params={"q": "chicken"})
    assert "Grilled or baked chicken breast" in response.text
    assert "Pork Rinds" not in response.text
    assert 'value="chicken"' in response.text


def test_a_food_shows_its_units_in_grams(client):
    response = client.get("/foods", params={"q": "buff chick"})
    assert "packet = 22 g" in response.text


def test_no_match_says_so(client):
    response = client.get("/foods", params={"q": "zzzz"})
    assert response.status_code == 200
    assert "No foods match" in response.text
    assert "zzzz" in response.text


def test_the_header_links_to_foods(client):
    assert 'href="/foods"' in client.get("/plans").text


def test_an_unverified_food_carries_a_badge(client, seeded):
    assert "unchecked" not in client.get("/foods").text
    _add_food(
        seeded[0], name="Cottage cheese", role="protein",
        macros=Macros(kcal=98, protein_g=11, fat_g=4.3, carb_g=3.4),
    )
    response = client.get("/foods", params={"q": "cottage"})
    assert "unchecked" in response.text


def test_a_recipe_without_macros_says_not_computed(client, seeded):
    conn = connect(seeded[0])
    conn.execute(
        "INSERT INTO foods (kind, name, role, source) "
        "VALUES ('recipe', 'Chili', 'protein', 'computed')"
    )
    conn.commit()
    conn.close()
    response = client.get("/foods", params={"q": "chili"})
    assert "not computed" in response.text


def test_the_header_shows_the_egg_beside_yolk(client):
    text = client.get("/plans").text
    assert '<svg class="egg"' in text
    assert 'aria-hidden="true"' in text
    assert "</svg>yolk</a>" in text


def test_the_egg_shows_on_the_setup_page_too(tmp_path):
    from fastapi.testclient import TestClient

    from yolk.web.app import create_app

    client = TestClient(create_app(tmp_path / "absent.db"), base_url="http://127.0.0.1")
    response = client.get("/plans")
    assert response.status_code == 503
    assert '<svg class="egg"' in response.text
