"""Plan pages: the list, one plan, and starting drafts from either."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from yolk.db import Connection
from yolk.errors import YolkError
from yolk.people import current_profiles
from yolk.planning import drafts
from yolk.planning.evaluate import evaluate
from yolk.planning.plans import draft_summaries, plan_slots, plan_summaries
from yolk.web.deps import ConnDep, Viewer, ViewerDep, owned_plan
from yolk.web.templating import templates

router = APIRouter()


def _plan_list(
    request: Request, conn: Connection, viewer: Viewer, *, status_code: int = 200, **extra
):
    return templates.TemplateResponse(
        request,
        "plans/list.html",
        {
            "viewer": viewer,
            "plans": plan_summaries(conn, viewer.person.id),
            "drafts": draft_summaries(conn, viewer.person.id),
            "profiles": current_profiles(
                conn, viewer.person.id, date.today().isoformat()
            ),
            **extra,
        },
        status_code=status_code,
    )


@router.get("/plans", response_class=HTMLResponse)
def plan_list(request: Request, conn: ConnDep, viewer: ViewerDep):
    return _plan_list(request, conn, viewer)


@router.post("/plans")
def new_plan(
    request: Request,
    conn: ConnDep,
    viewer: ViewerDep,
    profile_id: Annotated[int, Form()],
    name: Annotated[str, Form()] = "",
):
    try:
        draft_id = drafts.start_blank_draft(conn, viewer.person.id, profile_id, name)
    except LookupError:
        raise HTTPException(status_code=404, detail=f"There is no profile {profile_id}.")
    except (YolkError, ValueError) as exc:
        return _plan_list(
            request, conn, viewer, status_code=422, form_error=str(exc), form_name=name
        )
    return RedirectResponse(f"/drafts/{draft_id}", status_code=303)


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


@router.post("/plans/{plan_id}/draft")
def edit_plan(plan_id: int, conn: ConnDep, viewer: ViewerDep):
    plan = owned_plan(conn, viewer, plan_id)
    if plan.status == "draft":
        return RedirectResponse(f"/drafts/{plan.id}", status_code=303)
    try:
        draft_id = drafts.start_draft(conn, plan.id)
    except YolkError as exc:
        # A saved plan already uses the draft's name, "<name> (draft)".
        raise HTTPException(status_code=409, detail=str(exc))
    return RedirectResponse(f"/drafts/{draft_id}", status_code=303)
