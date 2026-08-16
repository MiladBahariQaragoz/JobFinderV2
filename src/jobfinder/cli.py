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


def _default_client_factory(settings: Settings):
    """One polite client — the registry gives each adapter its own."""
    from jobfinder.sources.http import PoliteClient

    return PoliteClient(cache_dir=settings.data_dir / "http-cache", budget=settings.request_budget)


def _adapter_factory(settings: Settings, client_factory):
    """Build one leg's adapters — fresh clients, so fresh budgets (§8)."""
    from jobfinder.sources.registry import build_adapters

    return lambda: build_adapters(settings, client_factory).adapters


def _print_search_summary(result, csv_path: Path | None, skipped=()) -> None:
    if result.state == "interrupted":
        kept = f"{result.found} jobs found so far ({result.new} new) — all of them are saved."
        print(f"Run interrupted. {kept}")
        print("Continue any time with: jobfinder search --resume")
    else:
        print(
            f"Search finished: {result.found} jobs found — "
            f"{result.new} new, {result.duplicates} already in your list."
        )
    per_source = getattr(result, "per_source", None) or {}
    if per_source or skipped:
        from jobfinder.sources.registry import SOURCE_LABELS

        print("Sources:")
        for source, counts in per_source.items():
            print(f"  {SOURCE_LABELS.get(source, source)} — {counts.found} found, {counts.new} new")
        for name, reason in skipped:
            print(f"  {SOURCE_LABELS.get(name, name)} — skipped ({reason})")
    if result.legs > 1:
        print(f"It took {result.legs} rounds of requests, continued automatically.")
    if result.errors:
        print("Problems along the way (the rest of the search was kept):")
        for error in result.errors:
            print(f"  - {error}")
    if csv_path is not None:
        print(f"jobs-init.csv: {csv_path}")


def _cmd_search(settings: Settings, args, *, _runner=None, _client_factory=None) -> int:
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

    with closing(connect(settings.db_path)) as connection:
        migrate(connection)
        result = runner(
            connection,
            _adapter_factory(settings, client_factory),
            spec,
            resume=args.resume,
            csv_path=settings.jobs_init_csv,
            max_legs=settings.max_search_legs,
        )
    _print_search_summary(result, settings.jobs_init_csv, skipped=skipped_sources(settings))
    return 0


def main(
    argv: list[str] | None = None,
    *,
    _run_doctor=None,
    _pool_factory=None,
    _runner=None,
    _client_factory=None,
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

    if args.command == "search":
        settings = Settings.load(args.root or Path.cwd())
        return _cmd_search(settings, args, _runner=_runner, _client_factory=_client_factory)

    parser.error(f"unknown command {args.command!r}")  # pragma: no cover
    return 2  # pragma: no cover
