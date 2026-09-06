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
    """Sodium is present in the payload but Macros has no field for it, so
    there is nowhere for it to land. This asserts exact field-by-field
    equality against the mapped nutrients, which would catch a nutrient-ID
    cross-mapping (e.g. sodium's amount landing in fat_g)."""
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


# --- foodPortions import ---------------------------------------------------

# Modelled on the live shape of SR Legacy 170000 (Onions, raw). `amount` is
# the count the gramWeight describes, which is why 10 rings weigh 60 g.
PORTION_PAYLOAD = {
    "fdcId": 170000,
    "description": "Onions, raw",
    "dataType": "SR Legacy",
    "foodNutrients": [
        {"nutrient": {"id": 1008}, "amount": 40.0},
        {"nutrient": {"id": 1003}, "amount": 1.1},
        {"nutrient": {"id": 1004}, "amount": 0.1},
        {"nutrient": {"id": 1005}, "amount": 9.34},
    ],
    "foodPortions": [
        {"amount": 1.0, "modifier": "medium (2-1/2\" dia)",
         "measureUnit": {"name": "undetermined"}, "gramWeight": 110.0},
        {"amount": 10.0, "modifier": "rings",
         "measureUnit": {"name": "undetermined"}, "gramWeight": 60.0},
        {"amount": 1.0, "modifier": "cup, chopped",
         "measureUnit": {"name": "undetermined"}, "gramWeight": 160.0},
    ],
}


def test_import_food_records_usda_portions_as_units(db, monkeypatch):
    monkeypatch.setattr(usda, "get_food", lambda fdc_id: PORTION_PAYLOAD)
    food_id = usda.import_food(db, 170000, role="veg")
    row = db.execute(
        "SELECT grams FROM food_units WHERE food_id = ? AND unit = ?",
        (food_id, 'medium (2-1/2" dia)'),
    ).fetchone()
    assert row is not None, "USDA portion was not imported as a food_unit"
    assert row["grams"] == pytest.approx(110.0)


def test_portion_gram_weight_is_divided_by_amount(db, monkeypatch):
    """`amount=10, gramWeight=60` means ten rings weigh 60 g, so one ring is
    6 g. Storing 60 would make every quantity ten times too heavy — the same
    read-the-wrong-number failure the Cronometer column mapping guards against."""
    monkeypatch.setattr(usda, "get_food", lambda fdc_id: PORTION_PAYLOAD)
    food_id = usda.import_food(db, 170000, role="veg")
    row = db.execute(
        "SELECT grams FROM food_units WHERE food_id = ? AND unit = 'rings'",
        (food_id,),
    ).fetchone()
    assert row["grams"] == pytest.approx(6.0)


def test_racc_portion_is_not_imported(db, monkeypatch):
    """Foundation foods often carry a single RACC row — a regulatory label
    serving, not a cooking unit. Importing it as a unit named 'RACC' would
    put a meaningless 85 g conversion on the food."""
    payload = dict(PORTION_PAYLOAD)
    payload["foodPortions"] = [
        {"amount": 1.0, "modifier": None,
         "measureUnit": {"name": "RACC"}, "gramWeight": 85.0}
    ]
    monkeypatch.setattr(usda, "get_food", lambda fdc_id: payload)
    food_id = usda.import_food(db, 170000, role="veg")
    count = db.execute(
        "SELECT COUNT(*) AS n FROM food_units WHERE food_id = ?", (food_id,)
    ).fetchone()["n"]
    assert count == 0


def test_undetermined_measure_unit_without_modifier_is_skipped(db, monkeypatch):
    """'undetermined' is a placeholder, not a unit name."""
    payload = dict(PORTION_PAYLOAD)
    payload["foodPortions"] = [
        {"amount": 1.0, "modifier": None,
         "measureUnit": {"name": "undetermined"}, "gramWeight": 50.0}
    ]
    monkeypatch.setattr(usda, "get_food", lambda fdc_id: payload)
    food_id = usda.import_food(db, 170000, role="veg")
    count = db.execute(
        "SELECT COUNT(*) AS n FROM food_units WHERE food_id = ?", (food_id,)
    ).fetchone()["n"]
    assert count == 0


