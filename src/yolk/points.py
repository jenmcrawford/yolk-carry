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
from yolk.macros import Macros

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
