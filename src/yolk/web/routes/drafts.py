"""Draft pages: look at a draft, then save it over its plan, save it as new,
or discard it."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from yolk.db import Connection
from yolk.errors import YolkError
from yolk.planning import drafts
from yolk.planning.evaluate import evaluate
from yolk.planning.plans import PlanHeader, compare, get_plan, plan_slots
from yolk.web.deps import ConnDep, Viewer, ViewerDep, owned_plan
from yolk.web.templating import templates

router = APIRouter()


def draft_context(
    conn: Connection, viewer: Viewer, draft: PlanHeader, **extra
) -> dict:
    """Everything the draft page and its partials need."""
    evaluation = evaluate(conn, draft.id, partial=True)
    parent = (
        None if draft.parent_plan_id is None else get_plan(conn, draft.parent_plan_id)
    )
    vs = (
        None
        if parent is None
        else compare(evaluation, evaluate(conn, parent.id, partial=True))
    )
    return {
        "viewer": viewer,
        "draft": draft,
        "parent": parent,
        "evaluation": evaluation,
        "vs": vs,
        "slots": plan_slots(conn, draft.id, evaluation),
        **extra,
    }


def _draft_page(
    request: Request,
    conn: Connection,
    viewer: Viewer,
    draft: PlanHeader,
    *,
    status_code: int = 200,
    **extra,
):
    return templates.TemplateResponse(
        request,
        "drafts/detail.html",
        draft_context(conn, viewer, draft, **extra),
        status_code=status_code,
    )


@router.get("/drafts/{draft_id}", response_class=HTMLResponse)
def draft_page(draft_id: int, request: Request, conn: ConnDep, viewer: ViewerDep):
    draft = owned_plan(conn, viewer, draft_id, status="draft")
    return _draft_page(request, conn, viewer, draft)


@router.post("/drafts/{draft_id}/save-over")
def save_draft_over(draft_id: int, request: Request, conn: ConnDep, viewer: ViewerDep):
    draft = owned_plan(conn, viewer, draft_id, status="draft")
    try:
        drafts.save_over(conn, draft.id)
    except (YolkError, ValueError) as exc:
        return _draft_page(
            request, conn, viewer, draft, status_code=422, form_error=str(exc)
        )
    return RedirectResponse(f"/plans/{draft.parent_plan_id}", status_code=303)


@router.post("/drafts/{draft_id}/save-as-new")
def save_draft_as_new(
    draft_id: int,
    request: Request,
    conn: ConnDep,
    viewer: ViewerDep,
    name: Annotated[str, Form()] = "",
):
    draft = owned_plan(conn, viewer, draft_id, status="draft")
    try:
        plan_id = drafts.save_as_new(conn, draft.id, name=name)
    except (YolkError, ValueError) as exc:
        return _draft_page(
            request, conn, viewer, draft, status_code=422, form_error=str(exc)
        )
    return RedirectResponse(f"/plans/{plan_id}", status_code=303)


@router.post("/drafts/{draft_id}/discard")
def discard_draft(draft_id: int, conn: ConnDep, viewer: ViewerDep):
    draft = owned_plan(conn, viewer, draft_id, status="draft")
    drafts.discard_draft(conn, draft.id)
    back = f"/plans/{draft.parent_plan_id}" if draft.parent_plan_id else "/plans"
    return RedirectResponse(back, status_code=303)
