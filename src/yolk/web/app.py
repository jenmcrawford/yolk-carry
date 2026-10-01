"""The local web app.

create_app() wires routes, static files, the request guards, and the pages
that replace a normal response: "run this command" when the database is not
ready, and the HTML error page for everything else that goes wrong.
"""

from __future__ import annotations

from http import HTTPStatus
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from yolk.config import database_path
from yolk.web.deps import SetupRequired
from yolk.web.routes import foods, people, plans
from yolk.web.templating import templates

STATIC_DIR = Path(__file__).parent / "static"

# Only this machine: refuses other Host headers, which stops DNS rebinding.
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _from_this_app(request: Request) -> bool:
    """Whether a request that changes something came from this app's pages.

    Browsers send Origin with every POST and usually Referer too. A request
    carrying neither is refused rather than trusted.
    """
    source = request.headers.get("origin") or request.headers.get("referer")
    return source is not None and urlsplit(source).hostname in ALLOWED_HOSTS


def create_app(db_path: Path | None = None) -> FastAPI:
    app = FastAPI(title="yolk", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.db_path = db_path if db_path is not None else database_path()
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)

    @app.middleware("http")
    async def refuse_cross_site_changes(request: Request, call_next):
        # Any website can make a browser post to 127.0.0.1. Only this app's
        # own pages may change anything.
        if request.method not in SAFE_METHODS and not _from_this_app(request):
            return templates.TemplateResponse(
                request,
                "error.html",
                {
                    "title": "Refused",
                    "message": "That change did not come from this app, so it "
                    "was refused.",
                },
                status_code=403,
            )
        return await call_next(request)

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

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        title = HTTPStatus(exc.status_code).phrase
        return templates.TemplateResponse(
            request,
            "error.html",
            {"title": title, "message": None if exc.detail == title else exc.detail},
            status_code=exc.status_code,
        )

    @app.exception_handler(RequestValidationError)
    async def bad_request(request: Request, exc: RequestValidationError):
        return templates.TemplateResponse(
            request,
            "error.html",
            {
                "title": "That didn't make sense",
                "message": "Something in the address or the form wasn't valid.",
            },
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception):
        # Starlette re-raises after this handler responds, so uvicorn still
        # logs the traceback to the console. The page never shows it.
        return templates.TemplateResponse(request, "error.html", {}, status_code=500)

    return app
