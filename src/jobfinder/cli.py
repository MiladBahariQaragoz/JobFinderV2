"""Command-line entry points.

Every command prints for her, not for a developer: one sentence per problem,
plain summaries on success. Failures exit 1 with a message she can act on —
never a traceback.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from jobfinder.config import Settings
from jobfinder.profile import ProfileError, Resume, load_profile


def _default_pool_path() -> Path:
    return Settings.load(Path.cwd()).pool_path


def _load(path: Path) -> Resume | None:
    try:
        return load_profile(path)
    except ProfileError as exc:
        print(exc)
        return None


def _profile_summary(resume: Resume) -> str:
    languages = ", ".join(f"{lang.name} ({lang.level})" for lang in resume.languages)
    groups = sorted(resume.skill_groups.items(), key=lambda pair: len(pair[1]), reverse=True)[:3]
    group_lines = "\n".join(f"  - {name}: {len(items)} skills" for name, items in groups)
    return (
        f"OK — {resume.basics['name']}\n"
        f"  Languages: {languages or 'none listed'}\n"
        f"  Strongest skill groups:\n{group_lines if groups else '  (none listed)'}\n"
        f"  Experience: {resume.years_of_experience()} years"
    )


def _cmd_profile_validate(path: Path) -> int:
    resume = _load(path)
    if resume is None:
        return 1
    print(_profile_summary(resume))
    return 0


def _cmd_profile_show(path: Path) -> int:
    resume = _load(path)
    if resume is None:
        return 1

    lines: list[str] = [f"{resume.basics['name']} — {resume.basics.get('headline', '')}"]
    contact = " · ".join(
        str(resume.basics[key]) for key in ("email", "location") if resume.basics.get(key)
    )
    if contact:
        lines.append(contact)

    if resume.languages:
        lines += ["", "Languages"]
        lines += [f"  {lang.name}: {lang.level} ({lang.normalized})" for lang in resume.languages]

    if resume.experience:
        lines += ["", "Experience"]
        for job in resume.experience:
            lines.append(f"  {job.role} — {job.org} ({job.start} → {job.end})")
            lines += [f"      {bullet}" for bullet in job.bullets]

    if resume.education:
        lines += ["", "Education"]
        lines += [
            f"  {entry.degree} — {entry.org} ({entry.start} → {entry.end})"
            for entry in resume.education
        ]

    if resume.projects:
        lines += ["", "Projects"]
        lines += [f"  {project.name}: {project.summary}" for project in resume.projects]

    if resume.skill_groups:
        lines += ["", "Skill groups"]
        lines += [f"  {name}: {', '.join(items)}" for name, items in resume.skill_groups.items()]

    if resume.certifications:
        lines += ["", "Certifications"]
        lines += [f"  {cert.name} ({cert.issuer})" for cert in resume.certifications]

    print("\n".join(lines))
    return 0


def _cache_size_line(settings: Settings) -> str:
    """One plain-English line about the answer cache."""
    path = settings.llm_cache_path
    if not path.exists():
        return "Cache: no cache yet — nothing has been enriched."
    import sqlite3
    from contextlib import closing

    # sqlite3's own context manager commits, it does not close — hence `closing`.
    with closing(sqlite3.connect(path)) as db:
        count = db.execute("SELECT COUNT(*) FROM llm_cache").fetchone()[0]
    plural = "" if count == 1 else "s"
    return f"Cache: {count} cached answer{plural} in {path.name}."


def _run_llmpool_doctor(settings: Settings) -> int:
    """Delegate to the llmpool CLI, which pings providers (hits the network)."""
    import subprocess
    import sys

    return subprocess.run([sys.executable, "-m", "llmpool", "doctor"], check=False).returncode


def _cmd_llm_doctor(settings: Settings, *, _run_doctor=None) -> int:
    print(_cache_size_line(settings))
    doctor = _run_doctor or _run_llmpool_doctor
    return doctor(settings)


def _render_roles_table(roles: list, *, cached: bool, top: int | None) -> str:
    shown = roles if top is None else roles[:top]
    source = "from your last run (cached — no LLM call)" if cached else "fresh from the LLM"
    lines = [f"Suggested roles — {len(shown)} of {len(roles)} ({source})", ""]
    for index, role in enumerate(shown, start=1):
        types = ", ".join(role.typical_employment_types)
        lines.append(f"{index:>3}. {role.title_de}  ({role.title_en})")
        lines.append(
            f"      German: {role.german_level_typical} · Types: {types} · "
            f"Confidence: {int(round(role.confidence * 100))}%"
        )
        lines.append(f"      Why: {role.why}")
        lines.append(f"      Search: {' · '.join(role.search_keywords)}")
        lines.append("")
    return "\n".join(lines)


def _cmd_suggest_roles(settings: Settings, args, *, _pool_factory=None) -> int:
    from llmpool import PoolExhausted

    from jobfinder.llm.pool import LLMConfigError, build_pool
    from jobfinder.llm.schema import roles_answer_validator
    from jobfinder.profile import load_profile
    from jobfinder.roles import RolesError, stored_suggestions, suggest_roles

    # The cheap path first: stored suggestions need neither her CV nor any keys.
    fresh = False
    roles = None if args.refresh else stored_suggestions(settings)

    if roles is None:
        try:
            resume = load_profile(args.path or settings.pool_path)
        except ProfileError as exc:
            print(exc)
            return 1

        pool_factory = _pool_factory or (lambda: build_pool(settings, roles_answer_validator))
        try:
            pool = pool_factory()
            roles, fresh = suggest_roles(settings, resume, pool, refresh=args.refresh)
        except LLMConfigError as exc:
            print(exc)
            return 1
        except RolesError as exc:
            print(exc)
            return 1
        except PoolExhausted as exc:
            print(f"LLM quota spent: {exc}")
            print("Wait for a free-tier window, add another key to .env, or retry later.")
            return 1

    if args.json:
        print(json.dumps([asdict(role) for role in roles], ensure_ascii=False, indent=2))
        return 0

    print(_render_roles_table(roles, cached=not fresh, top=args.top))
    return 0


DEFAULT_CITIES = ("Neuburg an der Donau", "Ingolstadt", "München")
DEFAULT_TYPES = ("werkstudent", "minijob", "parttime")


def _comma_list(raw: str | None) -> list[str]:
    return [part.strip() for part in (raw or "").split(",") if part.strip()]


def _build_search_spec(args):
    from dataclasses import replace

    from jobfinder.search_spec import SearchSpec

    spec = SearchSpec.build(
        mode="general",
        employment_types=_comma_list(args.types) or list(DEFAULT_TYPES),
        city_names=_comma_list(args.cities) or list(DEFAULT_CITIES),
        keywords=_comma_list(args.keywords),
    )
    if args.radius is not None:
        spec = replace(spec, cities=tuple(city.with_radius(args.radius) for city in spec.cities))
    return spec


def _default_client_factory(settings: Settings, delay_seconds: float):
    """One polite client — the registry gives each adapter its own, paced for its host."""
    from jobfinder.sources.http import PoliteClient

    return PoliteClient(
        cache_dir=settings.data_dir / "http-cache",
        budget=settings.request_budget,
        min_delay=delay_seconds,
    )


def _adapter_factory(settings: Settings, client_factory):
    """Build one leg's adapters — fresh clients, so fresh budgets (§8)."""
    from jobfinder.sources.registry import build_adapters

    return lambda: build_adapters(settings, client_factory).adapters


