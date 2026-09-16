"""Resolution of display units to grams.

Conversions are per-food on purpose: a scoop of Karbolyn is not a scoop of
cyclic dextrin, and a tablespoon of oil is not a tablespoon of mayo. Only
mass units are universal.
"""

from __future__ import annotations

from yolk.db import Connection
from yolk.errors import UnknownUnitError

MASS_UNITS = {"g": 1.0, "kg": 1000.0, "mg": 0.001, "oz": 28.349523125, "lb": 453.59237}


def _food_name(conn: Connection, food_id: int) -> str:
    row = conn.execute("SELECT name FROM foods WHERE id = ?", (food_id,)).fetchone()
    return row["name"] if row else f"food id {food_id}"


def _grams_per_unit(conn: Connection, food_id: int, unit: str) -> float:
    if unit in MASS_UNITS:
        return MASS_UNITS[unit]
    row = conn.execute(
        "SELECT grams FROM food_units WHERE food_id = ? AND unit = ?",
        (food_id, unit),
    ).fetchone()
    if row is None:
        raise UnknownUnitError(
            f"No gram conversion recorded for unit {unit!r} on "
            f"{_food_name(conn, food_id)!r} (food id {food_id}). "
            f"Add a food_units row before using this unit."
        )
    return row["grams"]


def to_grams(conn: Connection, food_id: int, qty: float, unit: str) -> float:
    """Convert a quantity in some unit to grams for a specific food."""
    return qty * _grams_per_unit(conn, food_id, unit)


def from_grams(conn: Connection, food_id: int, grams: float, unit: str) -> float:
    """Convert grams back into a display unit for a specific food."""
    return grams / _grams_per_unit(conn, food_id, unit)
