"""Read-only queries for the web layer: her list, her job, her options.

One module decides what the pages show. German level and fit score live
inside `enrichment.answer` as JSON, so the filters that need them use
`json_extract` in SQL — the store is 674 rows today and 1 000 is the stated
bar, which is a long way below the size where parsing answers in Python per
request stops being fast.

The CEFR rank in SQL is a CASE, not a function, because SQLite has no
built-in one and the web layer ships no custom connection.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from jobfinder.cities import resolve_city
from jobfinder.config import Settings

GERMAN_ORDER = {"none": 0, "A1": 1, "A2": 2, "B1": 3, "B2": 4, "C1": 5, "C2": 6}
EMPLOYMENT_TYPES = {
    "minijob": "is_minijob",
    "werkstudent": "is_werkstudent",
    "parttime": "is_parttime",
    "fulltime": "is_fulltime",
    "internship": "is_internship",
}
STATUSES = ("new", "interested", "applied", "rejected", "deleted")
SORTS = ("fit", "date", "distance")
PAGE_SIZE = 50
# Cross-cutting concern: a posting none of her searches has seen in two weeks
# is probably dead; it stays in the list, greyed, never hidden.
STALE_AFTER_DAYS = 14

# §1: her base. Distances on the list are "from home", which is here.
HOME_CITY = resolve_city("Neuburg an der Donau")

_SQL_LEVEL = "json_extract(e.answer, '$.german_level')"
_SQL_FIT = "json_extract(e.answer, '$.fit_score')"
_SQL_LEVEL_RANK = (
    "CASE {column} WHEN 'none' THEN 0 WHEN 'A1' THEN 1 WHEN 'A2' THEN 2"
    " WHEN 'B1' THEN 3 WHEN 'B2' THEN 4 WHEN 'C1' THEN 5 WHEN 'C2' THEN 6 ELSE -1 END"
)


@dataclass(frozen=True)
class JobFilters:
    """What she asked for, already validated — invalid input never reaches SQL.

    The four categorical filters hold **sets**: she can reach Ingolstadt and
    Munich, and she will take a minijob or a Werkstudent contract, so asking
    for one at a time was the wrong question. Empty means no filter. The query
    parameter names are unchanged and simply repeat (`?city=A&city=B`), so an
    old single-value link still means what it always did.
    """

    cities: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    types: tuple[str, ...] = ()
    max_german: str | None = None
    min_fit: int | None = None
    statuses: tuple[str, ...] = ()  # empty = everything except deleted
    sort: str = "fit"
    page: int = 1


def _picked(params, key: str, valid=None) -> tuple[str, ...]:
    """Every value she gave for one parameter, de-duplicated, order kept.

    Anything not in `valid` is dropped rather than raising: a stale link with
    a since-renamed value should still show her a list.
    """
    getlist = getattr(params, "getlist", None)
    values = list(getlist(key)) if getlist else _as_list(params.get(key))
    seen: dict[str, None] = {}
    for value in values:
        value = value.strip()
        if value and (valid is None or value in valid):
            seen.setdefault(value, None)
    return tuple(seen)


def _as_list(value) -> list[str]:
    if value is None:
        return []
    return list(value) if isinstance(value, list) else [value]


def _places(values) -> str:
    """`?, ?, ?` for an IN clause — the values themselves stay bound."""
    return ", ".join("?" for _ in values)


def parse_filters(params) -> JobFilters:
    """Query params → validated filters. Anything unparseable is dropped —
    a bad value in a URL is a stale link, not a reason to 500."""
    cities = _picked(params, "city")
    sources = _picked(params, "source")
    types = _picked(params, "type", EMPLOYMENT_TYPES)
    statuses = _picked(params, "status", STATUSES)
    max_german = params.get("max_german") or None
    sort = params.get("sort") or "fit"

    if max_german not in GERMAN_ORDER:
        max_german = None
    if sort not in SORTS:
        sort = "fit"

    try:
        min_fit = int(params.get("min_fit", ""))
        min_fit = min_fit if 0 <= min_fit <= 100 else None
    except ValueError:
        min_fit = None

    try:
        page = max(1, int(params.get("page", "1")))
    except ValueError:
        page = 1

    return JobFilters(
        cities=cities,
        sources=sources,
        types=types,
        max_german=max_german,
        min_fit=min_fit,
        statuses=statuses,
        sort=sort,
        page=page,
    )


def current_prompt_version() -> str:
    """The version the pages read answers at — one place, one prompt file."""
    from jobfinder.llm.prompting import load_prompt

    return load_prompt("enrich").version


def her_german_level(settings: Settings) -> str:
    """Her comfortable German level, for the three-step scale.

    Read from her `pool.yaml` when it parses; `A2` when it does not (§1 says
    limited German — an optimistic default would mark jobs comfortable that
    are not).
    """
    try:
        from jobfinder.profile import load_profile

        resume = load_profile(settings.pool_path)
    except Exception:  # no CV, or one that does not parse — the UI still works
        return "A2"
    for language in resume.languages:
        if "german" in language.name.lower() or "deutsch" in language.name.lower():
            if language.normalized in GERMAN_ORDER:
                return language.normalized
    return "A2"


def german_tier(level: str | None, her_level: str) -> str:
    """comfortable / stretch / out — the §10 three-step scale.

    `unknown` (no answer, or `unclear`) is its own state: the page says the
    ad does not say, which is the honest answer, not a guess dressed as one.
    """
    if level not in GERMAN_ORDER:
        return "unknown"
    mine = GERMAN_ORDER[her_level if her_level in GERMAN_ORDER else "A2"]
    rank = GERMAN_ORDER[level]
    if rank == 0 or rank <= mine:
        return "comfortable"
    if rank == mine + 1:
        return "stretch"
    return "out"


def distance_km(lat: float | None, lon: float | None) -> int | None:
    """Whole kilometres from her home city, the way the crow flies."""
    if lat is None or lon is None:
        return None
    from math import asin, cos, radians, sin, sqrt

    lat1, lon1, lat2, lon2 = map(radians, (HOME_CITY.lat, HOME_CITY.lon, lat, lon))
    a = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return round(2 * 6371.0 * asin(sqrt(a)))


def list_jobs(
    connection: sqlite3.Connection,
    filters: JobFilters,
    *,
    prompt_version: str | None = None,
    her_level: str = "A2",
) -> tuple[list[dict[str, Any]], int]:
    """The visible jobs for one filter set, plus how many matched in total.

    Rows come back as dicts with the list page's extra fields already on
    them: `german_level`, `fit_score`, `distance_km`, `tier`, `stale`.
    """
    version = prompt_version or current_prompt_version()
    where: list[str] = []
    parameters: list[Any] = [version]

    if filters.statuses:
        where.append(f"COALESCE(s.status, 'new') IN ({_places(filters.statuses)})")
        parameters.extend(filters.statuses)
    else:
        where.append("COALESCE(s.status, 'new') != 'deleted'")

    if filters.cities:
        where.append(f"j.city IN ({_places(filters.cities)})")
        parameters.extend(filters.cities)
    if filters.sources:
        where.append(f"j.source IN ({_places(filters.sources)})")
        parameters.extend(filters.sources)
    if filters.types:
        # Types are alternatives, never a stack: a job matching any one of the
        # contracts she will take belongs in the list (Phase 4 learned the same
        # thing about the BA's query parameters).
        columns = " OR ".join(f"j.{EMPLOYMENT_TYPES[name]} = 1" for name in filters.types)
        where.append(f"({columns})")
    if filters.max_german is not None:
        # A bound she set is a promise: `unclear` and unanswered jobs cannot
        # keep it, so they are excluded — and the empty state says so. The
        # expression is inlined because SQLite resolves WHERE before aliases.
        rank = _SQL_LEVEL_RANK.format(column=_SQL_LEVEL)
        where.append(f"{rank} BETWEEN 0 AND ?")
        parameters.append(GERMAN_ORDER[filters.max_german])
    if filters.min_fit is not None:
        where.append(f"{_SQL_FIT} IS NOT NULL AND {_SQL_FIT} >= ?")
        parameters.append(filters.min_fit)

    clause = ("WHERE " + " AND ".join(where)) if where else ""
    base = (
        "FROM jobs j"
        " LEFT JOIN status s ON s.job_id = j.job_id"
        " LEFT JOIN enrichment e ON e.job_id = j.job_id AND e.prompt_version = ?"
        f" {clause}"
    )
    select = (
        ", ".join(
            f"j.{column}"
            for column in (
                "job_id",
                "title",
                "company",
                "city",
                "plz",
                "lat",
                "lon",
                "source",
                "employment_type_raw",
                "is_minijob",
                "is_werkstudent",
                "is_parttime",
                "is_fulltime",
                "is_internship",
                "homeoffice",
                "published_at",
                "apply_url",
                "source_url",
                "also_seen_on",
                "first_seen_at",
                "last_seen_at",
            )
        )
        + ", COALESCE(s.status, 'new') AS status"
        ", json_extract(e.answer, '$.german_level') AS lvl"
        ", json_extract(e.answer, '$.fit_score') AS fit"
        ", json_extract(e.answer, '$.summary_en') AS summary_en"
    )

    total = connection.execute(f"SELECT COUNT(*) {base}", parameters).fetchone()[0]

    if filters.sort == "distance":
        rows = connection.execute(
            f"SELECT {select} {base} ORDER BY j.job_id", parameters
        ).fetchall()
        rows = sorted(
            rows,
            key=lambda row: (
                distance_km(row["lat"], row["lon"]) is None,
                distance_km(row["lat"], row["lon"]) or 0,
            ),
        )
        start = (filters.page - 1) * PAGE_SIZE
        page_rows = rows[start : start + PAGE_SIZE]
    else:
        order = (
            "fit IS NULL, fit DESC, j.last_seen_at DESC"
            if filters.sort == "fit"
            else ("j.published_at IS NULL, j.published_at DESC, j.first_seen_at DESC")
        )
        offset = (filters.page - 1) * PAGE_SIZE
        page_rows = connection.execute(
            f"SELECT {select} {base} ORDER BY {order} LIMIT {PAGE_SIZE} OFFSET {offset}",
            parameters,
        ).fetchall()

    cutoff = (datetime.now(UTC) - timedelta(days=STALE_AFTER_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    jobs = []
    for row in page_rows:
        jobs.append(
            {
                **dict(row),
                "distance_km": distance_km(row["lat"], row["lon"]),
                "tier": german_tier(row["lvl"], her_level),
                "stale": (row["last_seen_at"] or "") < cutoff,
                "type_label": _type_label(row),
            }
        )
    return jobs, total


def _type_label(row: sqlite3.Row | dict) -> str:
    """The contract type in her words — the source flags first (§ Phase 7:
    the BA writes prose here and Adzuna writes nothing), the raw text second."""
    flags = [
        label
        for column, label in (
            ("is_minijob", "minijob"),
            ("is_werkstudent", "werkstudent"),
            ("is_parttime", "part-time"),
            ("is_fulltime", "full-time"),
            ("is_internship", "internship"),
        )
        if row[column]
    ]
    if flags:
        return " / ".join(flags)
    return row["employment_type_raw"] or ""


def describe_filters(filters: JobFilters) -> list[str]:
    """The applied filters in her words — the empty state names them (§10)."""
    parts = []
    if filters.cities:
        parts.append(f"jobs in {_or_list(filters.cities)}")
    if filters.types:
        parts.append(f"{_or_list(filters.types)} positions")
    if filters.max_german is not None:
        parts.append(f"German at most {filters.max_german}")
    if filters.min_fit is not None:
        parts.append(f"fit at least {filters.min_fit}")
    if filters.sources:
        parts.append(f"from {_or_list(filters.sources)}")
    if filters.statuses:
        parts.append(f"marked {_or_list(filters.statuses)}")
    return parts


def _or_list(values: tuple[str, ...]) -> str:
    """`Ingolstadt or München`, `A, B or C` — she picked alternatives, and the
    empty state has to read like the question she asked."""
    if len(values) == 1:
        return values[0]
    return f"{', '.join(values[:-1])} or {values[-1]}"


def filter_options(connection: sqlite3.Connection) -> dict[str, list[str]]:
    """The values the filter dropdowns actually offer: what's in her store."""
    cities = [
        row[0]
        for row in connection.execute(
            "SELECT DISTINCT city FROM jobs WHERE city IS NOT NULL ORDER BY city"
        )
    ]
    sources = [
        row[0] for row in connection.execute("SELECT DISTINCT source FROM jobs ORDER BY source")
    ]
    return {"cities": cities, "sources": sources}


