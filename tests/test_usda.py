import httpx
import pytest

from yolk.errors import SourceRequestError
from yolk.macros import Macros
from yolk.sources import usda

# Shape of a FoodData Central /food/{id} response, trimmed to what we read.
SAMPLE_PAYLOAD = {
    "fdcId": 171077,
    "description": "Chicken, broilers or fryers, breast, meat only, raw",
    "dataType": "SR Legacy",
    "foodNutrients": [
        {"nutrient": {"id": 1008, "name": "Energy", "unitName": "KCAL"}, "amount": 120.0},
        {"nutrient": {"id": 1003, "name": "Protein", "unitName": "G"}, "amount": 22.5},
        {"nutrient": {"id": 1004, "name": "Total lipid (fat)", "unitName": "G"}, "amount": 2.62},
        {"nutrient": {"id": 1005, "name": "Carbohydrate", "unitName": "G"}, "amount": 0.0},
        {"nutrient": {"id": 1079, "name": "Fiber", "unitName": "G"}, "amount": 0.0},
        {"nutrient": {"id": 1093, "name": "Sodium", "unitName": "MG"}, "amount": 45.0},
    ],
}


def test_parse_macros_maps_nutrient_ids():
    m = usda.parse_macros(SAMPLE_PAYLOAD)
    assert m.kcal == pytest.approx(120.0)
    assert m.protein_g == pytest.approx(22.5)
    assert m.fat_g == pytest.approx(2.62)
    assert m.carb_g == pytest.approx(0.0)
    assert m.fiber_g == pytest.approx(0.0)


def test_parse_macros_ignores_unmapped_nutrients():
    """Sodium is present in the payload and must not land anywhere."""
    m = usda.parse_macros(SAMPLE_PAYLOAD)
    assert m == Macros(kcal=120.0, protein_g=22.5, fat_g=2.62, carb_g=0.0, fiber_g=0.0)


def test_parse_macros_missing_energy_raises():
    payload = {"fdcId": 1, "description": "Mystery", "foodNutrients": []}
    with pytest.raises(ValueError) as exc:
        usda.parse_macros(payload)
    assert "energy" in str(exc.value).lower()


def test_import_food_creates_item_with_provenance(db, monkeypatch):
    monkeypatch.setattr(usda, "get_food", lambda fdc_id: SAMPLE_PAYLOAD)
    food_id = usda.import_food(db, 171077, role="protein")
    row = db.execute(
        "SELECT name, source, source_ref, verified, kcal_100g FROM foods WHERE id = ?",
        (food_id,),
    ).fetchone()
    assert row["source"] == "usda"
    assert row["source_ref"] == "171077"
    assert row["verified"] == 0
    assert row["kcal_100g"] == pytest.approx(120.0)


def test_import_food_attaches_units(db, monkeypatch):
    monkeypatch.setattr(usda, "get_food", lambda fdc_id: SAMPLE_PAYLOAD)
    food_id = usda.import_food(db, 171077, role="protein", units={"breast": 174.0})
    row = db.execute(
        "SELECT grams FROM food_units WHERE food_id = ? AND unit = 'breast'", (food_id,)
    ).fetchone()
    assert row["grams"] == 174.0


def test_failed_fetch_writes_nothing(db, monkeypatch):
    def boom(fdc_id):
        raise RuntimeError("network down")

    monkeypatch.setattr(usda, "get_food", boom)
    with pytest.raises(RuntimeError):
        usda.import_food(db, 171077, role="protein")
    count = db.execute("SELECT COUNT(*) AS n FROM foods").fetchone()["n"]
    assert count == 0


def test_failed_parse_writes_nothing(db, monkeypatch):
    """parse_macros can also raise (missing energy) — that must be caught
    before create_item runs too, not just a fetch failure."""
    payload = {"fdcId": 1, "description": "Mystery", "foodNutrients": []}
    monkeypatch.setattr(usda, "get_food", lambda fdc_id: payload)
    with pytest.raises(ValueError):
        usda.import_food(db, 1, role="protein")
    count = db.execute("SELECT COUNT(*) AS n FROM foods").fetchone()["n"]
    assert count == 0


def test_fetch_json_redacts_api_key_on_http_error(monkeypatch):
    """An HTTP error's message embeds the full request URL, api_key query
    param included. The redaction must strip the key value, not just
    happen to omit it, so build a real httpx error and check its text."""
    fake_key = "SECRET123"
    request = httpx.Request(
        "GET", "https://api.nal.usda.gov/fdc/v1/food/1", params={"api_key": fake_key}
    )
    response = httpx.Response(403, request=request)
    monkeypatch.setattr(usda.httpx, "get", lambda *a, **k: response)

    with pytest.raises(SourceRequestError) as exc:
        usda._fetch_json(
            "https://api.nal.usda.gov/fdc/v1/food/1", {"api_key": fake_key}
        )

    assert fake_key not in str(exc.value)
