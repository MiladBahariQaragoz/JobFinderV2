"""Pages: list, job, settings — and the partials HTMX swaps in.

Every route opens its own SQLite connection (one per thread, `busy_timeout`
— the same §8 rule the search and enrichment workers live by) and closes it
when the response is built. Nothing is cached in the process: her list is a
query, so it is always the truth in the database.
"""

from __future__ import annotations

from urllib.parse import quote, urlencode

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from jobfinder.sources.registry import SOURCE_LABELS
from jobfinder.store.db import connect, migrate
from jobfinder.store.status import set_notes, set_status
from jobfinder.web.app import templates
from jobfinder.web.queries import (
    PAGE_SIZE,
    STALE_AFTER_DAYS,
    describe_filters,
    filter_options,
    her_german_level,
    job_detail,
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


# -- one job -------------------------------------------------------------------


def _detail_or_none(request: Request, job_id: str):
    settings = request.app.state.settings
    connection = connect(settings.db_path)
    try:
        migrate(connection)
        detail = job_detail(
            connection,
            job_id,
            her_level=her_german_level(settings),
        )
    finally:
        connection.close()
    if detail is not None:
        detail["source_label"] = SOURCE_LABELS.get(detail["source"], detail["source"])
    return detail


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_page(job_id: str, request: Request):
    detail = _detail_or_none(request, job_id)
    if detail is None:
        return render(
            request,
            "error.html",
            {
                "heading": "No job here",
                "sentence": f"No job '{job_id}' is in the store — it may never have been found,"
                " or the link is old.",
                "back": "/",
            },
            status_code=404,
        )
    return render(request, "job.html", {"job": detail})


def _respond(request: Request, job_id: str, template: str, context: dict):
    """HTMX gets the swapped partial; a plain form post gets a redirect back."""
    if request.headers.get("HX-Request"):
        return render(request, template, context)
    return RedirectResponse(f"/jobs/{quote(job_id)}", status_code=303)


@router.post("/jobs/{job_id}/status")
async def set_job_status(job_id: str, request: Request):
    form = await request.form()
    status = str(form.get("status", ""))
    settings = request.app.state.settings

    connection = connect(settings.db_path)
    try:
        migrate(connection)
        try:
            set_status(connection, job_id, status)
        except ValueError as exc:
            return render(
                request,
                "error.html",
                {"heading": "That did not work", "sentence": str(exc), "back": f"/jobs/{job_id}"},
                status_code=400,
            )
        detail = job_detail(connection, job_id, her_level=her_german_level(settings))
    finally:
        connection.close()

    if detail is None:
        return render(
            request,
            "error.html",
            {"heading": "No job here", "sentence": f"No job '{job_id}'.", "back": "/"},
            status_code=404,
        )
    detail["source_label"] = SOURCE_LABELS.get(detail["source"], detail["source"])
    return _respond(request, job_id, "_actions.html", {"job": detail})


@router.post("/jobs/{job_id}/notes")
async def save_job_notes(job_id: str, request: Request):
    form = await request.form()
    notes = str(form.get("notes", ""))
    settings = request.app.state.settings

    connection = connect(settings.db_path)
    try:
        migrate(connection)
        try:
            set_notes(connection, job_id, notes)
        except ValueError as exc:
            return render(
                request,
                "error.html",
                {"heading": "That did not work", "sentence": str(exc), "back": f"/jobs/{job_id}"},
                status_code=400,
            )
        detail = job_detail(connection, job_id, her_level=her_german_level(settings))
    finally:
        connection.close()

    if detail is None:
        return render(
            request,
            "error.html",
            {"heading": "No job here", "sentence": f"No job '{job_id}'.", "back": "/"},
            status_code=404,
        )
    detail["source_label"] = SOURCE_LABELS.get(detail["source"], detail["source"])
    return _respond(request, job_id, "_notes.html", {"job": detail})
