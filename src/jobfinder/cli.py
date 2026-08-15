"""Command-line entry points.

Every command prints for her, not for a developer: one sentence per problem,
plain summaries on success. Failures exit 1 with a message she can act on —
never a traceback.
"""

from __future__ import annotations

import argparse
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jobfinder", description="Local job-search assistant")
    sub = parser.add_subparsers(dest="command", required=True)

    profile = sub.add_parser("profile", help="validate and show her CV")
    profile.add_argument("action", choices=["validate", "show"])
    profile.add_argument(
        "--path", type=Path, default=None, help="path to pool.yaml (default: ./pool.yaml)"
    )

    args = parser.parse_args(argv)

    if args.command == "profile":
        path = args.path or _default_pool_path()
        if args.action == "validate":
            return _cmd_profile_validate(path)
        return _cmd_profile_show(path)

    parser.error(f"unknown command {args.command!r}")  # pragma: no cover
    return 2  # pragma: no cover
