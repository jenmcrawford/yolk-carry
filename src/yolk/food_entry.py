"""Bringing a new food in from its nutrition label.

A label is read per serving, as printed. This module checks the figures,
converts them to the per-100 g macros every food stores, shows the points
before anything is saved, and writes the food, its household unit, and the
label's own portion in one transaction. The web form and the receipt CSV
import both go through it.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from yolk.db import Connection
from yolk.errors import SourceRequestError, YolkError
from yolk.foods import create_item
from yolk.macros import Macros
from yolk.points import (
    PointRules,
    add_portion,
    effective_class,
    format_points,
    format_qty,
    load_rules,
    main_type,
    one_point_from,
    points_for,
)
from yolk.sources import usda

COUNTS_AS = ("auto", "fat", "carb", "protein", "veggie", "free")
FREE_ROLES = ("veg", "sauce", "beverage")

# A label rounds each figure, so macros may add up to a little over the
# serving weight. More than this is a typo, not rounding.
_ROUNDING_ALLOWANCE = 1.05

_ROLE_FOR_CLASS = {"fat": "fat", "carb": "carb", "protein": "protein", "veggie": "veg"}


@dataclass(frozen=True)
class LabelInput:
    name: str
    brand: str
    serving_g: float | None
    kcal: float | None
    fat_g: float | None
    carb_g: float | None
    fiber_g: float | None
    sugar_alcohol_g: float | None
    protein_g: float | None
    counts_as: str = "auto"
    # Only for a free food: whether it is a veg, a sauce, or a beverage.
    free_role: str | None = None
    # A household unit for the serving: "4 pancakes" is ("pancake", 4).
    unit: str | None = None
    unit_qty: float | None = None
    notes: str | None = None


class LabelInputError(YolkError):
    """A label could not be saved. `errors` maps each field to what is wrong."""

    def __init__(self, errors: dict[str, str]) -> None:
        super().__init__("; ".join(f"{field}: {message}" for field, message in errors.items()))
        self.errors = errors


_REQUIRED = (("kcal", "Calories"), ("fat_g", "Fat"), ("carb_g", "Carbs"), ("protein_g", "Protein"))
_OPTIONAL = (("fiber_g", "Fiber"), ("sugar_alcohol_g", "Sugar alcohols"))


def validate(inp: LabelInput) -> dict[str, str]:
    """Every problem with a label, keyed by field. Empty when it can be saved."""
    errors: dict[str, str] = {}
    if not inp.name.strip():
        errors["name"] = "Give the food a name."
    if inp.serving_g is None or inp.serving_g <= 0:
        errors["serving_g"] = "The serving size must be more than 0 g."
    for field, label in _REQUIRED:
        value = getattr(inp, field)
        if value is None:
            errors[field] = f"{label} is required; enter 0 if the label says 0."
        elif value < 0:
            errors[field] = f"{label} cannot be negative."
    for field, label in _OPTIONAL:
        value = getattr(inp, field)
        if value is not None and value < 0:
            errors[field] = f"{label} cannot be negative."

    if "serving_g" not in errors:
        macros = [getattr(inp, f) or 0.0 for f in ("fat_g", "carb_g", "protein_g")]
        if sum(macros) > inp.serving_g * _ROUNDING_ALLOWANCE:
            biggest = max(("fat_g", "carb_g", "protein_g"), key=lambda f: getattr(inp, f) or 0.0)
            errors.setdefault(
                biggest,
                f"Fat, carbs and protein add up to {sum(macros):g} g, more than the "
                f"{inp.serving_g:g} g serving. Check this figure.",
            )
    if inp.carb_g is not None and "fiber_g" not in errors:
        subtracted = (inp.fiber_g or 0.0) + (inp.sugar_alcohol_g or 0.0)
        if subtracted > inp.carb_g:
            errors["fiber_g"] = (
                "Fiber and sugar alcohols are part of the carbs, so together they "
                f"cannot be more than {inp.carb_g:g} g."
            )

    if inp.counts_as not in COUNTS_AS:
        errors["counts_as"] = f"Choose one of: {', '.join(COUNTS_AS)}."
    if inp.counts_as == "free":
        if inp.free_role not in FREE_ROLES:
            errors["free_role"] = "Say whether this free food is a veg, a sauce, or a beverage."
    if inp.unit is not None and inp.unit.strip():
        if inp.unit_qty is None or inp.unit_qty <= 0:
            errors["unit_qty"] = f"How many {inp.unit} are in one serving?"
    return errors


def per_100g(inp: LabelInput) -> Macros:
    """The label's per-serving figures as per-100 g macros. Unknown fiber reads 0
    here; whether it was known is carried separately."""
    factor = 100.0 / inp.serving_g
    return Macros(
        kcal=(inp.kcal or 0.0) * factor,
        fat_g=(inp.fat_g or 0.0) * factor,
        carb_g=(inp.carb_g or 0.0) * factor,
        fiber_g=(inp.fiber_g or 0.0) * factor,
        sugar_alcohol_g=(inp.sugar_alcohol_g or 0.0) * factor,
        protein_g=(inp.protein_g or 0.0) * factor,
    )


def _point_class(counts_as: str) -> str | None:
    return None if counts_as == "auto" else counts_as


def role_for(
    counts_as: str, free_role: str | None, per_100g: Macros, rules: PointRules
) -> str:
    """The food's role, from what it counts as. The form never asks for it."""
    if counts_as == "free":
        return free_role
    return _ROLE_FOR_CLASS[effective_class(_point_class(counts_as), per_100g, rules)]


