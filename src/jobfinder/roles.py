"""Role recommendations: her CV in, job titles worth searching for, in German.

This is the first feature she sees working. The CV digest sent to the model is
skills, education, experience and languages — never her name, address, phone or
email. Answers are cached and stored, so a second run is instant and free.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from jobfinder.config import Settings
from jobfinder.llm.cache import LLMCache, cache_key, complete_json_cached, fingerprint
from jobfinder.llm.prompting import load_prompt
from jobfinder.llm.schema import ROLES_SPEC, roles_answer_validator
from jobfinder.profile import Resume


class RolesError(Exception):
    """One actionable sentence about why role suggestions cannot run."""


@dataclass(frozen=True)
class Role:
    title_de: str
    title_en: str
    why: str
    search_keywords: tuple[str, ...]
    typical_employment_types: tuple[str, ...]
    german_level_typical: str
    confidence: float


def build_cv_digest(resume: Resume) -> str:
    """The parts of her CV the model may see — skills, education, experience, languages.

    Everything identifying (name, email, phone, address, links) is left out;
    a test holds that line, not a promise.
    """
    sections: list[str] = []

    if resume.skill_groups:
        sections.append("# Skills")
        for name, items in resume.skill_groups.items():
            sections.append(f"- {name}: {', '.join(items)}")

    if resume.education:
        sections.append("# Education")
        for entry in resume.education:
            sections.append(f"- {entry.degree}, {entry.org} ({entry.start} to {entry.end})")

    if resume.experience:
        sections.append("# Experience")
        for job in resume.experience:
            line = f"- {job.role} at {job.org} ({job.start} to {job.end})"
            if job.skills:
                line += f" — skills: {', '.join(job.skills)}"
            sections.append(line)
            sections.extend(f"  - {bullet}" for bullet in job.bullets)

    if resume.languages:
        sections.append("# Languages")
        sections.extend(f"- {lang.name}: {lang.level}" for lang in resume.languages)

    return "\n".join(sections)


def stored_suggestions(settings: Settings) -> list[Role] | None:
    """Roles from the last successful run — no CV, no pool, no LLM call."""
    storage = settings.suggested_roles_path
    if not storage.exists():
        return None
    return _load_stored(storage)


def suggest_roles(
    settings: Settings, resume: Resume, pool, *, refresh: bool = False
) -> tuple[list[Role], bool]:
    """Suggest roles; returns ``(roles, fresh)`` — fresh=False means no LLM call.

    Stored suggestions answer first, then the content-hash cache; only a miss
    reaches the pool. ``refresh=True`` skips the stored file (not the cache).
    """
    storage = settings.suggested_roles_path
    if not refresh and storage.exists():
        roles = _load_stored(storage)
        if roles is not None:
            return roles, False

    if not (resume.skill_groups or resume.experience or resume.education):
        raise RolesError(
            "Your pool.yaml has no skills, experience or education yet — add at "
            "least one skill group or job first (`jobfinder profile validate` "
            "shows what is there). Nothing was sent to the LLM."
        )

    digest = build_cv_digest(resume)
    spec = load_prompt("roles")
    key = cache_key(
        spec.version,
        hashlib.sha1(digest.encode("utf-8")).hexdigest(),
        fingerprint({name: asdict(rule) for name, rule in ROLES_SPEC.items()}),
    )
    prompt = f"{spec.text}\n\n---\n\nCV DIGEST:\n\n{digest}"

    with LLMCache(settings.llm_cache_path) as cache:
        answer = cache.get(key)
        fresh = answer is None  # fresh means: a provider call had to be made
        if fresh:
            answer = complete_json_cached(pool, cache, prompt=prompt, key=key)

    ok, reason = roles_answer_validator(answer)
    if not ok:
        raise RolesError(
            f"The model's answer was not usable ({reason}). "
            "Run again in a moment — the pool will try another provider."
        )

    roles = [_normalise_role(raw) for raw in answer["roles"]]
    _store(storage, spec.version, roles)
    return roles, fresh


def _normalise_role(raw: dict) -> Role:
    """Coerce a validated answer into a Role: keywords deduped and lowercased."""
    keywords: list[str] = []
    for keyword in raw["search_keywords"]:
        cleaned = str(keyword).strip().lower()
        if cleaned and cleaned not in keywords:
            keywords.append(cleaned)
    return Role(
        title_de=str(raw["title_de"]).strip(),
        title_en=str(raw["title_en"]).strip(),
        why=str(raw["why"]).strip(),
        search_keywords=tuple(keywords),
        typical_employment_types=tuple(raw["typical_employment_types"]),
        german_level_typical=str(raw["german_level_typical"]),
        confidence=float(raw["confidence"]),
    )


def _load_stored(storage) -> list[Role] | None:
    try:
        payload = json.loads(storage.read_text(encoding="utf-8"))
        return [_normalise_role(raw) for raw in payload["roles"]]
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None  # corrupt or foreign file: re-run instead of crashing


def _store(storage, prompt_version: str, roles: list[Role]) -> None:
    """Write atomically — a crash mid-write must not destroy the previous file."""
    storage.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "prompt_version": prompt_version,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "roles": [asdict(role) for role in roles],
    }
    tmp = storage.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
    os.replace(tmp, storage)
