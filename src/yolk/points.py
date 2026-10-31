"""The point system: macros seen as points.

One point is a fixed number of grams of one macro: FAT, CARB, PROTEIN, and
VEGGIE (carbs from a vegetable). FREE foods are not counted. The sizes live in
the point_rules table, so the coach can change them without touching a food.

Points are never stored. Everything here is computed from Macros and the
rules, so a corrected label or a new point size shows up everywhere at once.
"""

from __future__ import annotations

from dataclasses import dataclass

from yolk.db import Connection
from yolk.errors import MissingYieldError, RecipeCycleError
from yolk.foods import macros_per_100g
from yolk.macros import Macros
from yolk.units import MASS_UNITS, own_units, to_grams

POINT_TYPES = ("fat", "carb", "protein", "veggie")
CARB_BASES = ("total", "net")

_LETTERS = {"fat": "F", "carb": "C", "protein": "P", "veggie": "V"}
_QUARTERS = {0: "", 1: "¼", 2: "½", 3: "¾"}


@dataclass(frozen=True)
class Points:
    fat: float = 0.0
    carb: float = 0.0
    protein: float = 0.0
    veggie: float = 0.0

    @staticmethod
    def zero() -> "Points":
        return Points()

    def __add__(self, other: "Points") -> "Points":
        if not isinstance(other, Points):
            return NotImplemented
        return Points(
            fat=self.fat + other.fat,
            carb=self.carb + other.carb,
            protein=self.protein + other.protein,
            veggie=self.veggie + other.veggie,
        )

    __radd__ = __add__

    def scale(self, factor: float) -> "Points":
        return Points(
            fat=self.fat * factor,
            carb=self.carb * factor,
            protein=self.protein * factor,
            veggie=self.veggie * factor,
        )


@dataclass(frozen=True)
class PointRules:
    fat_g: float
    carb_g: float
    protein_g: float
    veggie_g: float
    # 'total' or 'net': which carbs a carb or veggie point counts.
    carb_basis: str


def load_rules(conn: Connection) -> PointRules:
    sizes = {
        row["point_type"]: row["grams_per_point"]
        for row in conn.execute("SELECT point_type, grams_per_point FROM point_rules")
    }
    basis = conn.execute(
        "SELECT value FROM settings WHERE key = 'carb_basis'"
    ).fetchone()
    return PointRules(
        fat_g=sizes["fat"],
        carb_g=sizes["carb"],
        protein_g=sizes["protein"],
        veggie_g=sizes["veggie"],
        carb_basis=basis["value"] if basis else "total",
    )


def set_carb_basis(conn: Connection, basis: str) -> None:
    """Count carbs as total or net everywhere, from the next computation on."""
    if basis not in CARB_BASES:
        raise ValueError(f"Carb basis must be 'total' or 'net', not {basis!r}.")
    conn.execute(
        "UPDATE settings SET value = ? WHERE key = 'carb_basis'", (basis,)
    )
    conn.commit()


def counted_carbs(m: Macros, basis: str, *, fiber_known: bool = True) -> float:
    """The carbs a point counts: total, or net of fiber and sugar alcohols.

    A food whose fiber was never recorded falls back to total carbs under
    net: treating unknown fiber as zero would be the same number, but saying
    so out loud is the caller's job (fiber_known is how it knows to).
    """
    if basis == "total" or not fiber_known:
        return m.carb_g
    return max(m.carb_g - m.fiber_g - m.sugar_alcohol_g, 0.0)


def points_for(
    m: Macros, cls: str, rules: PointRules, *, fiber_known: bool = True
) -> Points:
    """Points for a portion's macros, under the food's effective class."""
    if cls == "free":
        return Points.zero()
    carbs = counted_carbs(m, rules.carb_basis, fiber_known=fiber_known)
    return Points(
        fat=m.fat_g / rules.fat_g,
        carb=0.0 if cls == "veggie" else carbs / rules.carb_g,
        protein=m.protein_g / rules.protein_g,
        veggie=carbs / rules.veggie_g if cls == "veggie" else 0.0,
    )


def effective_class(
    point_class: str | None, per_100g: Macros, rules: PointRules
) -> str:
    """The class a food is scored under: its override, or its biggest macro."""
    if point_class is not None:
        return point_class
    scored = points_for(per_100g, "carb", rules)
    candidates = (("fat", scored.fat), ("carb", scored.carb), ("protein", scored.protein))
    # max keeps the first of equals, so ties go fat, carb, protein.
    return max(candidates, key=lambda pair: pair[1])[0]


def _quarters(value: float) -> int:
    return round(value * 4)


def _fraction(quarters: int) -> str:
    whole, part = divmod(quarters, 4)
    return f"{whole or ''}{_QUARTERS[part]}" if part else str(whole)