def test_duplicate_portion_modifiers_do_not_break_the_import(db, monkeypatch):
    """food_units is UNIQUE(food_id, unit). Two portions sharing a modifier
    must not abort the whole import via that constraint."""
    payload = dict(PORTION_PAYLOAD)
    payload["foodPortions"] = [
        {"amount": 1.0, "modifier": "medium", "measureUnit": {"name": "undetermined"},
         "gramWeight": 110.0},
        {"amount": 1.0, "modifier": "medium", "measureUnit": {"name": "undetermined"},
         "gramWeight": 125.0},
    ]
    monkeypatch.setattr(usda, "get_food", lambda fdc_id: payload)
    food_id = usda.import_food(db, 170000, role="veg")
    rows = db.execute(
        "SELECT grams FROM food_units WHERE food_id = ? AND unit = 'medium'", (food_id,)
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["grams"] == pytest.approx(110.0)


def test_zero_amount_portion_is_skipped(db, monkeypatch):
    """A zero amount cannot be divided by, and grams must be > 0."""
    payload = dict(PORTION_PAYLOAD)
    payload["foodPortions"] = [
        {"amount": 0.0, "modifier": "sprig", "measureUnit": {"name": "undetermined"},
         "gramWeight": 5.0}
    ]
    monkeypatch.setattr(usda, "get_food", lambda fdc_id: payload)
    food_id = usda.import_food(db, 170000, role="veg")
    count = db.execute(
        "SELECT COUNT(*) AS n FROM food_units WHERE food_id = ?", (food_id,)
    ).fetchone()["n"]
    assert count == 0


def test_explicit_units_win_over_usda_portions(db, monkeypatch):
    """A caller who passes a weight has checked it. USDA's average must not
    silently overwrite it."""
    monkeypatch.setattr(usda, "get_food", lambda fdc_id: PORTION_PAYLOAD)
    food_id = usda.import_food(
        db, 170000, role="veg", units={'medium (2-1/2" dia)': 95.0}
    )
    row = db.execute(
        "SELECT grams FROM food_units WHERE food_id = ? AND unit = ?",
        (food_id, 'medium (2-1/2" dia)'),
    ).fetchone()
    assert row["grams"] == pytest.approx(95.0)


def test_payload_without_portions_still_imports(db, monkeypatch):
    """SAMPLE_PAYLOAD has no foodPortions key at all."""
    monkeypatch.setattr(usda, "get_food", lambda fdc_id: SAMPLE_PAYLOAD)
    food_id = usda.import_food(db, 171077, role="protein")
    assert food_id is not None


def test_real_measure_unit_is_kept_in_the_unit_name(db, monkeypatch):
    """FDC's modifier qualifies the measureUnit rather than replacing it.
    Live data for 'Onions, red, raw' is modifier='Edible', measureUnit='Onion'
    — naming the unit 'Edible' throws away the only part anyone would type."""
    payload = dict(PORTION_PAYLOAD)
    payload["foodPortions"] = [
        {"amount": 1.0, "modifier": "Edible",
         "measureUnit": {"name": "Onion"}, "gramWeight": 197.0}
    ]
    monkeypatch.setattr(usda, "get_food", lambda fdc_id: payload)
    food_id = usda.import_food(db, 170000, role="veg")
    units = dict(
        db.execute(
            "SELECT unit, grams FROM food_units WHERE food_id = ?", (food_id,)
        ).fetchall()
    )
    assert "Edible" not in units
    assert any(u.startswith("Onion") for u in units), units
    assert next(iter(units.values())) == pytest.approx(197.0)


def test_measure_unit_and_modifier_stay_distinct_per_preparation(db, monkeypatch):
    """Foundation splits what SR Legacy writes as one string: measureUnit
    'cup' plus modifier 'chopped'. Collapsing to 'cup' alone would make two
    preparations with different weights collide on one unit name, and
    setdefault would silently keep whichever came first."""
    payload = dict(PORTION_PAYLOAD)
    payload["foodPortions"] = [
        {"amount": 1.0, "modifier": "chopped",
         "measureUnit": {"name": "cup"}, "gramWeight": 160.0},
        {"amount": 1.0, "modifier": "sliced",
         "measureUnit": {"name": "cup"}, "gramWeight": 115.0},
    ]
    monkeypatch.setattr(usda, "get_food", lambda fdc_id: payload)
    food_id = usda.import_food(db, 170000, role="veg")
    units = dict(
        db.execute(
            "SELECT unit, grams FROM food_units WHERE food_id = ?", (food_id,)
        ).fetchall()
    )
    assert len(units) == 2, f"preparations collapsed into one unit: {units}"
    assert set(units.values()) == {160.0, 115.0}


def test_placeholder_measure_unit_leaves_the_modifier_alone(db, monkeypatch):
    """SR Legacy's 'cup, chopped' already reads correctly; an 'undetermined'
    measureUnit must not be prepended to it."""
    monkeypatch.setattr(usda, "get_food", lambda fdc_id: PORTION_PAYLOAD)
    food_id = usda.import_food(db, 170000, role="veg")
    row = db.execute(
        "SELECT grams FROM food_units WHERE food_id = ? AND unit = 'cup, chopped'",
        (food_id,),
    ).fetchone()
    assert row is not None
    assert row["grams"] == pytest.approx(160.0)


def test_racc_measure_unit_still_yields_to_a_real_modifier(db, monkeypatch):
    """RACC is not a unit, but a modifier alongside it may still be one."""
    payload = dict(PORTION_PAYLOAD)
    payload["foodPortions"] = [
        {"amount": 1.0, "modifier": "bar",
         "measureUnit": {"name": "RACC"}, "gramWeight": 40.0}
    ]
    monkeypatch.setattr(usda, "get_food", lambda fdc_id: payload)
    food_id = usda.import_food(db, 170000, role="veg")
    row = db.execute(
        "SELECT grams FROM food_units WHERE food_id = ? AND unit = 'bar'", (food_id,)
    ).fetchone()
    assert row is not None
    assert row["grams"] == pytest.approx(40.0)
