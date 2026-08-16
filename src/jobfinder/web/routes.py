"""Pages: list, job, settings — and the partials HTMX swaps in.

Every route opens its own SQLite connection (one per thread, `busy_timeout`
— the same §8 rule the search and enrichment workers live by) and closes it
when the response is built. Nothing is cached in the process: her list is a
query, so it is always the truth in the database.
"""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from jobfinder.sources.registry import SOURCE_LABELS
from jobfinder.store.db import connect, migrate
from jobfinder.web.app import templates
from jobfinder.web.queries import (
    PAGE_SIZE,
    STALE_AFTER_DAYS,
    describe_filters,
    filter_options,
    her_german_level,
    list_jobs,
    parse_filters,
)

router = APIRouter()


def render(request: Request, template: str, context: dict, status_code: int = 200) -> HTMLResponse:
    context.setdefault("request", request)
    return templates.TemplateResponse(request, template, context, status_code=status_code)


def _list_context(request: Request) -> dict:
    """Everything the list page and its rows partial share."""
    settings = request.app.state.settings
    filters = parse_filters(request.query_params)

    connection = connect(settings.db_path)
    try:
        migrate(connection)
        her_level = her_german_level(settings)
        jobs, total = list_jobs(connection, filters, her_level=her_level)
        options = filter_options(connection)
        has_any_jobs = connection.execute("SELECT 1 FROM jobs LIMIT 1").fetchone() is not None
    finally:
        connection.close()

    pages = max(1, -(-total // PAGE_SIZE))
    params = dict(request.query_params)
    prev_url = next_url = None
    if filters.page > 1:
        prev_url = "/?" + urlencode({**params, "page": filters.page - 1})
    if filters.page < pages:
        next_url = "/?" + urlencode({**params, "page": filters.page + 1})
    return {
        "jobs": jobs,
        "total": total,
        "pages": pages,
        "prev_url": prev_url,
        "next_url": next_url,
        "filters": filters,
        "options": options,
        "has_any_jobs": has_any_jobs,
        "active_filters": describe_filters(filters),
        "source_labels": SOURCE_LABELS,
        "stale_days": STALE_AFTER_DAYS,
    }


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    return render(request, "index.html", _list_context(request))


@router.get("/jobs/rows", response_class=HTMLResponse)
def job_rows(request: Request):
    """The rows partial — what the filter form swaps in without a reload."""
    return render(request, "_rows.html", _list_context(request))