def format_points(p: Points) -> str:
    """'1P + ½F': nearest quarter, biggest first, types rounding to 0 left out."""
    rounded = [
        (_quarters(getattr(p, name)), index, name)
        for index, name in enumerate(POINT_TYPES)
    ]
    shown = sorted(
        (item for item in rounded if item[0] > 0), key=lambda item: (-item[0], item[1])
    )
    if not shown:
        return "—"
    return " + ".join(f"{_fraction(q)}{_LETTERS[name]}" for q, _, name in shown)


def point_hints(
    planned: Points, allotment: Points, tolerance: float = 0.25
) -> tuple[str, ...]:
    """'½C short' for each type off its allotment by more than the tolerance."""
    hints = []
    for name in POINT_TYPES:
        diff = getattr(planned, name) - getattr(allotment, name)
        if abs(diff) > tolerance:
            amount = _fraction(max(_quarters(abs(diff)), 1))
            hints.append(f"{amount}{_LETTERS[name]} {'over' if diff > 0 else 'short'}")
    return tuple(hints)


# --- Points for foods in the library -------------------------------------

# Which portion a food is added to a meal at, when it has several.
_PORTION_ORDER = ("manual", "coach", "label", "claude")

# A coach portion agrees with the macros when its main type lands here.
AGREEMENT_RANGE = (0.75, 1.25)


@dataclass(frozen=True)
class Portion:
    qty: float
    unit: str
    grams: float
    source: str
    # What the source says the portion counts as, in its own words.
    claimed: str


@dataclass(frozen=True)
class OnePoint:
    qty: float
    unit: str
    grams: float
    # e.g. "4 oz (113 g) → 1P + ¼F"
    label: str


def fiber_known(conn: Connection, food_id: int) -> bool:
    """False when an item's fiber was never recorded. Recipes are judged
    component by component, so they always count as known."""
    row = conn.execute(
        "SELECT kind, fiber_g_100g FROM foods WHERE id = ?", (food_id,)
    ).fetchone()
    if row is None:
        raise LookupError(f"No food with id {food_id}")
    return row["kind"] == "recipe" or row["fiber_g_100g"] is not None


def food_points(
    conn: Connection, food_id: int, grams: float, rules: PointRules
) -> Points:
    """Points for `grams` of a food.

    A recipe scores the sum of its components, each under its own class, so
    a stir-fry's broccoli stays veggie instead of turning into carb points.
    """
    return _food_points(conn, food_id, grams, rules, frozenset())


