"""Food creation, retrieval, and macro computation.

There is one foods table. kind='item' means purchased; kind='recipe' means
composed from other foods. Both store macros per 100 g, so both can appear
as a component of a recipe or an entry in a plan.
"""

from __future__ import annotations

import sqlite3

from yolk.macros import Macros
from yolk.units import to_grams


def create_item(
    conn: sqlite3.Connection,
    *,
    name: str,
    role: str,
    macros: Macros,
    brand: str = "",
    source: str = "manual",
    source_ref: str | None = None,
    verified: bool = False,
    units: dict[str, float] | None = None,
    notes: str | None = None,
) -> int:
    """Create a purchased food. Macros are per 100 g.

    The food row and its unit conversions are written in one transaction: a
    bad unit must not leave a food behind with no way to measure it.
    """
    try:
        cur = conn.execute(
            "INSERT INTO foods (kind, name, brand, role, kcal_100g, protein_g_100g, "
            "fat_g_100g, carb_g_100g, fiber_g_100g, source, source_ref, verified, "
            "notes) VALUES ('item', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                name, brand, role,
                macros.kcal, macros.protein_g, macros.fat_g,
                macros.carb_g, macros.fiber_g,
                source, source_ref, int(verified), notes,
            ),
        )
        food_id = cur.lastrowid
        for unit, grams in (units or {}).items():
            conn.execute(
                "INSERT INTO food_units (food_id, unit, grams) VALUES (?, ?, ?)",
                (food_id, unit, grams),
            )
    except Exception:
        conn.rollback()
        raise
    conn.commit()
    return food_id


def add_unit(
    conn: sqlite3.Connection,
    food_id: int,
    unit: str,
    grams: float,
    is_default_display: bool = False,
) -> None:
    """Record how many grams one of `unit` weighs for this specific food."""
    conn.execute(
        "INSERT INTO food_units (food_id, unit, grams, is_default_display) "
        "VALUES (?, ?, ?, ?)",
        (food_id, unit, grams, int(is_default_display)),
    )
    conn.commit()


def macros_per_100g(conn: sqlite3.Connection, food_id: int) -> Macros:
    """Return the stored per-100 g macros for a food."""
    row = conn.execute(
        "SELECT kcal_100g, protein_g_100g, fat_g_100g, carb_g_100g, fiber_g_100g "
        "FROM foods WHERE id = ?",
        (food_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"No food with id {food_id}")
    return Macros(
        kcal=row["kcal_100g"] or 0.0,
        protein_g=row["protein_g_100g"] or 0.0,
        fat_g=row["fat_g_100g"] or 0.0,
        carb_g=row["carb_g_100g"] or 0.0,
        fiber_g=row["fiber_g_100g"] or 0.0,
    )


def portion_macros(
    conn: sqlite3.Connection, food_id: int, qty: float, unit: str
) -> Macros:
    """Macros for a given quantity of a food, in any unit it knows."""
    grams = to_grams(conn, food_id, qty, unit)
    return macros_per_100g(conn, food_id).scale(grams / 100.0)