def _source_label(source: str) -> str:
    from jobfinder.sources.registry import SOURCE_LABELS

    return SOURCE_LABELS.get(source, source)


def _print_page(page, counts, totals) -> None:
    """One line per stored page (§10): a cold cache means minutes of fetching.

    The counts are that page's own — a line reading `Arbeitnow — 116 found`
    because another source had found 116 is worse than no line at all. The
    run's running total goes at the end, where it cannot be misread as this
    source's.
    """
    line = f"  {_source_label(page.source)}, page {page.page} — {counts.found} found, "
    line += f"{counts.new} new"
    if counts.duplicates:
        line += f", {counts.duplicates} already known"
    line += f" · {totals.found} so far"
    print(line, flush=True)  # unflushed output would leave the screen frozen


def _print_leg(leg: int, leg_result, combined) -> None:
    """Say so when a spent budget is being continued rather than ending the run."""
    if leg_result.budget_exhausted:
        print(
            f"  Request budget spent — continuing with a fresh one (round {leg + 1}).",
            flush=True,
        )


def _print_search_summary(
    result, csv_path: Path | None, skipped=(), *, resume_requested: bool = False
) -> None:
    if resume_requested and not result.resumed:
        print("Nothing was interrupted, so a fresh search ran instead.")

    if result.state == "interrupted":
        kept = f"{result.found} jobs found so far ({result.new} new) — all of them are saved."
        print(f"Run interrupted. {kept}")
        print("Continue any time with: jobfinder search --resume")
    elif resume_requested and result.resumed and result.found == 0:
        # The cursor of a finished search points past its last query, so the
        # run really does find nothing. Saying "0 jobs found" reads as failure.
        print("The last search had already finished — there was nothing left to continue.")
        print("Everything it found is in your list.")
    else:
        print(
            f"Search finished: {result.found} jobs found — "
            f"{result.new} new, {result.duplicates} already in your list."
        )
    per_source = getattr(result, "per_source", None) or {}
    if per_source or skipped:
        print("Sources:")
        for source, counts in per_source.items():
            print(f"  {_source_label(source)} — {counts.found} found, {counts.new} new")
        for name, reason in skipped:
            print(f"  {_source_label(name)} — skipped ({reason})")
    if result.legs > 1:
        print(f"It took {result.legs} rounds of requests, continued automatically.")
    if result.errors:
        print("Problems along the way (the rest of the search was kept):")
        for error in result.errors:
            print(f"  - {error}")
    if csv_path is not None:
        print(f"jobs-init.csv: {csv_path}")


