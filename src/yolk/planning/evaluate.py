"""Day plan construction and evaluation.

evaluate() is pure: it reads, computes, and returns, writing nothing to a
plan. Every other planning operation is built on top of it, so keeping
evaluate() side-effect free is what makes the rest testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from yolk.db import Connection
from yolk.errors import MissingYieldError, UnknownUnitError
from yolk.foods import portion_macros
from yolk.macros import KCAL_PER_G_CARB, KCAL_PER_G_FAT, KCAL_PER_G_PROTEIN, Macros
from yolk.people import profile_basis, slot_allotments, targets_for_profile
from yolk.points import (
    Points, counted_carbs, fiber_known, food_points, load_rules, point_hints,
)
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
    # None exactly when `error` is set: the entry could not be measured.
    grams: float | None
    macros: Macros | None
    error: str | None = None
    # Both None exactly when `error` is set, like grams and macros.
    points: Points | None = None
    # The carbs the day counts for this entry: total, or net under a points
    # profile whose carb setting is net.
    counted_carb_g: float | None = None
    # False when the food's fiber was never recorded: under net carbs it
    # then counts its total carbs, and the page says so.
    fiber_known: bool = True


@dataclass(frozen=True)
class SlotEvaluation:
    slot_no: int
    totals: Macros
    entries: list[EntryEvaluation] = field(default_factory=list)
    points: Points = Points()
    # None under a macros profile, or for a slot number with no template.
    allotment: Points | None = None
    # '½C short' for each point type off the allotment by more than ¼.
    # Hints never fail the day.
    hints: tuple[str, ...] = ()


@dataclass(frozen=True)
class DayEvaluation:
    day_plan_id: int
    plan_name: str
    totals: Macros
    target: Macros
    deltas: Macros
    within_tolerance: dict[str, bool]
    slots: list[SlotEvaluation] = field(default_factory=list)
    # Entries left out of every total because they could not be measured.
    excluded: int = 0
    # 'macros' or 'points'. Under points, totals.kcal is counted from grams
    # (9/4/4) and totals.carb_g is the counted carbs; label_kcal keeps what
    # the labels say. Under macros the two calorie figures are the same.
    basis: str = "macros"
    points: Points = Points()
    allotment: Points | None = None
    label_kcal: float = 0.0
    # Actual and target shares of calories, as judged.
    fat_pct: float = 0.0
    carb_pct: float = 0.0
    target_fat_pct: float = 0.0
    target_carb_pct: float = 0.0

    @property
    def ok(self) -> bool:
        return self.excluded == 0 and all(self.within_tolerance.values())


def _pct_of_kcal(grams: float, kcal_per_g: float, total_kcal: float) -> float:
    if total_kcal == 0:
        return 0.0
    return grams * kcal_per_g / total_kcal * 100.0


def evaluate(
    conn: Connection, day_plan_id: int, *, partial: bool = False
) -> DayEvaluation:
    """Aggregate a day plan and compare it against its profile's targets.

    By default the first entry that cannot be measured raises, naming the food
    and unit. With partial=True that entry comes back with `error` set, is
    left out of every total, and is counted in `excluded`; the day is then
    never ok. The draft page uses this so one bad entry shows on its own row
    instead of hiding the whole plan.
    """
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

    rules = load_rules(conn)
    basis = profile_basis(conn, plan["profile_id"])
    # Macros profiles were written by a coach counting total carbs.
    carb_basis = rules.carb_basis if basis == "points" else "total"
    allotments = slot_allotments(conn, plan["profile_id"])

    by_slot: dict[int, list[EntryEvaluation]] = {}
    for row in rows:
        try:
            grams = to_grams(conn, row["food_id"], row["qty"], row["unit"])
            macros = portion_macros(conn, row["food_id"], row["qty"], row["unit"])
            points = food_points(conn, row["food_id"], grams, rules)
            known = fiber_known(conn, row["food_id"])
            counted = counted_carbs(macros, carb_basis, fiber_known=known)
            error = None
        except (UnknownUnitError, MissingYieldError) as exc:
            if not partial:
                raise
            grams, macros, points, counted, error = None, None, None, None, str(exc)
            known = True
        by_slot.setdefault(row["slot_no"], []).append(
            EntryEvaluation(
                entry_id=row["id"],
                food_id=row["food_id"],
                food_name=row["food_name"],
                qty=row["qty"],
                unit=row["unit"],
                grams=grams,
                macros=macros,
                error=error,
                points=points,
                counted_carb_g=counted,
                fiber_known=known,
            )
        )

    slots = []
    for slot_no, entries in sorted(by_slot.items()):
        slot_points = sum(
            (e.points for e in entries if e.points is not None), Points.zero()
        )
        allotment = allotments.get(slot_no)
        slots.append(
            SlotEvaluation(
                slot_no=slot_no,
                totals=sum(
                    (e.macros for e in entries if e.macros is not None), Macros.zero()
                ),
                entries=entries,
                points=slot_points,
                allotment=allotment,
                hints=() if allotment is None else point_hints(slot_points, allotment),
            )
        )
    label_totals = sum((s.totals for s in slots), Macros.zero())
    excluded = sum(1 for s in slots for e in s.entries if e.error is not None)

    if basis == "points":
        # Counted from grams with the same arithmetic that builds the target,
        # so a day that hits every allotment always passes on calories.
        carb_g = sum(
            e.counted_carb_g
            for s in slots for e in s.entries
            if e.counted_carb_g is not None
        )
        totals = label_totals.replace(
            carb_g=carb_g,
            kcal=label_totals.fat_g * KCAL_PER_G_FAT
            + carb_g * KCAL_PER_G_CARB
            + label_totals.protein_g * KCAL_PER_G_PROTEIN,
        )
    else:
        totals = label_totals

    target = targets_for_profile(conn, plan["profile_id"])
    profile = conn.execute(
        "SELECT kcal_tol_pct, protein_tol_g, macro_pct_tol "
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
    # From the gram targets, so a points profile (which stores no
    # percentages) and a macros profile are judged the same way.
    target_fat_pct = _pct_of_kcal(target.fat_g, KCAL_PER_G_FAT, target.kcal)
    target_carb_pct = _pct_of_kcal(target.carb_g, KCAL_PER_G_CARB, target.kcal)

    within_tolerance = {
        "kcal": abs(deltas.kcal) <= target.kcal * profile["kcal_tol_pct"] / 100.0,
        "protein_g": abs(deltas.protein_g) <= profile["protein_tol_g"],
        "fat_pct": abs(actual_fat_pct - target_fat_pct) <= profile["macro_pct_tol"],
        "carb_pct": abs(actual_carb_pct - target_carb_pct)
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
        excluded=excluded,
        basis=basis,
        points=sum((s.points for s in slots), Points.zero()),
        allotment=sum(allotments.values(), Points.zero()) if allotments else None,
        label_kcal=label_totals.kcal,
        fat_pct=actual_fat_pct,
        carb_pct=actual_carb_pct,
        target_fat_pct=target_fat_pct,
        target_carb_pct=target_carb_pct,
    )
