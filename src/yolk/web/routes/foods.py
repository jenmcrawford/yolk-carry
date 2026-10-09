"""The food library page, and the food picker used while editing a draft."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from yolk.foods import search_library
from yolk.web.deps import ConnDep, ViewerDep, is_htmx, owned_plan
from yolk.web.templating import templates

router = APIRouter()


@router.get("/foods", response_class=HTMLResponse)
def food_list(request: Request, conn: ConnDep, viewer: ViewerDep, q: str = ""):
    return templates.TemplateResponse(
        request,
        "foods/list.html",
        {"viewer": viewer, "query": q, "foods": search_library(conn, q)},
    )


@router.get("/foods/search", response_class=HTMLResponse)
def food_picker(
    request: Request,
    conn: ConnDep,
    viewer: ViewerDep,
    draft: int,
    slot: int,
    q: str = "",
    entry: int | None = None,
):
    plan = owned_plan(conn, viewer, draft, status="draft")
    htmx = is_htmx(request)
    pick = {
        "action": f"/drafts/{plan.id}/entries"
        if entry is None
        else f"/drafts/{plan.id}/entries/{entry}/swap",
        "label": "Add" if entry is None else "Swap in",
        "fields": {"slot_no": slot} if entry is None else {},
        # Only an inline picker has a slot on the page to swap; the full-page
        # picker posts plainly and is redirected back to the draft.
        "target": f"#slot-{slot}" if htmx else None,
    }
    return templates.TemplateResponse(
        request,
        "foods/_picker.html" if htmx else "foods/pick.html",
        {
            "viewer": viewer,
            "draft": plan,
            "slot": slot,
            "entry": entry,
            "query": q,
            "foods": search_library(conn, q),
            "pick": pick,
        },
    )
