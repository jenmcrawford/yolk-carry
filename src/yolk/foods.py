"""Food creation, retrieval, and macro computation.

There is one foods table. kind='item' means purchased; kind='recipe' means
composed from other foods. Both store macros per 100 g, so both can appear
as a component of a recipe or an entry in a plan.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone

from yolk.db import Connection
from yolk.errors import MissingYieldError, RecipeCycleError
from yolk.macros import Macros
from yolk.units import to_grams


def create_item(
    conn: Connection,
    *,
    name: str,
    role: str,
    macros: Macros,
    brand: str = "",
    source: str = "manual",
    source_ref: str | None = None,
    verified: bool = False,
    verified_on: str | None = None,
    units: dict[str, float] | None = None,
    notes: str | None = None,
    commit: bool = True,
) -> int:
    """Create a purchased food. Macros are per 100 g.

    The food row and its unit conversions are written in one transaction: a
    bad unit must not leave a food behind with no way to measure it.

    `commit=False` lets a caller that is building several rows as one larger
    transaction (`yolk.seed.seed_keto_plan_a`, for instance) defer the commit
    to itself, so a failure elsewhere in that larger unit of work still rolls
    this food back too.
    """
    if verified and verified_on is None:
        verified_on = date.today().isoformat()
    try:
        row = conn.execute(
            "INSERT INTO foods (kind, name, brand, role, kcal_100g, protein_g_100g, "
            "fat_g_100g, carb_g_100g, fiber_g_100g, source, source_ref, verified, "
            "verified_on, notes) "
            "VALUES ('item', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
            (
                name, brand, role,
                macros.kcal, macros.protein_g, macros.fat_g,
                macros.carb_g, macros.fiber_g,
                source, source_ref, int(verified), verified_on, notes,
            ),
        ).fetchone()
        food_id = row["id"]
        for unit, grams in (units or {}).items():
            conn.execute(
                "INSERT INTO food_units (food_id, unit, grams) VALUES (?, ?, ?)",
                (food_id, unit, grams),
            )
    except Exception:
        conn.rollback()
        raise
    if commit:
        conn.commit()
    return food_id


def add_unit(
    conn: Connection,
    food_id: int,
    unit: str,
    grams: float,
    is_default_display: bool = False,
) -> None:
    """Record how many grams one of `unit` weighs for this specific food."""
    try:
        conn.execute(
            "INSERT INTO food_units (food_id, unit, grams, is_default_display) "
            "VALUES (?, ?, ?, ?)",
            (food_id, unit, grams, int(is_default_display)),
        )
    except Exception:
        conn.rollback()
        raise
    conn.commit()


def macros_per_100g(conn: Connection, food_id: int) -> Macros:
    """Return the stored per-100 g macros for a food.

    Items always have macros (the schema guarantees it). A recipe that has
    never been computed has NULL macro columns; that must raise rather than
    silently reporting zero, since zero is a plausible-looking wrong answer.
    """
    row = conn.execute(
        "SELECT kind, name, kcal_100g, protein_g_100g, fat_g_100g, carb_g_100g, "
        "fiber_g_100g FROM foods WHERE id = ?",
        (food_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"No food with id {food_id}")
    if row["kind"] == "recipe" and row["kcal_100g"] is None:
        raise MissingYieldError(
            f"Recipe {row['name']!r} (id {food_id}) has no computed macros. "
            f"Weigh the finished dish and call set_cooked_yield, or rebuild it "
            f"with create_recipe(servings=...) if it is portioned by count."
        )
    return Macros(
        kcal=row["kcal_100g"] or 0.0,
        protein_g=row["protein_g_100g"] or 0.0,
        fat_g=row["fat_g_100g"] or 0.0,
        carb_g=row["carb_g_100g"] or 0.0,
        fiber_g=row["fiber_g_100g"] or 0.0,
    )


def portion_macros(
    conn: Connection, food_id: int, qty: float, unit: str
) -> Macros:
    """Macros for a given quantity of a food, in any unit it knows."""
    grams = to_grams(conn, food_id, qty, unit)
    return macros_per_100g(conn, food_id).scale(grams / 100.0)


def create_recipe(
    conn: Connection,
    *,
    name: str,
    role: str,
    components: list[dict],
    cooked_yield_g: float | None = None,
    servings: int | None = None,
    instructions: str | None = None,
    units: dict[str, float] | None = None,
    notes: str | None = None,
) -> int:
    """Create a composed food. Macros are computed, never supplied.

    Each component dict needs food_id, qty, and unit. Optional keys: flex
    (bool), flex_min_g, flex_max_g, note.

    Yield comes from one of two places. Pass `cooked_yield_g` when the
    finished dish was weighed. Pass `servings` when it will be portioned by
    count instead, and the yield is derived from the summed raw component
    weight — no scale required, because the yield value cancels: storing
    per-100 g as `M * 100 / Y` alongside a serving unit of `Y / n` gives
    `M / n` per serving for any self-consistent Y. The resulting per-100 g
    figures are therefore nominal, which `yield_basis='raw_derived'` records.
    Weigh the dish instead whenever it will be portioned by weight, or nested
    into a parent recipe by weight, since water loss concentrates macros per
    gram and a raw-derived yield understates them.

    Recipe, components, and units are one transaction. A rejected component
    must not leave an empty recipe behind — and if a yield was given, the
    initial macro computation happens inside that same transaction, so a
    nested recipe that turns out to have no cooked_yield_g of its own rolls
    everything back rather than leaving a partially-written parent.
    """
    serving_g: float | None = None
    yield_basis: str | None = None

    if servings is not None:
        if cooked_yield_g is not None:
            raise ValueError(
                "Pass servings or cooked_yield_g, not both. They are two "
                "sources for one number, and choosing between them silently "
                "would make the recipe's macros depend on a hidden rule."
            )
        if servings <= 0:
            raise ValueError(f"servings must be positive, got {servings!r}.")
        if units and "serving" in units:
            raise ValueError(
                "Pass servings or an explicit 'serving' unit, not both. "
                "Accepting both lets a recipe declare n servings whose weights "
                "do not add up to the batch, with no error to say so."
            )
        # Resolved before any write, so an unknown unit leaves nothing behind.
        cooked_yield_g = sum(
            to_grams(conn, c["food_id"], c["qty"], c["unit"]) for c in components
        )
        if cooked_yield_g <= 0:
            raise ValueError(
                f"Recipe {name!r} has no component weight, so a yield cannot be "
                f"derived from it."
            )
        serving_g = cooked_yield_g / servings
        yield_basis = "raw_derived"
    elif cooked_yield_g is not None:
        yield_basis = "measured"

    if serving_g is not None:
        units = {**(units or {}), "serving": serving_g}

    try:
        row = conn.execute(
            "INSERT INTO foods (kind, name, role, cooked_yield_g, yield_basis, "
            "instructions, source, notes) "
            "VALUES ('recipe', ?, ?, ?, ?, ?, 'computed', ?) RETURNING id",
            (name, role, cooked_yield_g, yield_basis, instructions, notes),
        ).fetchone()
        food_id = row["id"]
        for c in components:
            conn.execute(
                "INSERT INTO food_components (parent_food_id, child_food_id, qty, "
                "unit, flex, flex_min_g, flex_max_g, note) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    food_id, c["food_id"], c["qty"], c["unit"],
                    int(c.get("flex", False)),
                    c.get("flex_min_g"), c.get("flex_max_g"), c.get("note"),
                ),
            )
        for unit, grams in (units or {}).items():
            conn.execute(
                "INSERT INTO food_units (food_id, unit, grams) VALUES (?, ?, ?)",
                (food_id, unit, grams),
            )
        if cooked_yield_g is not None:
            macros = _macros_resolved(conn, food_id, frozenset())
            _write_computed_macros(conn, food_id, macros)
    except Exception:
        conn.rollback()
        raise
    conn.commit()
    return food_id


def _components(conn: Connection, food_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT child_food_id, qty, unit FROM food_components "
        "WHERE parent_food_id = ? ORDER BY id",
        (food_id,),
    ).fetchall()


def _macros_resolved(
    conn: Connection, food_id: int, seen: frozenset[int]
) -> Macros:
    """Per-100 g macros, always recursing into nested recipes rather than
    trusting their cached value, so a stale cache cannot propagate.

    `seen` is the ancestor chain, used to detect cycles. Indirect cycles are
    only detectable here: the schema's CHECK catches direct self-reference,
    but a two-recipe loop is closed by an insert that is individually valid.
    """
    if food_id in seen:
        name = conn.execute(
            "SELECT name FROM foods WHERE id = ?", (food_id,)
        ).fetchone()["name"]
        raise RecipeCycleError(
            f"Recipe {name!r} (id {food_id}) contains itself, directly or "
            f"through a nested recipe."
        )

    row = conn.execute(
        "SELECT kind, name, cooked_yield_g FROM foods WHERE id = ?",
        (food_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"No food with id {food_id}")

    if row["kind"] == "item":
        return macros_per_100g(conn, food_id)

    if row["cooked_yield_g"] is None:
        raise MissingYieldError(
            f"Recipe {row['name']!r} (id {food_id}) has no cooked_yield_g, so its "
            f"per-100 g macros cannot be computed. Weigh the finished dish and call "
            f"set_cooked_yield, or use create_recipe(servings=...) instead."
        )

    chain = seen | {food_id}
    total = Macros.zero()
    for c in _components(conn, food_id):
        grams = to_grams(conn, c["child_food_id"], c["qty"], c["unit"])
        child = _macros_resolved(conn, c["child_food_id"], chain)
        total = total + child.scale(grams / 100.0)

    return total.scale(100.0 / row["cooked_yield_g"])


def _write_computed_macros(conn: Connection, food_id: int, macros: Macros) -> None:
    """Write computed per-100 g macros to a food row. Does not commit — the
    caller decides the transaction boundary."""
    conn.execute(
        "UPDATE foods SET kcal_100g = ?, protein_g_100g = ?, fat_g_100g = ?, "
        "carb_g_100g = ?, fiber_g_100g = ?, computed_at = ? WHERE id = ?",
        (
            macros.kcal, macros.protein_g, macros.fat_g, macros.carb_g,
            macros.fiber_g, datetime.now(timezone.utc).isoformat(), food_id,
        ),
    )


def set_cooked_yield(
    conn: Connection, food_id: int, cooked_yield_g: float
) -> Macros:
    """Record a weighed yield on an existing recipe and compute its macros.

    This is the second half of the create-now, cook-later flow: a recipe can
    be composed before the dish exists, and receives its yield once the
    finished dish has been weighed. The basis is always 'measured' — a
    derived yield comes from create_recipe(servings=...) instead — so a
    recipe whose per-100 g figures are real stays distinguishable from one
    whose figures are nominal.
    """
    if cooked_yield_g <= 0:
        raise ValueError(
            f"cooked_yield_g must be positive, got {cooked_yield_g!r}."
        )
    row = conn.execute(
        "SELECT kind, name FROM foods WHERE id = ?", (food_id,)
    ).fetchone()
    if row is None:
        raise LookupError(f"No food with id {food_id}")
    if row["kind"] != "recipe":
        raise ValueError(
            f"{row['name']!r} (id {food_id}) is an item, not a recipe. An "
            f"item's macros come from its source, not from a yield division."
        )

    try:
        conn.execute(
            "UPDATE foods SET cooked_yield_g = ?, yield_basis = 'measured' "
            "WHERE id = ?",
            (cooked_yield_g, food_id),
        )
        macros = _macros_resolved(conn, food_id, frozenset())
        _write_computed_macros(conn, food_id, macros)
    except Exception:
        conn.rollback()
        raise
    conn.commit()
    return macros


def recompute_recipe(conn: Connection, food_id: int) -> Macros:
    """Recompute and cache a recipe's per-100 g macros."""
    macros = _macros_resolved(conn, food_id, frozenset())
    _write_computed_macros(conn, food_id, macros)
    conn.commit()
    return macros


def derived_tags(conn: Connection, food_id: int) -> set[str]:
    """Tags on this food, unioned with those of every nested component.

    Only purchased items are tagged by hand. A recipe's tags are derived, so
    a sensitivity buried two levels deep still surfaces.
    """
    return _derived_tags(conn, food_id, frozenset())


def _derived_tags(
    conn: Connection, food_id: int, seen: frozenset[int]
) -> set[str]:
    if food_id in seen:
        raise RecipeCycleError(f"Cycle detected while deriving tags for id {food_id}")
    rows = conn.execute(
        "SELECT t.name FROM food_tags ft JOIN tags t ON t.id = ft.tag_id "
        "WHERE ft.food_id = ?",
        (food_id,),
    ).fetchall()
    tags = {r["name"] for r in rows}
    chain = seen | {food_id}
    for c in _components(conn, food_id):
        tags |= _derived_tags(conn, c["child_food_id"], chain)
    return tags
