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


def create_app(settings: Settings, *, run_manager=None) -> FastAPI:
    """Build the app for one project root. `run_manager` is the test seam for
    the run engine (`web/runs.py`); production builds its own."""
    app = FastAPI(title="JobFinder", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.run_manager = run_manager
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    from jobfinder.web.routes import router

    app.include_router(router)
    return app
