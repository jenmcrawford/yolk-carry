"""Settings: the point sizes, and whether carbs count as total or net."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from yolk.db import Connection
from yolk.points import load_rules, set_carb_basis
from yolk.web.deps import ConnDep, Viewer, ViewerDep
from yolk.web.templating import templates

router = APIRouter()


def _settings_page(
    request: Request, conn: Connection, viewer: Viewer, *, status_code: int = 200, **extra
):
    return templates.TemplateResponse(
        request,
        "settings.html",
        {"viewer": viewer, "rules": load_rules(conn), **extra},
        status_code=status_code,
    )


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, conn: ConnDep, viewer: ViewerDep):
    return _settings_page(request, conn, viewer)


@router.post("/settings/carb-basis")
def change_carb_basis(
    request: Request, conn: ConnDep, viewer: ViewerDep, basis: Annotated[str, Form()]
):
    try:
        set_carb_basis(conn, basis)
    except ValueError as exc:
        return _settings_page(request, conn, viewer, status_code=422, form_error=str(exc))
    return RedirectResponse("/settings", status_code=303)
