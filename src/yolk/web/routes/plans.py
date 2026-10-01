"""Plan pages."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from yolk.planning.plans import plan_summaries
from yolk.web.deps import ConnDep, ViewerDep
from yolk.web.templating import templates

router = APIRouter()


@router.get("/plans", response_class=HTMLResponse)
def plan_list(request: Request, conn: ConnDep, viewer: ViewerDep):
    return templates.TemplateResponse(
        request,
        "plans/list.html",
        {"viewer": viewer, "plans": plan_summaries(conn, viewer.person.id)},
    )