_JOB_PAGE_COLUMNS = (
    "job_id",
    "title",
    "company",
    "city",
    "plz",
    "lat",
    "lon",
    "source",
    "employment_type_raw",
    "is_minijob",
    "is_werkstudent",
    "is_parttime",
    "is_fulltime",
    "is_internship",
    "homeoffice",
    "published_at",
    "apply_url",
    "source_url",
    "also_seen_on",
    "first_seen_at",
    "last_seen_at",
)


def job_detail(
    connection: sqlite3.Connection,
    job_id: str,
    *,
    prompt_version: str | None = None,
    her_level: str = "A2",
) -> dict[str, Any] | None:
    """Everything one job page shows, in one query.

    The answer is read at the **current** prompt version: a job enriched only
    under an older version renders as un-enriched, because that is the truth —
    the ad changed or the prompt did, and Phase 7's skip rule will re-send it.
    """
    version = prompt_version or current_prompt_version()
    row = connection.execute(
        f"SELECT {', '.join(f'j.{column}' for column in _JOB_PAGE_COLUMNS)},"
        " COALESCE(s.status, 'new') AS status, s.notes, s.applied_on,"
        " d.description, e.answer AS answer_json, e.enriched_at"
        " FROM jobs j"
        " LEFT JOIN status s ON s.job_id = j.job_id"
        " LEFT JOIN job_descriptions d ON d.job_id = j.job_id"
        " LEFT JOIN enrichment e ON e.job_id = j.job_id AND e.prompt_version = ?"
        " WHERE j.job_id = ?",
        (version, job_id),
    ).fetchone()
    if row is None:
        return None

    answer = None
    if row["answer_json"]:
        try:
            parsed = json.loads(row["answer_json"])
        except (json.JSONDecodeError, TypeError):
            parsed = None
        answer = parsed if isinstance(parsed, dict) else None

    level = answer.get("german_level") if answer else None
    cutoff = (datetime.now(UTC) - timedelta(days=STALE_AFTER_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    return {
        **{column: row[column] for column in _JOB_PAGE_COLUMNS},
        "status": row["status"],
        "notes": row["notes"],
        "applied_on": row["applied_on"],
        "description": row["description"],
        "enriched_at": row["enriched_at"],
        "answer": answer,
        "german_level": level,
        "tier": german_tier(level, her_level),
        "distance_km": distance_km(row["lat"], row["lon"]),
        "type_label": _type_label(row),
        "stale_days": STALE_AFTER_DAYS,
        "is_stale": (row["last_seen_at"] or "") < cutoff,
    }
