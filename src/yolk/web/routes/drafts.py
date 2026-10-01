"""Draft pages and every edit to a draft.

Every edit has one shape: change the draft through the library, re-evaluate,
then answer with the changed slot and the day totals (htmx), or redirect back
to the draft page (a plain form post).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from yolk.db import Connection
from yolk.errors import YolkError
from yolk.planning import drafts
from yolk.planning.evaluate import evaluate
from yolk.planning.plans import PlanHeader, compare, entry_units, get_plan, plan_slots
from yolk.units import default_portion
from yolk.web.deps import ConnDep, Viewer, ViewerDep, is_htmx, owned_plan
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
        "entry_units": entry_units(conn, evaluation),
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


def _slot_of_entry(conn: Connection, draft: PlanHeader, entry_id: int) -> int:
    """The entry's slot, once it is known to belong to this draft."""
    try:
        where = drafts.locate_entry(conn, entry_id)
    except LookupError:
        where = None
    if where is None or where.plan_id != draft.id:
        raise HTTPException(
            status_code=404, detail=f"There is no entry {entry_id} in this draft."
        )
    return where.slot_no


def _require_food(conn: Connection, food_id: int) -> None:
    try:
        drafts.require_food(conn, food_id)
    except LookupError:
        raise HTTPException(
            status_code=404, detail=f"There is no food {food_id}."
        ) from None


def _after_edit(
    request: Request,
    conn: Connection,
    viewer: Viewer,
    draft: PlanHeader,
    slot_no: int,
    entry_errors: dict[int, str] | None = None,
):
    """Answer an edit: the changed slot and the totals for htmx, else the page."""
    if not is_htmx(request):
        if entry_errors:
            return _draft_page(
                request, conn, viewer, draft, status_code=422, entry_errors=entry_errors
            )
        return RedirectResponse(f"/drafts/{draft.id}#slot-{slot_no}", status_code=303)
    context = draft_context(conn, viewer, draft, entry_errors=entry_errors or {})
    changed = [ps for ps in context["slots"] if ps.slot_no == slot_no]
    if not changed:
        # The last entry of a slot with no template is gone, and the slot with it.
        return HTMLResponse("", headers={"HX-Refresh": "true"})
    return templates.TemplateResponse(
        request, "drafts/_changed.html", {**context, "ps": changed[0]}
    )


@router.get("/drafts/{draft_id}", response_class=HTMLResponse)
def draft_page(draft_id: int, request: Request, conn: ConnDep, viewer: ViewerDep):
    draft = owned_plan(conn, viewer, draft_id, status="draft")
    return _draft_page(request, conn, viewer, draft)


@router.post("/drafts/{draft_id}/entries")
def add_food(
    draft_id: int,
    request: Request,
    conn: ConnDep,
    viewer: ViewerDep,
    slot_no: Annotated[int, Form()],
    food_id: Annotated[int, Form()],
):
    draft = owned_plan(conn, viewer, draft_id, status="draft")
    _require_food(conn, food_id)
    qty, unit = default_portion(conn, food_id)
    drafts.add_entry_to_draft(
        conn, draft.id, slot_no=slot_no, food_id=food_id, qty=qty, unit=unit
    )
    return _after_edit(request, conn, viewer, draft, slot_no)


@router.post("/drafts/{draft_id}/entries/{entry_id}")
def change_amount(
    draft_id: int,
    entry_id: int,
    request: Request,
    conn: ConnDep,
    viewer: ViewerDep,
    unit: Annotated[str, Form()],
    qty: Annotated[str, Form()] = "",
):
    draft = owned_plan(conn, viewer, draft_id, status="draft")
    slot_no = _slot_of_entry(conn, draft, entry_id)
    try:
        drafts.update_entry(conn, entry_id, qty=drafts.parse_amount(qty), unit=unit)
    except ValueError as exc:
        return _after_edit(request, conn, viewer, draft, slot_no, {entry_id: str(exc)})
    return _after_edit(request, conn, viewer, draft, slot_no)


@router.post("/drafts/{draft_id}/entries/{entry_id}/swap")
def swap_food(
    draft_id: int,
    entry_id: int,
    request: Request,
    conn: ConnDep,
    viewer: ViewerDep,
    food_id: Annotated[int, Form()],
):
    draft = owned_plan(conn, viewer, draft_id, status="draft")
    slot_no = _slot_of_entry(conn, draft, entry_id)
    _require_food(conn, food_id)
    qty, unit = default_portion(conn, food_id)
    drafts.replace_entry_food(conn, entry_id, food_id, qty=qty, unit=unit)
    return _after_edit(request, conn, viewer, draft, slot_no)


@router.post("/drafts/{draft_id}/entries/{entry_id}/remove")
def remove_food(
    draft_id: int, entry_id: int, request: Request, conn: ConnDep, viewer: ViewerDep
):
    draft = owned_plan(conn, viewer, draft_id, status="draft")
    slot_no = _slot_of_entry(conn, draft, entry_id)
    drafts.remove_entry(conn, entry_id)
    return _after_edit(request, conn, viewer, draft, slot_no)


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