def _unit(inp: LabelInput) -> tuple[str, float, float]:
    """(unit, grams per unit, units per serving). No unit means 'serving'."""
    if inp.unit is not None and inp.unit.strip():
        return inp.unit.strip(), inp.serving_g / inp.unit_qty, inp.unit_qty
    return "serving", inp.serving_g, 1.0


@dataclass(frozen=True)
class LabelPreview:
    serving_points: str
    serving_text: str
    one_point: str | None
    errors: dict[str, str]


def preview(conn: Connection, inp: LabelInput) -> LabelPreview:
    """What a label counts as, before saving. Never raises on bad input."""
    errors = validate(inp)
    if errors:
        return LabelPreview(serving_points="", serving_text="", one_point=None, errors=errors)
    rules = load_rules(conn)
    m = per_100g(inp)
    cls = effective_class(_point_class(inp.counts_as), m, rules)
    per_100g_points = points_for(m, cls, rules, fiber_known=inp.fiber_g is not None)
    unit, grams_per_unit, count = _unit(inp)
    found = one_point_from(
        per_100g_points, main_type(_point_class(inp.counts_as), per_100g_points),
        [(unit, grams_per_unit)],
    )
    return LabelPreview(
        serving_points=format_points(per_100g_points.scale(inp.serving_g / 100.0)),
        serving_text=f"{format_qty(count)} {unit} ({inp.serving_g:g} g)",
        one_point=None if found is None else found.label,
        errors={},
    )


def create_label_food(
    conn: Connection, inp: LabelInput, *, source: str = "label", commit: bool = True
) -> int:
    """Save a label as an unchecked food, with its unit and its label portion.

    Raises LabelInputError, writing nothing, when the label does not validate
    or a food with the same name and brand already exists.
    """
    errors = validate(inp)
    if errors:
        raise LabelInputError(errors)
    shown = preview(conn, inp)
    rules = load_rules(conn)
    m = per_100g(inp)
    unit, grams_per_unit, count = _unit(inp)
    try:
        food_id = create_item(
            conn,
            name=inp.name.strip(),
            brand=inp.brand.strip(),
            role=role_for(inp.counts_as, inp.free_role, m, rules),
            macros=m,
            fiber_known=inp.fiber_g is not None,
            sugar_alcohol_g_100g=None if inp.sugar_alcohol_g is None else m.sugar_alcohol_g,
            point_class=_point_class(inp.counts_as),
            source=source,
            units={unit: grams_per_unit},
            notes=inp.notes or None,
            commit=False,
        )
        add_portion(
            conn, food_id, source="label", qty=count, unit=unit,
            claimed=shown.serving_points, commit=False,
        )
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        if "UNIQUE" in str(exc) and "foods" in str(exc):
            raise LabelInputError(
                {"name": f"There is already a food called {inp.name.strip()!r}"
                         f"{f' from {inp.brand.strip()}' if inp.brand.strip() else ''}."}
            ) from None
        raise
    except Exception:
        conn.rollback()
        raise
    if commit:
        conn.commit()
    return food_id


