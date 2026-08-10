"""USDA FoodData Central client.

Foundation and SR Legacy entries report nutrients per 100 g, which is the
unit yolk stores natively. Branded entries report per serving and are not
handled here.
"""

from __future__ import annotations

import os
import sqlite3

import httpx
from dotenv import load_dotenv

from yolk.foods import create_item
from yolk.macros import Macros
from yolk.sources.cache import cached_json

BASE_URL = "https://api.nal.usda.gov/fdc/v1"

# FoodData Central nutrient IDs. Anything not listed here is ignored.
NUTRIENT_KCAL = 1008
NUTRIENT_PROTEIN = 1003
NUTRIENT_FAT = 1004
NUTRIENT_CARB = 1005
NUTRIENT_FIBER = 1079


def _api_key() -> str:
    load_dotenv()
    key = os.environ.get("USDA_API_KEY")
    if not key:
        raise RuntimeError(
            "USDA_API_KEY is not set. Add it to .env; get a free key at "
            "https://api.data.gov/signup"
        )
    return key


def search_foods(
    query: str,
    *,
    page_size: int = 10,
    data_types: tuple[str, ...] = ("Foundation", "SR Legacy"),
) -> list[dict]:
    """Search FoodData Central. Returns the raw `foods` list."""
    key = f"search:{query}:{page_size}:{','.join(data_types)}"

    def fetch():
        response = httpx.get(
            f"{BASE_URL}/foods/search",
            params={
                "query": query,
                "pageSize": page_size,
                "dataType": ",".join(data_types),
                "api_key": _api_key(),
            },
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json()

    return cached_json("usda", key, fetch).get("foods", [])


def get_food(fdc_id: int) -> dict:
    """Fetch one food by FDC id."""

    def fetch():
        response = httpx.get(
            f"{BASE_URL}/food/{fdc_id}",
            params={"api_key": _api_key()},
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json()

    return cached_json("usda", f"food:{fdc_id}", fetch)


def parse_macros(payload: dict) -> Macros:
    """Extract per-100 g macros from a FoodData Central food payload."""
    by_id: dict[int, float] = {}
    for entry in payload.get("foodNutrients", []):
        nutrient = entry.get("nutrient") or {}
        nutrient_id = nutrient.get("id")
        if nutrient_id is not None and "amount" in entry:
            by_id[nutrient_id] = entry["amount"]

    if NUTRIENT_KCAL not in by_id:
        raise ValueError(
            f"No energy (nutrient {NUTRIENT_KCAL}) in FDC payload for "
            f"{payload.get('description', 'unknown food')!r}. Refusing to import a "
            f"food without calories."
        )

    return Macros(
        kcal=by_id[NUTRIENT_KCAL],
        protein_g=by_id.get(NUTRIENT_PROTEIN, 0.0),
        fat_g=by_id.get(NUTRIENT_FAT, 0.0),
        carb_g=by_id.get(NUTRIENT_CARB, 0.0),
        fiber_g=by_id.get(NUTRIENT_FIBER, 0.0),
    )


def import_food(
    conn: sqlite3.Connection,
    fdc_id: int,
    *,
    role: str,
    units: dict[str, float] | None = None,
) -> int:
    """Fetch a food from FDC and insert it as an item.

    Fetch and parse both happen before any write, so a failure leaves no
    partial row behind.
    """
    payload = get_food(fdc_id)
    macros = parse_macros(payload)
    return create_item(
        conn,
        name=payload["description"],
        role=role,
        macros=macros,
        source="usda",
        source_ref=str(fdc_id),
        verified=False,
        units=units,
    )
