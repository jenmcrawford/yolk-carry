"""USDA FoodData Central client.

Foundation and SR Legacy entries report nutrients per 100 g, which is the
unit yolk stores natively. Branded entries report per serving and are not
handled here.
"""

from __future__ import annotations

import os

import httpx
from dotenv import load_dotenv

from yolk.db import Connection
from yolk.errors import SourceRequestError
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

# measureUnit names that are not units anyone cooks with: 'undetermined' is
# FDC's placeholder, and RACC is the regulatory Reference Amount Customarily
# Consumed, a label serving.
PLACEHOLDER_MEASURE_UNITS = frozenset({"undetermined", "RACC"})


def _api_key() -> str:
    load_dotenv()
    key = os.environ.get("USDA_API_KEY")
    if not key:
        raise RuntimeError(
            "USDA_API_KEY is not set. Add it to .env; get a free key at "
            "https://api.data.gov/signup"
        )
    return key


def _fetch_json(url: str, params: dict) -> dict:
    """GET `url` with `params` and return the parsed JSON body.

    FDC only supports the API key as a query parameter, so it ends up in
    the request URL — and `httpx.HTTPError`'s message embeds the full URL,
    query string included. A bad key, an api.data.gov rate limit (429), or
    a transient 5xx would otherwise put the raw key into a traceback, a CI
    log, or a pasted bug report. Catch it here, redact the key value (not
    the whole URL — the endpoint and status are what make the error
    diagnosable), and re-raise as `SourceRequestError`.

    `from None` on the re-raise is deliberate: `from exc` would print the
    original exception's message (key included) in the traceback anyway.
    """
    key = params.get("api_key", "")
    try:
        response = httpx.get(url, params=params, timeout=30.0)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        message = str(exc)
        if key:
            message = message.replace(key, "***")
        raise SourceRequestError(message) from None
    return response.json()


def search_foods(
    query: str,
    *,
    page_size: int = 10,
    data_types: tuple[str, ...] = ("Foundation", "SR Legacy"),
) -> list[dict]:
    """Search FoodData Central. Returns the raw `foods` list."""
    key = f"search:{query}:{page_size}:{','.join(data_types)}"

    def fetch():
        return _fetch_json(
            f"{BASE_URL}/foods/search",
            {
                "query": query,
                "pageSize": page_size,
                "dataType": ",".join(data_types),
                "api_key": _api_key(),
            },
        )

    return cached_json("usda", key, fetch).get("foods", [])


def get_food(fdc_id: int) -> dict:
    """Fetch one food by FDC id."""

    def fetch():
        return _fetch_json(f"{BASE_URL}/food/{fdc_id}", {"api_key": _api_key()})

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


def parse_portions(payload: dict) -> dict[str, float]:
    """Gram weights for a food's display units, from FDC `foodPortions`.

    This is where "1 medium onion" and "1 clove garlic" come from, and it is
    the main defence against UnknownUnitError on whole foods.

    Two traps, both of which produce plausible wrong numbers rather than
    errors. First, `gramWeight` describes `amount` of the portion, not one of
    it: ten onion rings weighing 60 g is 6 g per ring, so the weight must be
    divided by the amount. Second, `measureUnit` is frequently the placeholder
    'undetermined', or 'RACC' — a regulatory label serving rather than a
    cooking unit, and the only portion many Foundation foods carry. Neither is
    a unit anyone measures with.

    Note that portion coverage is better on SR Legacy entries than on the
    newer Foundation ones, which is the opposite of their nutrient quality.
    """
    portions: dict[str, float] = {}
    for portion in payload.get("foodPortions") or []:
        measure = ((portion.get("measureUnit") or {}).get("name") or "").strip()
        if measure in PLACEHOLDER_MEASURE_UNITS:
            measure = ""
        modifier = (portion.get("modifier") or "").strip()

        # The modifier qualifies the measure unit rather than replacing it.
        # Dropping either one loses information: 'Onion' + 'Edible' without the
        # measure becomes the unusable unit 'Edible', while 'cup' + 'chopped'
        # and 'cup' + 'sliced' without the modifier collide on 'cup' at two
        # different weights. Joining them also reproduces SR Legacy's own
        # spelling, where the same portion arrives as one 'cup, chopped'
        # string with no measure unit at all.
        unit = ", ".join(part for part in (measure, modifier) if part)
        if not unit:
            continue

        amount = portion.get("amount")
        gram_weight = portion.get("gramWeight")
        if not amount or amount <= 0 or not gram_weight or gram_weight <= 0:
            continue

        # food_units is UNIQUE (food_id, unit); a repeated modifier must not
        # abort the import. First wins.
        portions.setdefault(unit, gram_weight / amount)
    return portions


def import_food(
    conn: Connection,
    fdc_id: int,
    *,
    role: str,
    units: dict[str, float] | None = None,
) -> int:
    """Fetch a food from FDC and insert it as an item.

    Unit conversions come from the payload's own `foodPortions`. Anything in
    `units` overrides them, since a caller who passes a weight has checked it
    and USDA's figure is an average.

    Fetch and parse both happen before any write, so a failure leaves no
    partial row behind.
    """
    payload = get_food(fdc_id)
    macros = parse_macros(payload)
    resolved_units = {**parse_portions(payload), **(units or {})}
    return create_item(
        conn,
        name=payload["description"],
        role=role,
        macros=macros,
        source="usda",
        source_ref=str(fdc_id),
        verified=False,
        units=resolved_units,
    )
