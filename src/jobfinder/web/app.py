"""The app she opens — FastAPI, server-rendered HTML, localhost-only.

One `Settings` in (her project root: the database, the pool, the sources),
one app out. Templates are Jinja2, interactivity is HTMX from
`static/vendor/` and both font faces are local woff2 files — the packaged exe
must work offline (§10), so nothing here may point at a CDN.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from jobfinder.config import Settings

# §2: one user, one laptop. The server binds the loopback interface and
# nothing else — this line is what `test_server_binds_localhost_only` holds.
SERVER_HOST = "127.0.0.1"

WEB_DIR = Path(__file__).parent
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def create_app(settings: Settings, *, run_manager=None, roles_pool_factory=None) -> FastAPI:
    """Build the app for one project root.

    `run_manager` is the test seam for the run engine (`web/runs.py`) and
    `roles_pool_factory` the one for the single LLM call the Settings page can
    make; production builds both itself.
    """
    app = FastAPI(title="JobFinder", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    if run_manager is None:
        from jobfinder.web.runs import RunManager

        run_manager = RunManager(settings)
    app.state.run_manager = run_manager
    app.state.roles_pool_factory = roles_pool_factory
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.middleware("http")
    async def to_the_wizard_until_it_is_done(request, call_next):
        """Before the first setup, every page leads to `/setup`.

        A check inside each route would be eleven checks, and the eleventh is
        the one somebody forgets — she would meet an empty job list with no way
        to know that nothing had been set up yet. `/static` is exempt, or the
        first page she ever sees arrives without its stylesheet.
        """
        from jobfinder.first_run import needs_setup

        path = request.url.path
        exempt = path == "/setup" or path.startswith("/static") or path == "/healthz"
        if not exempt and needs_setup(app.state.settings):
            from fastapi.responses import RedirectResponse

            return RedirectResponse("/setup", status_code=303)
        return await call_next(request)

    _install_error_pages(app)

    from jobfinder.web.routes import router

    app.include_router(router)
    return app


def _install_error_pages(app: FastAPI) -> None:
    """The last line of defence: nothing reaches her as a stack trace.

    Every predictable refusal already has its own sentence (Phase 8). These two
    handlers are for the rest — a route that raises something nobody thought of,
    and a link to a page that does not exist. Both say what happened and where
    to go, because a 500 with a traceback in it is a dead end for someone who
    cannot read Python.
    """
    from fastapi import HTTPException
    from fastapi.responses import HTMLResponse
    from starlette.exceptions import HTTPException as StarletteHTTPException

    def page(request, heading: str, sentence: str, status_code: int) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "error.html",
            {"heading": heading, "sentence": sentence, "back": "/"},
            status_code=status_code,
        )

    @app.exception_handler(StarletteHTTPException)
    async def not_found(request, exc: HTTPException):
        if exc.status_code == 404:
            return page(
                request,
                "There is no page here",
                "That address does not exist in JobFinder. It may be an old link, or a typed one.",
                404,
            )
        return page(request, "That did not work", str(exc.detail), exc.status_code)

    @app.exception_handler(Exception)
    async def unexpected(request, exc: Exception):
        # The exception itself is deliberately not rendered: its words are for
        # the terminal window, which is where it has already been printed.
        return page(
            request,
            "Something went wrong",
            "JobFinder hit a problem it did not expect on that page — nothing you "
            "had is lost, and everything already saved is still there. Try again, "
            "and if it keeps happening, close the window and start it once more.",
            500,
        )
