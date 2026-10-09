"""Reading plans for display: headers, lists, slots, and comparisons.

These exist so the web layer can show plans without running SQL itself.
"""

from __future__ import annotations

from dataclasses import dataclass

from yolk.db import Connection
from yolk.errors import YolkError
from yolk.macros import Macros
from yolk.people import slot_names
from yolk.planning.evaluate import DayEvaluation, SlotEvaluation, evaluate
from yolk.units import units_for


@dataclass(frozen=True)
class PlanHeader:
    id: int
    person_id: int
    profile_id: int
    profile_name: str
    name: str
    status: str
    # Set for a draft started from a saved plan, and kept as lineage after
    # the draft is saved as new.
    parent_plan_id: int | None = None


@dataclass(frozen=True)
class PlanSummary:
    id: int
    name: str
    profile_name: str
    # None exactly when the plan could not be evaluated; `error` then says why.
    ok: bool | None
    error: str | None


@dataclass(frozen=True)
class PlanSlot:
    slot_no: int
    name: str
    # None when nothing is planned in this slot yet.
    slot: SlotEvaluation | None


def get_plan(conn: Connection, plan_id: int) -> PlanHeader:
    row = conn.execute(
        "SELECT p.id, p.person_id, p.profile_id, p.name, p.status, "
        "p.parent_plan_id, m.name AS profile_name "
        "FROM day_plans p JOIN macro_profiles m ON m.id = p.profile_id "
        "WHERE p.id = ?",
        (plan_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"No day plan with id {plan_id}")
    return PlanHeader(
        id=row["id"],
        person_id=row["person_id"],
        profile_id=row["profile_id"],
        profile_name=row["profile_name"],
        name=row["name"],
        status=row["status"],
        parent_plan_id=row["parent_plan_id"],
    )


def _summaries(conn: Connection, person_id: int, status: str) -> list[PlanSummary]:
    rows = conn.execute(
        "SELECT p.id, p.name, m.name AS profile_name "
        "FROM day_plans p JOIN macro_profiles m ON m.id = p.profile_id "
        "WHERE p.person_id = ? AND p.status = ? ORDER BY p.name, p.id",
        (person_id, status),
    ).fetchall()
    summaries: list[PlanSummary] = []
    for row in rows:
        try:
            ok, error = evaluate(conn, row["id"]).ok, None
        except YolkError as exc:
            ok, error = None, str(exc)
        summaries.append(
            PlanSummary(
                id=row["id"],
                name=row["name"],
                profile_name=row["profile_name"],
                ok=ok,
                error=error,
            )
        )
    return summaries


def plan_summaries(conn: Connection, person_id: int) -> list[PlanSummary]:
    """A person's active plans, each marked within tolerance or not.

    A plan that cannot be evaluated is still listed, carrying the error, so
    one bad entry cannot hide every other plan.
    """
    return _summaries(conn, person_id, "active")


def draft_summaries(conn: Connection, person_id: int) -> list[PlanSummary]:
    """A person's open drafts, so unfinished work can be picked up again."""
    return _summaries(conn, person_id, "draft")


def plan_slots(
    conn: Connection, plan_id: int, evaluation: DayEvaluation
) -> list[PlanSlot]:
    """Every slot to show for a plan, in order.

    That is each slot template of the plan's profile, filled or empty, plus
    any slot number holding entries without a template, named "Slot N".
    """
    names = slot_names(conn, get_plan(conn, plan_id).profile_id)
    evaluated = {slot.slot_no: slot for slot in evaluation.slots}
    return [
        PlanSlot(
            slot_no=slot_no,
            name=names.get(slot_no, f"Slot {slot_no}"),
            slot=evaluated.get(slot_no),
        )
        for slot_no in sorted(names.keys() | evaluated.keys())
    ]


def compare(draft: DayEvaluation, saved: DayEvaluation) -> Macros:
    """How much each day total changed from the saved plan to the draft."""
    return Macros(
        kcal=draft.totals.kcal - saved.totals.kcal,
        protein_g=draft.totals.protein_g - saved.totals.protein_g,
        fat_g=draft.totals.fat_g - saved.totals.fat_g,
        carb_g=draft.totals.carb_g - saved.totals.carb_g,
        fiber_g=draft.totals.fiber_g - saved.totals.fiber_g,
    )


def entry_units(conn: Connection, evaluation: DayEvaluation) -> dict[int, list[str]]:
    """The units each food in the plan can be measured in, keyed by food id."""
    return {
        entry.food_id: units_for(conn, entry.food_id)
        for slot in evaluation.slots
        for entry in slot.entries
    }
