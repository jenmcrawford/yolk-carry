import re

CREPINI = {
    "name": "Crepini", "brand": "Crepini", "serving_g": "116", "kcal": "240",
    "fat_g": "4", "carb_g": "25", "fiber_g": "1", "sugar_alcohol_g": "",
    "protein_g": "20", "counts_as": "auto", "free_role": "", "unit": "pancake",
    "unit_qty": "4", "notes": "",
}

FIELDS = (
    "name", "brand", "serving_g", "kcal", "fat_g", "carb_g", "fiber_g",
    "sugar_alcohol_g", "protein_g", "counts_as", "free_role", "unit", "unit_qty", "notes",
)


def test_foods_page_links_to_new_food(client):
    assert 'href="/foods/new"' in client.get("/foods").text


def test_new_food_form_renders(client):
    text = client.get("/foods/new").text
    for field in FIELDS:
        assert f'name="{field}"' in text, field


def test_preview_shows_points(client):
    response = client.post("/foods/new/preview", data=CREPINI)
    assert response.status_code == 200
    assert "1C + ¾P + ¼F" in response.text
    assert "4 pancake (116 g)" in response.text


def test_preview_with_errors_shows_them(client):
    response = client.post("/foods/new/preview", data={**CREPINI, "serving_g": "0"})
    assert response.status_code == 200
    assert "more than 0 g" in response.text


def test_save_redirects_to_food_page(client):
    response = client.post("/foods/new", data=CREPINI, follow_redirects=False)
    assert response.status_code == 303
    assert re.fullmatch(r"/foods/\d+", response.headers["location"])
    listing = client.get("/foods", params={"q": "crepini"}).text
    assert "Crepini" in listing
    assert "unchecked" in listing


def test_duplicate_name_keeps_input(client):
    client.post("/foods/new", data=CREPINI, follow_redirects=False)
    response = client.post("/foods/new", data=CREPINI)
    assert response.status_code == 422
    assert 'value="240"' in response.text
    assert 'value="Crepini"' in response.text
    field = response.text.split('id="field-name"', 1)[1].split("</div>", 1)[0]
    assert "already a food" in field


def test_blank_numbers_are_errors_not_500(client):
    response = client.post("/foods/new", data={**CREPINI, "fat_g": ""})
    assert response.status_code == 422
    field = response.text.split('id="field-fat_g"', 1)[1].split("</div>", 1)[0]
    assert "required" in field


def test_words_in_numbers_are_errors(client):
    response = client.post("/foods/new", data={**CREPINI, "fat_g": "4g"})
    assert response.status_code == 422
    field = response.text.split('id="field-fat_g"', 1)[1].split("</div>", 1)[0]
    assert "number" in field
    assert 'value="4g"' in response.text


def test_free_food_needs_its_kind(client):
    response = client.post("/foods/new", data={**CREPINI, "counts_as": "free"})
    assert response.status_code == 422
    assert "veg, a sauce, or a beverage" in response.text


SEARCH_HIT = {
    "fdcId": 171077,
    "description": "Chicken, broiler or fryers, breast, skinless, boneless, meat only, raw",
    "foodNutrients": [
        {"nutrientId": 1008, "value": 120.0},
        {"nutrientId": 1003, "value": 22.5},
        {"nutrientId": 1004, "value": 2.62},
        {"nutrientId": 1005, "value": 0.0},
    ],
}


def _fake_usda(monkeypatch, search=None):
    from test_usda import SAMPLE_PAYLOAD
    from yolk.sources import usda

    monkeypatch.setattr(usda, "search_foods", search or (lambda q, page_size=10: [SEARCH_HIT]))
    monkeypatch.setattr(usda, "get_food", lambda fdc_id: SAMPLE_PAYLOAD)


def test_new_food_page_has_usda_search(client):
    assert 'hx-get="/foods/new/usda"' in client.get("/foods/new").text


def test_usda_search_lists_points_per_100g(client, monkeypatch):
    _fake_usda(monkeypatch)
    text = client.get("/foods/new/usda", params={"q": "chicken"}).text
    assert "Chicken, broiler or fryers, breast" in text
    assert "1P + ¼F" in text
    assert 'name="fdc_id" value="171077"' in text


def test_usda_add_sets_class_and_role(client, seeded, monkeypatch):
    from yolk.db.connection import connect

    _fake_usda(monkeypatch)
    response = client.post(
        "/foods/new/usda", data={"fdc_id": "171077", "counts_as": "protein", "free_role": ""},
        follow_redirects=False,
    )
    assert response.status_code == 303
    food_id = int(response.headers["location"].rsplit("/", 1)[1])
    conn = connect(seeded[0])
    row = conn.execute(
        "SELECT role, point_class, source, verified FROM foods WHERE id = ?", (food_id,)
    ).fetchone()
    conn.close()
    assert tuple(row) == ("protein", "protein", "usda", 0)


def test_usda_add_free_without_kind_says_so(client, monkeypatch):
    _fake_usda(monkeypatch)
    response = client.post(
        "/foods/new/usda", data={"fdc_id": "171077", "counts_as": "free", "free_role": ""}
    )
    assert response.status_code == 422
    assert "veg, a sauce, or a beverage" in response.text


def test_missing_key_shows_plain_message(client, monkeypatch):
    def no_key(q, page_size=10):
        raise RuntimeError("USDA_API_KEY is not set. Add it to .env; get a free key at "
                           "https://api.data.gov/signup")

    _fake_usda(monkeypatch, search=no_key)
    response = client.get("/foods/new/usda", params={"q": "chicken"})
    assert response.status_code == 200
    assert ".env" in response.text
    assert "Traceback" not in response.text


def test_blank_usda_query_lists_nothing(client, monkeypatch):
    def must_not_search(q, page_size=10):
        raise AssertionError("searched with a blank query")

    _fake_usda(monkeypatch, search=must_not_search)
    assert client.get("/foods/new/usda", params={"q": "  "}).status_code == 200
