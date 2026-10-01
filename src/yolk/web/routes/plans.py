"""Plan pages."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from yolk.errors import YolkError
from yolk.people import slot_names
from yolk.planning.evaluate import evaluate
from yolk.planning.plans import plan_summaries
from yolk.web.deps import ConnDep, ViewerDep, owned_plan
from yolk.web.templating import templates

router = APIRouter()


@router.get("/plans", response_class=HTMLResponse)
def plan_list(request: Request, conn: ConnDep, viewer: ViewerDep):
    return templates.TemplateResponse(
        request,
        "plans/list.html",
        {"viewer": viewer, "plans": plan_summaries(conn, viewer.person.id)},
    )


@router.get("/plans/{plan_id}", response_class=HTMLResponse)
def plan_detail(plan_id: int, request: Request, conn: ConnDep, viewer: ViewerDep):
    plan = owned_plan(conn, viewer, plan_id)
    try:
        evaluation, error = evaluate(conn, plan_id), None
    except YolkError as exc:
        # Shown in place of the totals and slots, naming the food and unit.
        evaluation, error = None, str(exc)
    return templates.TemplateResponse(
        request,
        "plans/detail.html",
        {
            "viewer": viewer,
            "plan": plan,
            "evaluation": evaluation,
            "error": error,
            "slot_names": slot_names(conn, plan.profile_id),
        },
    )
