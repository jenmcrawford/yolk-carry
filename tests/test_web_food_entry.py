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