def _print_enrichment_progress(done: int, total: int, job) -> None:
    """§10: real counts and the job she is waiting on, never a bare spinner."""
    where = " · ".join(part for part in (job["company"], job["city"]) if part)
    line = f"  {done} of {total} explained — {job['title']}"
    if where:
        line += f" ({where})"
    print(line, flush=True)  # unflushed output would leave the screen frozen


def _print_enrichment_summary(result, csv_path: Path) -> None:
    if result.total == 0:
        print("Every stored job is already explained — nothing to do, nothing spent.")
        print(f"jobs-enriched.csv: {csv_path}")
        return

    print(f"Done: {result.enriched} of {result.total} jobs explained in English.")
    if result.failed:
        print(
            f"  {result.failed} could not be explained this time — they stay on the "
            f"list and the next run picks them up."
        )
    if result.unevidenced_levels:
        print(
            f"  {result.unevidenced_levels} German levels were not actually quoted from "
            f"their ad, so they read 'unclear' rather than a number you cannot check."
        )
    if result.errors:
        # Printed even when nothing was counted as failed: a worker that died
        # before it sent anything reports here and nowhere else.
        for error in result.errors[:5]:
            print(f"    - {error}")
        if len(result.errors) > 5:
            print(f"    … and {len(result.errors) - 5} more.")
    if result.quota_spent:
        print(
            "The free LLM quota ran out, so the run stopped here. Everything above "
            "is saved — pick up where it stopped with: jobfinder enrich"
        )
    if result.remaining:
        print(f"{result.remaining} jobs are still waiting to be explained.")
    print(f"jobs-enriched.csv: {csv_path}")


