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


def main(argv: list[str] | None = None, *, _run_doctor=None, _pool_factory=None) -> int:
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

    parser.error(f"unknown command {args.command!r}")  # pragma: no cover
    return 2  # pragma: no cover
