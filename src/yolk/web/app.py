"""The local web app.

create_app() wires routes, static files, and the two pages that replace a
normal response: "run this command" when the database is not ready, and a
plain error page for anything unexpected.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from yolk.config import database_path
from yolk.web.deps import SetupRequired
from yolk.web.routes import foods, people, plans
from yolk.web.templating import templates

STATIC_DIR = Path(__file__).parent / "static"

# Only this machine: refuses other Host headers, which stops DNS rebinding.
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]


def create_app(db_path: Path | None = None) -> FastAPI:
    app = FastAPI(title="yolk", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.db_path = db_path if db_path is not None else database_path()
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(plans.router)
    app.include_router(people.router)
    app.include_router(foods.router)

    @app.get("/", include_in_schema=False)
    def home() -> RedirectResponse:
        return RedirectResponse("/plans", status_code=303)

    @app.exception_handler(SetupRequired)
    async def setup_required(request: Request, exc: SetupRequired):
        return templates.TemplateResponse(
            request,
            "setup.html",
            {"message": exc.message, "command": exc.command},
            status_code=503,
        )

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception):
        # Starlette re-raises after this handler responds, so uvicorn still
        # logs the traceback to the console. The page never shows it.
        return templates.TemplateResponse(request, "error.html", {}, status_code=500)

    return app
