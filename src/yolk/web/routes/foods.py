"""The food library page."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from yolk.foods import search_library
from yolk.web.deps import ConnDep, ViewerDep
from yolk.web.templating import templates

router = APIRouter()


@router.get("/foods", response_class=HTMLResponse)
def food_list(request: Request, conn: ConnDep, viewer: ViewerDep, q: str = ""):
    return templates.TemplateResponse(
        request,
        "foods/list.html",
        {"viewer": viewer, "query": q, "foods": search_library(conn, q)},
    )
