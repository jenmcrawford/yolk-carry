"""Day plan construction and evaluation.

evaluate() is pure: it reads, computes, and returns, writing nothing to a
plan. Every other planning operation is built on top of it, so keeping
evaluate() side-effect free is what makes the rest testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from yolk.db import Connection
from yolk.foods import portion_macros
from yolk.macros import KCAL_PER_G_CARB, KCAL_PER_G_FAT, Macros
from yolk.people import targets_for_profile
from yolk.units import to_grams


def create_day_plan(
    conn: Connection,
    person_id: int,
    profile_id: int,
    *,
    name: str,
    notes: str | None = None,
    parent_plan_id: int | None = None,
    commit: bool = True,
) -> int:
    row = conn.execute(
        "INSERT INTO day_plans (person_id, profile_id, name, parent_plan_id, "
        "created_at, notes) VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
        (
            person_id, profile_id, name, parent_plan_id,
            datetime.now(timezone.utc).isoformat(), notes,
        ),
    ).fetchone()
    if commit:
        conn.commit()
    return row["id"]


def add_entry(
    conn: Connection,
    day_plan_id: int,
    *,
    slot_no: int,
    food_id: int,
    qty: float,
    unit: str,
    flex: bool = False,
    flex_min_g: float | None = None,
    flex_max_g: float | None = None,
    commit: bool = True,
) -> int:
    row = conn.execute(
        "INSERT INTO day_plan_entries (day_plan_id, slot_no, food_id, qty, unit, "
        "flex, flex_min_g, flex_max_g) VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
        (day_plan_id, slot_no, food_id, qty, unit,
         int(flex), flex_min_g, flex_max_g),
    ).fetchone()
    if commit:
        conn.commit()
    return row["id"]


@dataclass(frozen=True)
class EntryEvaluation:
    entry_id: int
    food_id: int
    food_name: str
    qty: float
    unit: str
    grams: float
    macros: Macros


@dataclass(frozen=True)
class SlotEvaluation:
    slot_no: int
    totals: Macros
    entries: list[EntryEvaluation] = field(default_factory=list)


@dataclass(frozen=True)
class DayEvaluation:
    day_plan_id: int
    plan_name: str
    totals: Macros
    target: Macros
    deltas: Macros
    within_tolerance: dict[str, bool]
    slots: list[SlotEvaluation] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(self.within_tolerance.values())


def _pct_of_kcal(grams: float, kcal_per_g: float, total_kcal: float) -> float:
    if total_kcal == 0:
        return 0.0
    return grams * kcal_per_g / total_kcal * 100.0


def evaluate(conn: Connection, day_plan_id: int) -> DayEvaluation:
    """Aggregate a day plan and compare it against its profile's targets."""
    plan = conn.execute(
        "SELECT name, profile_id FROM day_plans WHERE id = ?", (day_plan_id,)
    ).fetchone()
    if plan is None:
        raise LookupError(f"No day plan with id {day_plan_id}")

    rows = conn.execute(
        "SELECT e.id, e.slot_no, e.food_id, e.qty, e.unit, f.name AS food_name "
        "FROM day_plan_entries e JOIN foods f ON f.id = e.food_id "
        "WHERE e.day_plan_id = ? ORDER BY e.slot_no, e.sort_order, e.id",
        (day_plan_id,),
    ).fetchall()

    by_slot: dict[int, list[EntryEvaluation]] = {}
    for row in rows:
        grams = to_grams(conn, row["food_id"], row["qty"], row["unit"])
        macros = portion_macros(conn, row["food_id"], row["qty"], row["unit"])
        by_slot.setdefault(row["slot_no"], []).append(
            EntryEvaluation(
                entry_id=row["id"],
                food_id=row["food_id"],
                food_name=row["food_name"],
                qty=row["qty"],
                unit=row["unit"],
                grams=grams,
                macros=macros,
            )
        )

    slots = [
        SlotEvaluation(
            slot_no=slot_no,
            totals=sum((e.macros for e in entries), Macros.zero()),
            entries=entries,
        )
        for slot_no, entries in sorted(by_slot.items())
    ]
    totals = sum((s.totals for s in slots), Macros.zero())

    target = targets_for_profile(conn, plan["profile_id"])
    profile = conn.execute(
        "SELECT fat_pct, carb_pct, kcal_tol_pct, protein_tol_g, macro_pct_tol "
        "FROM macro_profiles WHERE id = ?",
        (plan["profile_id"],),
    ).fetchone()

    deltas = Macros(
        kcal=totals.kcal - target.kcal,
        protein_g=totals.protein_g - target.protein_g,
        fat_g=totals.fat_g - target.fat_g,
        carb_g=totals.carb_g - target.carb_g,
        fiber_g=totals.fiber_g - target.fiber_g,
    )

    actual_fat_pct = _pct_of_kcal(totals.fat_g, KCAL_PER_G_FAT, totals.kcal)
    actual_carb_pct = _pct_of_kcal(totals.carb_g, KCAL_PER_G_CARB, totals.kcal)

    within_tolerance = {
        "kcal": abs(deltas.kcal) <= target.kcal * profile["kcal_tol_pct"] / 100.0,
        "protein_g": abs(deltas.protein_g) <= profile["protein_tol_g"],
        "fat_pct": abs(actual_fat_pct - profile["fat_pct"]) <= profile["macro_pct_tol"],
        "carb_pct": abs(actual_carb_pct - profile["carb_pct"])
        <= profile["macro_pct_tol"],
    }

    return DayEvaluation(
        day_plan_id=day_plan_id,
        plan_name=plan["name"],
        totals=totals,
        target=target,
        deltas=deltas,
        within_tolerance=within_tolerance,
        slots=slots,
    )
