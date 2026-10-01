"""Reading plans for display: one plan's header, and a person's plan list.

These exist so the web layer can show plans without running SQL itself.
"""

from __future__ import annotations

from dataclasses import dataclass

from yolk.db import Connection
from yolk.errors import YolkError
from yolk.planning.evaluate import evaluate


@dataclass(frozen=True)
class PlanHeader:
    id: int
    person_id: int
    profile_id: int
    profile_name: str
    name: str
    status: str


@dataclass(frozen=True)
class PlanSummary:
    id: int
    name: str
    profile_name: str
    # None exactly when the plan could not be evaluated; `error` then says why.
    ok: bool | None
    error: str | None


def get_plan(conn: Connection, plan_id: int) -> PlanHeader:
    row = conn.execute(
        "SELECT p.id, p.person_id, p.profile_id, p.name, p.status, "
        "m.name AS profile_name "
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
    )


def plan_summaries(conn: Connection, person_id: int) -> list[PlanSummary]:
    """A person's active plans, each marked within tolerance or not.

    A plan that cannot be evaluated is still listed, carrying the error, so
    one bad entry cannot hide every other plan.
    """
    rows = conn.execute(
        "SELECT p.id, p.name, m.name AS profile_name "
        "FROM day_plans p JOIN macro_profiles m ON m.id = p.profile_id "
        "WHERE p.person_id = ? AND p.status = 'active' ORDER BY p.name, p.id",
        (person_id,),
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