def _cmd_enrich(settings: Settings, args, *, _pool_factory=None) -> int:
    """Explain every stored job in English, saving each answer as it lands."""
    from contextlib import closing

    from jobfinder.enrich.runner import run_enrichment
    from jobfinder.llm.pool import LLMConfigError, build_pool
    from jobfinder.llm.schema import enrichment_answer_validator
    from jobfinder.profile import load_profile
    from jobfinder.roles import build_cv_digest
    from jobfinder.store.db import connect, migrate
    from jobfinder.store.enrichment import already_enriched_count, jobs_needing_enrichment
    from jobfinder.store.export import export_jobs_enriched

    try:
        resume = load_profile(args.path or settings.pool_path)
    except ProfileError as exc:
        print(exc)
        return 1

    from jobfinder.llm.prompting import load_prompt

    version = load_prompt("enrich").version

    with closing(connect(settings.db_path)) as connection:
        migrate(connection)
        waiting = len(jobs_needing_enrichment(connection, version, force=args.force))
        if waiting == 0:
            done = already_enriched_count(connection, version)
            if done == 0:
                print("There are no stored jobs yet — run `jobfinder search` first.")
            else:
                print(f"All {done} stored jobs are already explained. Nothing was spent.")
            export_jobs_enriched(connection, settings.jobs_enriched_csv, version)
            print(f"jobs-enriched.csv: {settings.jobs_enriched_csv}")
            return 0

        print(f"{waiting} jobs to explain. Each answer is saved the moment it arrives.")

        pool_factory = _pool_factory or (lambda: build_pool(settings, enrichment_answer_validator))
        try:
            pool = pool_factory()
        except LLMConfigError as exc:
            print(exc)
            return 1

        result = run_enrichment(
            connection,
            pool,
            settings,
            cv_digest=build_cv_digest(resume),
            limit=args.limit,
            force=args.force,
            csv_path=settings.jobs_enriched_csv,
            on_progress=_print_enrichment_progress,
            workers=settings.llm_workers,
            prompt_version=version,
        )
        # The appended file holds arrival order and, after --force, the same job
        # twice. This is the tidy-up pass — one row per job, sorted.
        export_jobs_enriched(connection, settings.jobs_enriched_csv, version)

    _print_enrichment_summary(result, settings.jobs_enriched_csv)
    return 0


CHECK_SPEC_CITY = "Ingolstadt"


def _cmd_sources_check(settings: Settings, args, *, _client_factory=None, _sources=None) -> int:
    """Ask every source one small question and report what it said.

    Scrapers break when a site is redesigned and boards block clients without
    announcing it. This is the honest way to find out which is which, and it
    is deliberately a report: a source saying no is the answer, not an error.
    """
    from jobfinder.search_spec import SearchSpec
    from jobfinder.sources.http import SourceUnavailable
    from jobfinder.sources.registry import build_adapters

    spec = SearchSpec.build(
        mode="general", employment_types=["minijob"], city_names=[CHECK_SPEC_CITY]
    )
    if _sources is not None:
        adapters, skipped = _sources
    else:
        built = build_adapters(settings, _client_factory or _default_client_factory)
        adapters, skipped = built.adapters, built.skipped

    print(f"Asking each source for minijobs in {CHECK_SPEC_CITY}:")
    for adapter in adapters:
        label = _source_label(adapter.source)
        try:
            page = next(iter(adapter.search_pages(spec)), None)
            found = len(page.postings) if page is not None else 0
            if found:
                print(f"  {label} — answers, {found} jobs on the first page")
            else:
                # Two very different things look identical from here.
                print(
                    f"  {label} — answers, no jobs matched. Either nothing is listed "
                    f"for that search, or the adapter has drifted — re-record its "
                    f"fixture to find out which."
                )
        except SourceUnavailable as err:
            print(f"  {label} — no answer ({err})")
        except Exception as err:  # a broken adapter is a finding, not a crash
            print(f"  {label} — broken ({type(err).__name__}: {err})")
    for name, reason in skipped:
        print(f"  {_source_label(name)} — off ({reason})")
    return 0


def _start_companion(settings: Settings, args, *, _pool_factory=None):
    """Build the second worker for `search --enrich`, or explain why it cannot.

    Returns `(companion, exit_code)`: a started companion and None, or None and
    the code to exit with. Her CV and the LLM keys are checked here, before a
    single request goes out — a search that runs for ten minutes and then finds
    it cannot enrich anything has wasted her evening.
    """
    from jobfinder.enrich.companion import EnrichmentCompanion
    from jobfinder.llm.pool import LLMConfigError, build_pool
    from jobfinder.llm.schema import enrichment_answer_validator
    from jobfinder.profile import load_profile
    from jobfinder.roles import build_cv_digest

    try:
        resume = load_profile(args.path or settings.pool_path)
    except ProfileError as exc:
        print(exc)
        return None, 1

    pool_factory = _pool_factory or (lambda: build_pool(settings, enrichment_answer_validator))
    try:
        pool = pool_factory()
    except LLMConfigError as exc:
        print(exc)
        return None, 1

    companion = EnrichmentCompanion(
        settings.db_path,
        pool,
        settings,
        cv_digest=build_cv_digest(resume),
        csv_path=settings.jobs_enriched_csv,
        on_progress=_print_enrichment_progress,
        workers=settings.llm_workers,
    )
    companion.start()
    print("Explaining jobs in English as they arrive, while the search runs.")
    return companion, None


