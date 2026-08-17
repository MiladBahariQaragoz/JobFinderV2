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

from jobfinder.cli import DEFAULT_CITIES, DEFAULT_TYPES
from jobfinder.sources.registry import SOURCE_LABELS
from jobfinder.store.db import connect, migrate
from jobfinder.store.runs import (
    display_state,
    interrupted_run,
    latest_run,
    run_sources,
)
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
from jobfinder.web.runs import StartRefused, elapsed_seconds

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
    # Repeated parameters are the point now (?city=A&city=B), so the paging
    # links are rebuilt from every pair — a dict() here would keep only the
    # last value of each and quietly drop the rest of her selection.
    params = [(key, value) for key, value in request.query_params.multi_items() if key != "page"]
    prev_url = next_url = None
    if filters.page > 1:
        prev_url = "/?" + urlencode([*params, ("page", filters.page - 1)])
    if filters.page < pages:
        next_url = "/?" + urlencode([*params, ("page", filters.page + 1)])
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
    context = _list_context(request)
    context.update(_progress_context(request))  # the panel ships with the page
    return render(request, "index.html", context)


@router.get("/search", response_class=HTMLResponse)
def search_page(request: Request):
    """Searching has its own page: it asks the internet for more jobs, which
    is a different question from narrowing the ones already stored."""
    return render(request, "search.html", _progress_context(request))


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


# -- runs: the live progress surface (§10) --------------------------------------


def _progress_context(request: Request) -> dict:
    """Everything the progress panel shows, read from the journal — never
    from the run thread's memory, so a reload shows the same truth."""
    settings = request.app.state.settings
    manager = request.app.state.run_manager

    connection = connect(settings.db_path)
    try:
        migrate(connection)
        run = latest_run(connection, kind="search")
        sources = run_sources(connection, run["id"]) if run is not None else []
        enrichment = latest_run(connection, kind="enrich")
        interrupted = interrupted_run(connection)
    finally:
        connection.close()

    state = display_state(run) if run is not None else None
    running = manager.is_running() if manager is not None else False
    elapsed = elapsed_seconds(run["started_at"]) if run is not None else None
    rate = None
    if run is not None and elapsed and elapsed > 0:
        rate = round(run["found_count"] / (elapsed / 60))

    return {
        "run": run,
        "run_state": state,
        "running": running,
        "sources": [
            {
                "label": SOURCE_LABELS.get(row["source"], row["source"]),
                "found": row["found_count"],
                "new": row["new_count"],
                "state": row["state"],
            }
            for row in sources
        ],
        "enrichment": enrichment,
        "enrich_state": display_state(enrichment) if enrichment is not None else None,
        "interrupted": interrupted,
        "elapsed": elapsed,
        "rate": rate,
        "failure": manager.failure() if manager is not None else None,
        "default_cities": ", ".join(DEFAULT_CITIES),
        "default_types": ", ".join(DEFAULT_TYPES),
    }


@router.get("/progress", response_class=HTMLResponse)
def progress(request: Request):
    return render(request, "_progress.html", _progress_context(request))


@router.post("/run/start", response_class=HTMLResponse)
async def run_start(request: Request):
    form = await request.form()
    manager = request.app.state.run_manager
    context = _progress_context(request)
    try:
        manager.start(
            resume=bool(form.get("resume")),
            enrich=bool(form.get("enrich")),
            cities=str(form.get("cities") or "") or None,
            types=str(form.get("types") or "") or None,
            keywords=str(form.get("keywords") or "") or None,
        )
    except StartRefused as exc:
        # Rendered, not raised: this is a state she can act on, not an error
        # dump — §10's "a sentence and a link, not a traceback".
        context["refusal"] = exc
        return render(request, "_progress.html", context)
    if request.headers.get("HX-Request"):
        return render(request, "_progress.html", _progress_context(request))
    return RedirectResponse("/", status_code=303)


@router.post("/run/cancel", response_class=HTMLResponse)
def run_cancel(request: Request):
    manager = request.app.state.run_manager
    if manager is not None:
        manager.cancel()
    if request.headers.get("HX-Request"):
        return render(request, "_progress.html", _progress_context(request))
    return RedirectResponse("/", status_code=303)


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    """One page of "is it set up": which provider keys exist, which do not,
    and where to get the missing ones. Key values are never shown."""
    import llmpool

    app_settings = request.app.state.settings
    catalog = llmpool.load_catalog()
    missing_vars = {env_var for _name, env_var, _url in llmpool.missing_keys(catalog)}
    providers = [
        {
            "name": name,
            "env_var": env_var,
            "signup": url,
            "present": env_var not in missing_vars,
        }
        # missing_keys(catalog, env={}) enumerates every enabled provider,
        # whether or not a key exists for it.
        for name, env_var, url in llmpool.missing_keys(catalog, env={})
    ]
    providers.sort(key=lambda provider: (not provider["present"], provider["name"]))
    return render(
        request,
        "settings.html",
        {"providers": providers, "project_root": app_settings.project_root},
    )
