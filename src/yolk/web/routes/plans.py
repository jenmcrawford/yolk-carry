"""Plan pages."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from yolk.planning.evaluate import evaluate
from yolk.planning.plans import plan_slots, plan_summaries
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
    if plan.status == "draft":
        return RedirectResponse(f"/drafts/{plan.id}", status_code=303)
    # partial=True: an entry that cannot be measured shows on its own row,
    # naming the food and unit, instead of hiding the whole plan.
    evaluation = evaluate(conn, plan.id, partial=True)
    return templates.TemplateResponse(
        request,
        "plans/detail.html",
        {
            "viewer": viewer,
            "plan": plan,
            "evaluation": evaluation,
            "slots": plan_slots(conn, plan.id, evaluation),
        },
    )