def _cmd_search(
    settings: Settings, args, *, _runner=None, _client_factory=None, _pool_factory=None
) -> int:
    from jobfinder.search import run_search_until_done
    from jobfinder.search_spec import SearchSpecError
    from jobfinder.store.db import connect, migrate

    try:
        spec = _build_search_spec(args)
    except (SearchSpecError, ValueError) as exc:  # resolve_city speaks ValueError
        print(exc)
        return 1

    if args.dry_run:
        from jobfinder.sources.ba import build_queries

        print("Dry run — no requests sent, nothing stored.")
        print("The Bundesagentur search would fetch:")
        for index, query in enumerate(build_queries(spec), start=1):
            print(f"  {index}. {query.url()}")
        print("Each URL is fetched page by page (size=50) until the source's total is reached.")
        return 0

    client_factory = _client_factory or _default_client_factory
    runner = _runner or run_search_until_done

    from contextlib import closing

    from jobfinder.sources.registry import skipped_sources

    companion = None
    if args.enrich:
        # The schema first, on one connection alone: two connections racing to
        # switch a brand-new file to WAL is a fight only one of them can win.
        with closing(connect(settings.db_path)) as connection:
            migrate(connection)
        # Then her CV and a usable pool — checked before the first request, so
        # a ten-minute search cannot end by discovering it could not enrich.
        companion, failure = _start_companion(settings, args, _pool_factory=_pool_factory)
        if companion is None:
            return failure

    try:
        with closing(connect(settings.db_path)) as connection:
            migrate(connection)
            result = runner(
                connection,
                _adapter_factory(settings, client_factory),
                spec,
                resume=args.resume,
                csv_path=settings.jobs_init_csv,
                max_legs=settings.max_search_legs,
                on_page=_print_page,
                on_leg=_print_leg,
                # Lets the runner give each source its own thread and its own
                # connection — §8 rule 2, and the reason four scrapers cost the
                # slowest one rather than the sum of them.
                db_path=settings.db_path,
            )
    finally:
        # Even a failed search leaves stored jobs behind, and the answers the
        # companion already wrote are hers to keep.
        enrichment = companion.finish() if companion is not None else None

    _print_search_summary(
        result,
        settings.jobs_init_csv,
        skipped=skipped_sources(settings),
        resume_requested=args.resume,
    )
    if enrichment is not None:
        with closing(connect(settings.db_path)) as connection:
            from jobfinder.llm.prompting import load_prompt
            from jobfinder.store.export import export_jobs_enriched

            export_jobs_enriched(
                connection, settings.jobs_enriched_csv, load_prompt("enrich").version
            )
        _print_enrichment_summary(enrichment, settings.jobs_enriched_csv)
    return 0


def _uvicorn_serve(app, *, host: str, port: int, on_ready) -> None:
    """Run the server; `on_ready` fires once it is listening.

    `callback_notify` is uvicorn's own heartbeat, invoked from the main loop
    after startup — the first tick is the earliest honest moment to open a
    browser tab at it.
    """
    import uvicorn

    uvicorn.run(app, host=host, port=port, callback_notify=on_ready, timeout_notify=0.25)


def _cmd_serve(settings: Settings, args, *, _serve=None, _browser=None) -> int:
    """Start the app and open her browser at it (§10: one double-click)."""
    import webbrowser

    from jobfinder.web.app import SERVER_HOST, create_app

    serve = _serve or _uvicorn_serve
    open_browser = _browser or webbrowser.open
    url = f"http://{SERVER_HOST}:{args.port}"

    def open_when_ready() -> None:
        if not args.no_browser:
            open_browser(url)

    serve(create_app(settings), host=SERVER_HOST, port=args.port, on_ready=open_when_ready)
    return 0


