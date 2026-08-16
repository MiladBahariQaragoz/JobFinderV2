"""Pages: list, job, settings — and the partials HTMX swaps in.

Every route opens its own SQLite connection (one per thread, `busy_timeout`
— the same §8 rule the search and enrichment workers live by) and closes it
when the response is built. Nothing is cached in the process: her list is a
query, so it is always the truth in the database.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from jobfinder.store.db import connect, migrate
from jobfinder.web.app import templates

router = APIRouter()


def render(request: Request, template: str, context: dict, status_code: int = 200) -> HTMLResponse:
    context.setdefault("request", request)
    return templates.TemplateResponse(request, template, context, status_code=status_code)


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    settings = request.app.state.settings
    connection = connect(settings.db_path)
    try:
        migrate(connection)
        stored = connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    finally:
        connection.close()

    return render(request, "index.html", {"stored": stored})
