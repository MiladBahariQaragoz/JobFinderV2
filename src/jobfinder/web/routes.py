"""Pages: list, job, settings — and the partials HTMX swaps in.

Every route opens its own SQLite connection (one per thread, `busy_timeout`
— the same §8 rule the search and enrichment workers live by) and closes it
when the response is built. Nothing is cached in the process: her list is a
query, so it is always the truth in the database.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

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
    POSTED_WITHIN,
    POSTED_WITHIN_LABELS,
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
        "posted_within_options": POSTED_WITHIN_LABELS,
        "posted_within": POSTED_WITHIN,
    }


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    context = _list_context(request)
    context.update(_progress_context(request))  # the panel ships with the page
    return render(request, "index.html", context)


@router.get("/search", response_class=HTMLResponse)
def search_page(request: Request):
    """Searching has its own page: it asks the internet for more jobs, which
    is a different question from narrowing the ones already stored.

    `?keywords=…` arrives from a suggested role, so the title the model
    proposed lands in the form rather than being retyped.
    """
    context = _progress_context(request)
    context["keywords"] = request.query_params.get("keywords", "")
    return render(request, "search.html", context)


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
        "default_cities": ", ".join(settings.cities),
        "default_types": ", ".join(settings.employment_types),
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


# -- explaining jobs in English, on demand --------------------------------------

# What one press spends by default. Not "everything left": a full pass over her
# store is hundreds of real free-tier calls, and the cross-cutting free-tier
# rule means the default has to be a number she can afford to press by mistake.
DEFAULT_ENRICH_LIMIT = 50


def _enrich_context(request: Request) -> dict:
    """What the Explain page and its panel share, all read from the store.

    The pending count is the promise the button makes, so it comes from the
    same query the pass itself drains — never from a cached number.
    """
    from jobfinder.llm.prompting import load_prompt
    from jobfinder.store.enrichment import already_enriched_count, pending_enrichment_count

    settings = request.app.state.settings
    manager = request.app.state.run_manager
    prompt_version = load_prompt("enrich").version

    connection = connect(settings.db_path)
    try:
        migrate(connection)
        pending = pending_enrichment_count(connection, prompt_version)
        explained = already_enriched_count(connection, prompt_version)
        has_any_jobs = connection.execute("SELECT 1 FROM jobs LIMIT 1").fetchone() is not None
        run = latest_run(connection, kind="enrich")
    finally:
        connection.close()

    return {
        "pending": pending,
        "explained": explained,
        "has_any_jobs": has_any_jobs,
        "enrich_run": run,
        "enrich_state": display_state(run) if run is not None else None,
        "enriching": manager.is_enriching() if manager is not None else False,
        "enrich_stopping": manager.enrich_is_stopping() if manager is not None else False,
        "enrich_failure": manager.enrich_failure() if manager is not None else None,
        "enrich_elapsed": elapsed_seconds(run["started_at"]) if run is not None else None,
        "default_limit": DEFAULT_ENRICH_LIMIT,
    }


@router.get("/enrich", response_class=HTMLResponse)
def enrich_page(request: Request):
    """Explaining costs one free-tier call per job, so it gets its own page —
    the same reason searching did: two buttons, two very different bills."""
    return render(request, "enrich.html", _enrich_context(request))


@router.get("/enrich/progress", response_class=HTMLResponse)
def enrich_progress(request: Request):
    return render(request, "_enrich_progress.html", _enrich_context(request))


def _bounded_limit(raw: str) -> int:
    """Her typed bound, or the default — a stale or fat-fingered value is not
    a reason to refuse, and never a reason to spend more than she asked."""
    try:
        limit = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_ENRICH_LIMIT
    return limit if limit > 0 else DEFAULT_ENRICH_LIMIT


@router.post("/run/enrich", response_class=HTMLResponse)
async def run_enrich(request: Request):
    form = await request.form()
    manager = request.app.state.run_manager
    try:
        manager.start_enrich(limit=_bounded_limit(str(form.get("limit") or "")))
    except StartRefused as exc:
        context = _enrich_context(request)
        context["refusal"] = exc
        return render(request, "_enrich_progress.html", context)
    if request.headers.get("HX-Request"):
        return render(request, "_enrich_progress.html", _enrich_context(request))
    return RedirectResponse("/enrich", status_code=303)


@router.post("/run/enrich/cancel", response_class=HTMLResponse)
def run_enrich_cancel(request: Request):
    manager = request.app.state.run_manager
    if manager is not None:
        manager.cancel_enrich()
    if request.headers.get("HX-Request"):
        return render(request, "_enrich_progress.html", _enrich_context(request))
    return RedirectResponse("/enrich", status_code=303)


def _cv_context(request: Request) -> dict:
    """What Settings says about her CV: present, missing, broken, or a template.

    Only what confirms the right file landed — languages, skill groups, years.
    Her address, phone and email stay in the file (§ Cross-cutting concerns);
    the name is shown because it is the fastest way to see the upload worked,
    and this page renders on her own laptop only.
    """
    from jobfinder.profile import ProfileError, is_unfilled_template, load_profile

    settings = request.app.state.settings
    if not settings.pool_path.exists():
        return {"cv": None, "cv_error": None, "cv_is_template": False}

    try:
        resume = load_profile(settings.pool_path)
    except ProfileError as exc:
        return {"cv": None, "cv_error": str(exc), "cv_is_template": False}

    groups = sorted(resume.skill_groups.items(), key=lambda pair: len(pair[1]), reverse=True)
    return {
        "cv": {
            "name": resume.basics.get("name", ""),
            "headline": resume.basics.get("headline", ""),
            "languages": [f"{lang.name} ({lang.level})" for lang in resume.languages],
            "skill_groups": [{"name": name, "count": len(items)} for name, items in groups[:3]],
            "years": resume.years_of_experience(),
            "jobs": len(resume.experience),
        },
        "cv_error": None,
        "cv_is_template": is_unfilled_template(resume),
    }


def _roles_context(request: Request) -> dict:
    """Whatever was suggested last — no CV, no key and no call needed (Phase 3
    stores its answers), so the page never spends anything to render."""
    from jobfinder.roles import stored_suggestions

    settings = request.app.state.settings
    roles = stored_suggestions(settings)
    return {
        "roles": [
            {
                "title_de": role.title_de,
                "title_en": role.title_en,
                "why": role.why,
                "keywords": list(role.search_keywords),
                # The point of the suggestion: the German title, handed to the
                # search form as a keyword rather than retyped by hand.
                "search_url": "/search?" + urlencode({"keywords": role.title_de}),
            }
            for role in roles or []
        ]
    }


def _settings_context(request: Request) -> dict:
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
    context = {"providers": providers, "project_root": app_settings.project_root}
    context.update(_cv_context(request))
    context.update(_roles_context(request))
    return context


# -- the call-list (Phase 9) ----------------------------------------------------

# How many places to put on one page. Smaller than the job list's 50: each of
# these is a card with a script and three buttons, and she works down them a
# few at a time with a phone in her hand. Her three cities returned 357.
CONTACTS_PAGE_SIZE = 20


def _contacts_context(request: Request) -> dict:
    """The call-list as the page needs it: best first, with her decisions."""
    from jobfinder.store.contacts import contact_counts, list_contacts

    settings = request.app.state.settings
    show_all = request.query_params.get("show") == "all"
    try:
        page = max(1, int(request.query_params.get("page", "1")))
    except ValueError:
        page = 1

    connection = connect(settings.db_path)
    try:
        migrate(connection)
        counts = contact_counts(connection)
        # The queue she works through: reachable today, not yet answered for.
        queue = list_contacts(connection, pending_only=not show_all, reachable_only=True)
        # Places with a website and no route yet — kept, but not in the queue.
        waiting = [
            row
            for row in list_contacts(connection)
            if not row["phone"] and not row["email"] and row["website"]
        ]
    finally:
        connection.close()

    pages = max(1, -(-len(queue) // CONTACTS_PAGE_SIZE))
    page = min(page, pages)
    start = (page - 1) * CONTACTS_PAGE_SIZE
    shown = queue[start : start + CONTACTS_PAGE_SIZE]

    def link(number: int) -> str:
        params = [("show", "all")] if show_all else []
        return "/contacts?" + urlencode([*params, ("page", number)])

    manager = request.app.state.run_manager
    return {
        "contacts": shown,
        "waiting": waiting if page == pages else [],
        "counts": counts,
        "show_all": show_all,
        "page": page,
        "pages": pages,
        "prev_url": link(page - 1) if page > 1 else None,
        "next_url": link(page + 1) if page < pages else None,
        "worked_through": counts["total"] > 0 and not queue and not show_all,
        "finding": manager.is_finding_contacts() if manager is not None else False,
        "contacts_failure": manager.contacts_failure() if manager is not None else None,
        "default_cities": ", ".join(settings.cities),
    }


@router.get("/contacts", response_class=HTMLResponse)
def contacts_page(request: Request):
    """A list to work through with a phone in her hand — not a job board."""
    return render(request, "contacts.html", _contacts_context(request))


def _contact_or_404(request: Request, osm_id: str):
    from jobfinder.store.contacts import contact_by_osm_id

    settings = request.app.state.settings
    connection = connect(settings.db_path)
    try:
        migrate(connection)
        return contact_by_osm_id(connection, osm_id)
    finally:
        connection.close()


@router.post("/contacts/{osm_id:path}/outcome", response_class=HTMLResponse)
async def set_outcome(osm_id: str, request: Request):
    from jobfinder.store.contacts import set_contact_outcome

    form = await request.form()
    outcome = str(form.get("outcome", ""))
    settings = request.app.state.settings

    connection = connect(settings.db_path)
    try:
        migrate(connection)
        try:
            set_contact_outcome(connection, osm_id, outcome)
        except ValueError as exc:
            status = 404 if "Unknown place" in str(exc) else 400
            return render(
                request,
                "error.html",
                {"heading": "That did not work", "sentence": str(exc), "back": "/contacts"},
                status_code=status,
            )
        _refresh_contacts_csv(connection, settings)
    finally:
        connection.close()
    return _contacts_response(request)


def _refresh_contacts_csv(connection, settings) -> None:
    """Keep the printable list in step with the screen.

    The CSV used to be rewritten only by a run, so a place she had just rung
    still read as untouched in the file she would print and carry. It is a few
    hundred rows and an atomic replace, so writing it on every decision costs
    nothing worth measuring.
    """
    from jobfinder.store.contacts_export import export_contacts

    try:
        export_contacts(connection, settings.contacts_csv)
    except OSError:
        pass  # the file being open in Excel must not lose her decision


@router.post("/contacts/{osm_id:path}/notes", response_class=HTMLResponse)
async def save_contact_notes(osm_id: str, request: Request):
    from jobfinder.store.contacts import set_contact_notes

    form = await request.form()
    notes = str(form.get("notes", ""))
    settings = request.app.state.settings

    connection = connect(settings.db_path)
    try:
        migrate(connection)
        try:
            set_contact_notes(connection, osm_id, notes)
        except ValueError as exc:
            return render(
                request,
                "error.html",
                {"heading": "No place here", "sentence": str(exc), "back": "/contacts"},
                status_code=404,
            )
        _refresh_contacts_csv(connection, settings)
    finally:
        connection.close()
    return _contacts_response(request)


def _contacts_response(request: Request):
    """HTMX gets the rows partial; a plain post goes back to the page."""
    if request.headers.get("HX-Request"):
        return render(request, "_contact_rows.html", _contacts_context(request))
    return RedirectResponse("/contacts", status_code=303)


@router.post("/run/contacts", response_class=HTMLResponse)
async def run_contacts_now(request: Request):
    """Build the call-list without a terminal — the same gap the Explain button
    closed for enrichment."""
    form = await request.form()
    manager = request.app.state.run_manager
    try:
        radius = int(str(form.get("radius") or "")) if form.get("radius") else None
    except ValueError:
        radius = None
    try:
        manager.start_contacts(cities=str(form.get("cities") or "") or None, radius_km=radius)
    except StartRefused as exc:
        context = _contacts_context(request)
        context["refusal"] = exc
        return render(request, "_contact_rows.html", context)
    return _contacts_response(request)


@router.post("/run/contacts/cancel", response_class=HTMLResponse)
def cancel_contacts_run(request: Request):
    manager = request.app.state.run_manager
    if manager is not None:
        manager.cancel_contacts()
    return _contacts_response(request)


@router.get("/setup", response_class=HTMLResponse)
def setup_page(request: Request):
    """The first thing she ever sees — and nothing at all on the second start."""
    from jobfinder.first_run import needs_setup

    settings = request.app.state.settings
    if not needs_setup(settings):
        return RedirectResponse("/", status_code=303)
    return render(request, "setup.html", _setup_context(request))


def _setup_context(request: Request) -> dict:
    """The providers to choose from, and the answers already in `Settings`."""
    import llmpool

    settings = request.app.state.settings
    catalog = llmpool.load_catalog()
    providers = [
        {"name": name, "env_var": env_var, "signup": url}
        for name, env_var, url in llmpool.missing_keys(catalog, env={})
    ]
    return {
        "providers": providers,
        "default_cities": ", ".join(settings.cities),
        "default_types": ", ".join(settings.employment_types),
        "project_root": settings.project_root,
    }


@router.post("/setup", response_class=HTMLResponse)
async def finish_setup(request: Request):
    """Write her answers and get out of the way.

    A refusal re-renders the page with the sentence on it and writes nothing:
    a typo in one town must not leave half a configuration behind.
    """
    from jobfinder.first_run import SetupError, save_setup

    settings = request.app.state.settings
    form = await request.form()
    try:
        save_setup(
            settings,
            env_var=str(form.get("env_var", "")),
            api_key=str(form.get("api_key", "")),
            cities=str(form.get("cities", "")),
            types=str(form.get("types", "")),
        )
    except SetupError as exc:
        context = _setup_context(request)
        context["error"] = str(exc)
        # What she typed comes back, except the key — that one she pastes again.
        context["default_cities"] = str(form.get("cities", ""))
        context["default_types"] = str(form.get("types", ""))
        return render(request, "setup.html", context)

    # The app reads its settings once, at startup, so the answers she just gave
    # have to reach the running process too.
    request.app.state.settings = type(settings).load(settings.project_root)
    return RedirectResponse("/search", status_code=303)


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    """One page of "is it set up": which provider keys exist, which do not,
    where to get the missing ones, and whether her CV is in place. Key values
    are never shown."""
    return render(request, "settings.html", _settings_context(request))


@router.get("/settings/cv/template")
def cv_template(request: Request):
    """The blank CV template, as a download — she should never have to find a
    file beside the source code to get started."""
    from fastapi.responses import FileResponse

    settings = request.app.state.settings
    template = settings.project_root / "pool.template.yaml"
    if not template.exists():
        # Running from an installed package rather than the checkout.
        template = Path(__file__).resolve().parents[3] / "pool.template.yaml"
    return FileResponse(
        template,
        media_type="application/x-yaml",
        filename="pool.template.yaml",
        headers={"Content-Disposition": 'attachment; filename="pool.template.yaml"'},
    )


@router.post("/settings/cv", response_class=HTMLResponse)
async def upload_cv(request: Request):
    """Take the filled template back. Validated first, written second — the CV
    she already had survives a bad paste (Phase 1 owns the error sentences)."""
    from jobfinder.profile import ProfileError, save_profile_text

    settings = request.app.state.settings
    form = await request.form()
    upload = form.get("cv")
    if hasattr(upload, "read"):
        try:
            raw = await upload.read()
        finally:
            # Starlette spools the upload to a temporary file; leaving it open
            # leaks a handle per upload, which on Windows also keeps the temp
            # file undeletable.
            await upload.close()
    else:
        raw = b""

    context = _settings_context(request)
    try:
        # Her CV is one file she typed; a stray BOM from a Windows editor is
        # hers, not a reason to refuse the upload.
        save_profile_text(
            raw.decode("utf-8-sig"),
            settings.pool_path,
            backup_path=settings.pool_backup_path,
        )
    except (ProfileError, UnicodeDecodeError) as exc:
        context["upload_error"] = str(exc)
        return render(request, "settings.html", context, status_code=200)

    if request.headers.get("HX-Request"):
        return render(request, "settings.html", _settings_context(request))
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/export", response_class=HTMLResponse)
def export_everything(request: Request):
    """Write all three CSVs from the database, now, and say what landed where.

    Each export already runs at the end of its own kind of run, so this exists
    for the times between runs: a file a page behind an interrupted run, or a
    spreadsheet she wants to send somewhere. Where the files are is half the
    answer — a CSV she cannot find has not been exported.
    """
    from jobfinder.llm.prompting import load_prompt
    from jobfinder.store.contacts_export import export_contacts
    from jobfinder.store.db import connect, migrate
    from jobfinder.store.export import export_jobs_enriched, export_jobs_init

    settings = request.app.state.settings
    connection = connect(settings.db_path)
    try:
        migrate(connection)
        jobs = export_jobs_init(connection, settings.jobs_init_csv)
        explained = export_jobs_enriched(
            connection, settings.jobs_enriched_csv, load_prompt("enrich").version
        )
        places = export_contacts(connection, settings.contacts_csv)
    finally:
        connection.close()

    context = _settings_context(request)
    context["export"] = {
        "jobs": jobs,
        "explained": explained,
        "places": places,
        "folder": settings.data_dir,
        "files": [settings.jobs_init_csv, settings.jobs_enriched_csv, settings.contacts_csv],
    }
    return render(request, "settings.html", context)


@router.post("/settings/roles", response_class=HTMLResponse)
def suggest_roles_now(request: Request):
    """One LLM call: her CV in, job titles worth searching for out (Phase 3).

    Every way this can fail is a sentence on the page — no CV, no key, an
    unusable answer, a spent quota. The answer is stored, so this is the only
    press that costs anything.
    """
    from llmpool import PoolExhausted

    from jobfinder.llm.pool import LLMConfigError, build_pool
    from jobfinder.llm.schema import roles_answer_validator
    from jobfinder.profile import ProfileError, load_profile
    from jobfinder.roles import RolesError, suggest_roles

    settings = request.app.state.settings
    factory = getattr(request.app.state, "roles_pool_factory", None) or (
        lambda: build_pool(settings, roles_answer_validator)
    )

    error = None
    try:
        resume = load_profile(settings.pool_path)
        suggest_roles(settings, resume, factory(), refresh=True)
    except (ProfileError, RolesError, LLMConfigError) as exc:
        error = str(exc)
    except PoolExhausted as exc:
        error = (
            f"The free-tier quota is spent for now ({exc}). Nothing was lost — "
            "try again later, or add a second free key."
        )

    context = _settings_context(request)
    if error is not None:
        context["roles_error"] = error
        return render(request, "settings.html", context)
    if request.headers.get("HX-Request"):
        return render(request, "settings.html", context)
    return RedirectResponse("/settings", status_code=303)
