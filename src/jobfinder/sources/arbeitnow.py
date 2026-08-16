"""Arbeitnow job-board API — free, keyless, Germany-wide (and beyond).

Facts verified live 2026-08-16 (see the Phase 5 plan): one endpoint, `?page=N`
pagination of 175-entry pages ordered newest first, and **no server-side
filter** for city, employment type or keyword — everything is filtered
client-side on one walk over the pages. Locations are free text ("München",
but also "Munich Office" and "London"), so the city match is exact on the
canonical name and nothing fuzzier.

Employment types stay alternatives here too (Phase 4 audit): a posting passes
when it signals **any** of her selected types, through `job_types` (messy
free text: "Working student", "Part time", "Full-time", "fulltime permanent"…)
or through the title's German wording — the real page's München Werkstudent
ads carry no "working student" job_type at all, only the title word.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from jobfinder.sources.base import PageResult, RawPosting
from jobfinder.sources.extract import extract_readable_text

if TYPE_CHECKING:
    from jobfinder.search_spec import SearchSpec

BASE_URL = "https://www.arbeitnow.com/api/job-board-api"

# `links.last` is null and there is no total, so a full walk is unbounded.
# The cap rides on top of the request budget (§8: request count is the scarce
# resource) and covers the newest ~1 750 postings.
MAX_PAGES = 10

# Substrings over the normalised `job_types` text. The vocabulary is curated
# by Arbeitnow (no "international" lurking), so plain substrings are safe.
_JOB_TYPE_TERMS = {
    "werkstudent": ("working student", "werkstudent", "student"),
    "internship": ("intern", "praktikum", "trainee"),
    "parttime": ("part time", "teilzeit"),
    "fulltime": ("full time", "vollzeit"),
}

# Substrings over the title, casefolded — the same idea as the BA adapter's
# title hints. "intern" is deliberately absent: "International Sales" is not
# an internship.
_TITLE_TERMS = {
    "werkstudent": ("werkstudent", "studentische hilfskraft"),
    "internship": ("praktikum", "internship", "praktikant"),
    "parttime": ("teilzeit",),
    "fulltime": ("vollzeit",),
}

# Minijob has no job_type and no API flag — only the wording (Phase 6's list).
_MINIJOB_TITLE_WORDS = ("minijob", "450 €", "520 €", "geringfügig", "geringfuegig", "aushilfe")


def _normalize_types(job_types) -> str:
    """One comparable blob: casefolded, hyphens spaced, glued words split."""
    joined = " ".join(job_types or []).casefold()
    joined = joined.replace("-", " ").replace("fulltime", "full time")
    joined = joined.replace("parttime", "part time")
    return " ".join(joined.split())


def _signals(entry: dict) -> set[str]:
    """Every employment type this entry signals, from job_types or title."""
    types_blob = _normalize_types(entry.get("job_types"))
    title = (entry.get("title") or "").casefold()
    signals: set[str] = set()
    for employment_type, terms in _JOB_TYPE_TERMS.items():
        if any(term in types_blob for term in terms):
            signals.add(employment_type)
        elif any(term in title for term in _TITLE_TERMS[employment_type]):
            signals.add(employment_type)
    if any(word in title for word in _MINIJOB_TITLE_WORDS):
        signals.add("minijob")
    return signals


def parse_entry(entry: dict) -> RawPosting | None:
    """One `data[]` entry into a RawPosting — or None when it has no identity."""
    slug = entry.get("slug")
    if not slug:
        return None  # without a slug the job cannot be stored or re-found
    signals = _signals(entry)
    description = extract_readable_text(entry.get("description") or "")
    created_at = entry.get("created_at")
    return RawPosting(
        job_id=f"AN:{slug}",
        source="AN",
        source_id=slug,
        title=entry.get("title") or "",
        company=entry.get("company_name"),
        city=entry.get("location"),
        employment_type_raw=", ".join(entry.get("job_types") or []) or None,
        is_minijob="minijob" in signals,
        is_parttime="parttime" in signals,
        is_fulltime="fulltime" in signals,
        is_internship="internship" in signals,
        is_werkstudent="werkstudent" in signals,
        homeoffice=bool(entry.get("remote")),
        published_at=(
            datetime.fromtimestamp(created_at, tz=UTC).isoformat() if created_at else None
        ),
        apply_url=entry.get("url"),
        source_url=entry.get("url"),
        description=description,
    )


def parse_page(payload: dict) -> list[RawPosting]:
    """Every parsable entry on one page — filtering is a separate concern."""
    return [posting for entry in payload.get("data") or [] if (posting := parse_entry(entry))]


def entry_matches(entry: dict, spec: SearchSpec) -> bool:
    """Her city, employment-type and keyword filters — all client-side."""
    location = (entry.get("location") or "").strip().casefold()
    if location not in {city.name.casefold() for city in spec.cities}:
        return False
    if spec.employment_types and not _signals(entry) & set(spec.employment_types):
        return False  # types are alternatives: matching any one is enough
    if spec.keywords:
        haystack = " ".join([entry.get("title") or "", *(entry.get("tags") or [])]).casefold()
        if not any(keyword.casefold() in haystack for keyword in spec.keywords):
            return False
    return True


def postings_for_spec(payload: dict, spec: SearchSpec) -> list[RawPosting]:
    """One page's entries, filtered to her spec, parsed into postings."""
    return [
        posting
        for entry in payload.get("data") or []
        if entry_matches(entry, spec) and (posting := parse_entry(entry))
    ]


class ArbeitnowApi:
    """SourceAdapter over the job-board API. Source code: `AN`."""

    source = "AN"

    def __init__(self, client):
        self._client = client

    def search(self, spec: SearchSpec):
        for page in self.search_pages(spec):
            yield from page.postings

    def search_pages(self, spec: SearchSpec, *, start_query_index: int = 0, start_page: int = 1):
        """One walk over the newest pages, filtered client-side as they land."""
        if start_query_index > 0:
            return  # the only query already finished before the interruption
        page = max(1, start_page)
        for _ in range(MAX_PAGES):
            payload = self._client.get_json(BASE_URL, params={"page": page})
            if not (payload.get("data") or []):
                break  # past the end — Arbeitnow answers empty pages
            yield PageResult(
                source=self.source,
                query_index=0,
                page=page,
                postings=postings_for_spec(payload, spec),
            )
            if not (payload.get("links") or {}).get("next"):
                break  # the last page says so
            page += 1

    def fetch_detail(self, posting: RawPosting) -> RawPosting:
        """The listing already carries the description — nothing to fetch."""
        return posting