def _food_points(
    conn: Connection,
    food_id: int,
    grams: float,
    rules: PointRules,
    seen: frozenset[int],
) -> Points:
    row = conn.execute(
        "SELECT kind, name, point_class, cooked_yield_g FROM foods WHERE id = ?",
        (food_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"No food with id {food_id}")

    if row["kind"] == "item":
        per_100g = macros_per_100g(conn, food_id)
        cls = effective_class(row["point_class"], per_100g, rules)
        return points_for(
            per_100g.scale(grams / 100.0), cls, rules,
            fiber_known=fiber_known(conn, food_id),
        )

    if food_id in seen:
        raise RecipeCycleError(
            f"Recipe {row['name']!r} (id {food_id}) contains itself, directly or "
            f"through a nested recipe."
        )
    if row["cooked_yield_g"] is None:
        raise MissingYieldError(
            f"Recipe {row['name']!r} (id {food_id}) has no cooked_yield_g, so its "
            f"points cannot be computed. Weigh the finished dish and call "
            f"set_cooked_yield, or use create_recipe(servings=...) instead."
        )
    share = grams / row["cooked_yield_g"]
    total = Points.zero()
    for c in conn.execute(
        "SELECT child_food_id, qty, unit FROM food_components "
        "WHERE parent_food_id = ? ORDER BY id",
        (food_id,),
    ).fetchall():
        child_grams = to_grams(conn, c["child_food_id"], c["qty"], c["unit"]) * share
        total = total + _food_points(
            conn, c["child_food_id"], child_grams, rules, seen | {food_id}
        )
    return total


def _main_type(conn: Connection, food_id: int, per_100g: Points) -> str | None:
    row = conn.execute(
        "SELECT kind, point_class FROM foods WHERE id = ?", (food_id,)
    ).fetchone()
    # A recipe's own class is ignored, as in food_points.
    return main_type(row["point_class"] if row["kind"] == "item" else None, per_100g)


def _quarter_units(grams: float, grams_per_unit: float) -> float:
    """`grams` in a unit, to the nearest quarter, and never below a quarter."""
    return max(round(grams / grams_per_unit * 4) / 4, 0.25)


def _units_of(conn: Connection, food_id: int) -> list[tuple[str, float]]:
    """(unit, grams) for each of the food's own units, or ounces if it has none."""
    own = own_units(conn, food_id)
    if not own:
        return [("oz", MASS_UNITS["oz"])]
    return [(unit, to_grams(conn, food_id, 1.0, unit)) for unit in own]


def _best_unit(units: list[tuple[str, float]], grams: float) -> tuple[str, float]:
    """The unit whose nearest quarter lands closest to `grams`.

    A quarter cup is the smallest step in cups, so a one-point portion of
    27 g reads as 1¾ tbsp, not ¼ cup. Ties go to the unit listed first (the
    food's default display unit).
    """
    return min(units, key=lambda u: abs(_quarter_units(grams, u[1]) * u[1] - grams))


def format_qty(qty: float) -> str:
    """3.5 -> '3½', 0.25 -> '¼', 4.0 -> '4'."""
    return _fraction(_quarters(qty))


def main_type(point_class: str | None, per_100g: Points) -> str | None:
    """The type one point of a food is measured in, or None for a free food.

    An explicit class decides; otherwise (automatic, or a recipe) it is
    whichever type the food carries most of.
    """
    if point_class == "free":
        return None
    if point_class is not None:
        return point_class
    return max(POINT_TYPES, key=lambda name: getattr(per_100g, name))


def one_point_from(
    per_100g: Points, main: str | None, units: list[tuple[str, float]]
) -> OnePoint | None:
    """One point of `main`, in whichever of `units` measures it best.

    Pure, so a label can be previewed before the food exists. Points are
    linear in grams, so per-100 g points scale to any portion.
    """
    if main is None or getattr(per_100g, main) <= 0:
        return None
    exact_grams = 100.0 / getattr(per_100g, main)
    unit, grams_per_unit = _best_unit(units, exact_grams)
    qty = _quarter_units(exact_grams, grams_per_unit)
    grams = qty * grams_per_unit
    points = per_100g.scale(grams / 100.0)
    return OnePoint(
        qty=qty,
        unit=unit,
        grams=grams,
        label=f"{format_qty(qty)} {unit} ({grams:.0f} g) → {format_points(points)}",
    )


def one_point(conn: Connection, food_id: int, rules: PointRules) -> OnePoint | None:
    """How much of a food is one point of its main type, in its usual unit.

    None for a free food, and for one with none of its main type: there is
    no amount of olive oil that is one carb.
    """
    per_100g = food_points(conn, food_id, 100.0, rules)
    return one_point_from(
        per_100g, _main_type(conn, food_id, per_100g), _units_of(conn, food_id)
    )


def portions(conn: Connection, food_id: int) -> list[Portion]:
    """Every source's portion for a food, in the order they are preferred."""
    rows = conn.execute(
        "SELECT source, qty, unit, claimed FROM point_portions WHERE food_id = ?",
        (food_id,),
    ).fetchall()
    found = [
        Portion(
            qty=row["qty"],
            unit=row["unit"],
            grams=to_grams(conn, food_id, row["qty"], row["unit"]),
            source=row["source"],
            claimed=row["claimed"],
        )
        for row in rows
    ]
    return sorted(found, key=lambda p: _PORTION_ORDER.index(p.source))


def preferred_portion(conn: Connection, food_id: int) -> Portion | None:
    """The portion a food is added to a meal at: Jen's own, then the coach's."""
    found = portions(conn, food_id)
    return found[0] if found else None


def add_portion(
    conn: Connection,
    food_id: int,
    *,
    source: str,
    qty: float,
    unit: str,
    claimed: str,
    commit: bool = True,
) -> None:
    """Record what a source says one serving of points is.

    The unit is resolved before writing, so a portion nobody can measure is
    never stored.
    """
    to_grams(conn, food_id, qty, unit)
    conn.execute(
        "INSERT INTO point_portions (food_id, source, qty, unit, claimed) "
        "VALUES (?, ?, ?, ?, ?)",
        (food_id, source, qty, unit, claimed),
    )
    if commit:
        conn.commit()


def agrees(
    conn: Connection, food_id: int, points: Points, rules: PointRules
) -> bool:
    """Whether a portion's main type lands within AGREEMENT_RANGE of one point."""
    main = _main_type(conn, food_id, food_points(conn, food_id, 100.0, rules))
    if main is None:
        return True
    low, high = AGREEMENT_RANGE
    return low <= getattr(points, main) <= high


def entry_default(conn: Connection, food_id: int) -> tuple[float, str]:
    """The amount a food is added to a meal at: its preferred point portion,
    or, for a food no source has portioned, one of its usual unit."""
    from yolk.units import default_portion

    portion = preferred_portion(conn, food_id)
    if portion is not None:
        return portion.qty, portion.unit
    return default_portion(conn, food_id)