# --- From USDA ---------------------------------------------------------------

class UsdaUnavailable(YolkError):
    """USDA could not be asked: no API key, or the request failed."""


_SEARCH_NUTRIENTS = {1003: "protein_g", 1004: "fat_g", 1005: "carb_g", 1079: "fiber_g"}


def _search_macros(hit: dict) -> Macros:
    """Per-100 g macros from a search result, whose nutrients are shaped
    differently from a full food payload's."""
    values = {n.get("nutrientId"): n.get("value") for n in hit.get("foodNutrients", [])}
    kcal = values.get(1008)
    if kcal is None:
        kcal = values.get(2048) or values.get(2047) or 0.0
    return Macros(
        kcal=kcal,
        **{field: values.get(nid) or 0.0 for nid, field in _SEARCH_NUTRIENTS.items()},
    )


@dataclass(frozen=True)
class UsdaChoice:
    fdc_id: int
    description: str
    per_100g: Macros
    # What 100 g counts as, scored automatically, e.g. "1P + ¼F".
    points_100g: str


def usda_search(query: str, rules: PointRules) -> list[UsdaChoice]:
    """USDA foods matching `query`, each with what 100 g counts as."""
    try:
        hits = usda.search_foods(query, page_size=10)
    except (RuntimeError, SourceRequestError) as exc:
        raise UsdaUnavailable(str(exc)) from None
    choices = []
    for hit in hits:
        m = _search_macros(hit)
        choices.append(
            UsdaChoice(
                fdc_id=hit["fdcId"],
                description=hit["description"],
                per_100g=m,
                points_100g=format_points(points_for(m, effective_class(None, m, rules), rules)),
            )
        )
    return choices


def create_usda_food(
    conn: Connection, fdc_id: int, *, counts_as: str, free_role: str | None
) -> int:
    """Import a USDA food as unchecked, scored as `counts_as`.

    Raises LabelInputError, writing nothing, when the choice of class is
    incomplete, and UsdaUnavailable when USDA cannot be reached.
    """
    errors = {}
    if counts_as not in COUNTS_AS:
        errors["counts_as"] = f"Choose one of: {', '.join(COUNTS_AS)}."
    elif counts_as == "free" and free_role not in FREE_ROLES:
        errors["free_role"] = "Say whether this free food is a veg, a sauce, or a beverage."
    if errors:
        raise LabelInputError(errors)
    try:
        payload = usda.get_food(fdc_id)
    except (RuntimeError, SourceRequestError) as exc:
        raise UsdaUnavailable(str(exc)) from None
    rules = load_rules(conn)
    role = role_for(counts_as, free_role, usda.parse_macros(payload), rules)
    try:
        food_id = usda.import_food(conn, fdc_id, role=role, commit=False)
        conn.execute(
            "UPDATE foods SET point_class = ? WHERE id = ?",
            (_point_class(counts_as), food_id),
        )
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        if "UNIQUE" in str(exc):
            raise LabelInputError(
                {"name": f"There is already a food called {payload['description']!r}."}
            ) from None
        raise
    except Exception:
        conn.rollback()
        raise
    conn.commit()
    return food_id