def main(
    argv: list[str] | None = None,
    *,
    _run_doctor=None,
    _pool_factory=None,
    _runner=None,
    _client_factory=None,
    _sources=None,
    _serve=None,
    _browser=None,
) -> int:
    parser = argparse.ArgumentParser(prog="jobfinder", description="Local job-search assistant")
    sub = parser.add_subparsers(dest="command", required=True)

    profile = sub.add_parser("profile", help="validate and show her CV")
    profile.add_argument("action", choices=["validate", "show"])
    profile.add_argument(
        "--path", type=Path, default=None, help="path to pool.yaml (default: ./pool.yaml)"
    )

    llm = sub.add_parser("llm", help="LLM backend health")
    llm.add_argument("action", choices=["doctor"])
    llm.add_argument(
        "--root", type=Path, default=None, help="project root (default: current directory)"
    )

    suggest = sub.add_parser("suggest-roles", help="job titles worth searching for")
    suggest.add_argument("--root", type=Path, default=None, help="project root")
    suggest.add_argument("--path", type=Path, default=None, help="path to pool.yaml")
    suggest.add_argument("--json", action="store_true", help="print JSON instead of a table")
    suggest.add_argument("--top", type=int, default=None, help="show only the first N roles")
    suggest.add_argument(
        "--refresh", action="store_true", help="ignore stored suggestions and re-ask"
    )

    sources = sub.add_parser("sources", help="check which sources still answer")
    sources.add_argument("action", choices=["check"])
    sources.add_argument("--root", type=Path, default=None, help="project root")

    enrich = sub.add_parser("enrich", help="explain the stored jobs in English")
    enrich.add_argument("--root", type=Path, default=None, help="project root")
    enrich.add_argument("--path", type=Path, default=None, help="path to pool.yaml")
    enrich.add_argument("--limit", type=int, default=None, help="explain at most N jobs this run")
    enrich.add_argument(
        "--force",
        action="store_true",
        help="explain jobs again even when they already have an answer",
    )

    search = sub.add_parser("search", help="collect jobs into jobs-init.csv")
    search.add_argument("--root", type=Path, default=None, help="project root")
    search.add_argument(
        "--cities",
        default=None,
        help=f"comma-separated cities (default: {', '.join(DEFAULT_CITIES)})",
    )
    search.add_argument(
        "--types",
        default=None,
        help=f"comma-separated employment types (default: {', '.join(DEFAULT_TYPES)})",
    )
    search.add_argument("--keywords", default=None, help="comma-separated search keywords")
    search.add_argument(
        "--radius",
        type=int,
        default=None,
        help="search radius in km for all cities",
    )
    search.add_argument(
        "--dry-run", action="store_true", help="print the exact URLs, send nothing, store nothing"
    )
    search.add_argument("--resume", action="store_true", help="continue the newest interrupted run")
    search.add_argument(
        "--enrich",
        action="store_true",
        help="explain jobs in English as the search stores them",
    )
    search.add_argument("--path", type=Path, default=None, help="path to pool.yaml (with --enrich)")

    serve = sub.add_parser("serve", help="open the app in your browser")
    serve.add_argument("--root", type=Path, default=None, help="project root (default: cwd)")
    serve.add_argument("--port", type=int, default=8000, help="port to listen on (default: 8000)")
    serve.add_argument(
        "--no-browser", action="store_true", help="start the server without opening a browser"
    )

    args = parser.parse_args(argv)

    if args.command == "profile":
        path = args.path or _default_pool_path()
        if args.action == "validate":
            return _cmd_profile_validate(path)
        return _cmd_profile_show(path)

    if args.command == "llm":
        settings = Settings.load(args.root or Path.cwd())
        return _cmd_llm_doctor(settings, _run_doctor=_run_doctor)

    if args.command == "suggest-roles":
        settings = Settings.load(args.root or Path.cwd())
        return _cmd_suggest_roles(settings, args, _pool_factory=_pool_factory)

    if args.command == "sources":
        settings = Settings.load(args.root or Path.cwd())
        return _cmd_sources_check(
            settings, args, _client_factory=_client_factory, _sources=_sources
        )

    if args.command == "enrich":
        settings = Settings.load(args.root or Path.cwd())
        return _cmd_enrich(settings, args, _pool_factory=_pool_factory)

    if args.command == "search":
        settings = Settings.load(args.root or Path.cwd())
        return _cmd_search(
            settings,
            args,
            _runner=_runner,
            _client_factory=_client_factory,
            _pool_factory=_pool_factory,
        )

    if args.command == "serve":
        settings = Settings.load(args.root or Path.cwd())
        return _cmd_serve(settings, args, _serve=_serve, _browser=_browser)

    parser.error(f"unknown command {args.command!r}")  # pragma: no cover
    return 2  # pragma: no cover
