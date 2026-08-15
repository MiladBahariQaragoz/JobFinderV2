"""Bundesagentur für Arbeit Jobsuche — the backbone source.

Parameter values below were verified against the live API on 2026-08-15, not
read from documentation: `wo` must be the canonical umlaut spelling
(`wo=Muenchen` returns zero results silently), `arbeitszeit` codes are the
short forms, and unknown values are dropped rather than rejected. See
docs/superpowers/plans/2026-08-15-phase-4-store-ba-jobs-init.md.
"""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass

from jobfinder.search_spec import SearchSpec

BASE_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service"
SEARCH_URL = f"{BASE_URL}/pc/v6/jobs"
DETAIL_URL = f"{BASE_URL}/pc/v4/jobdetails"

# Public constant the service documents for exactly this kind of client.
API_HEADERS = {"X-API-Key": "jobboerse-jobsuche"}

PAGE_SIZE = 50

# Her employment types that map onto a verified arbeitszeit code.
ARBEITSZEIT_FOR_TYPE = {
    "minijob": "mj",
    "parttime": "tz",
    "fulltime": "vz",
}
# Types the API cannot filter for — they travel as search terms instead.
KEYWORD_FOR_TYPE = {
    "werkstudent": "Werkstudent",
    "internship": "Praktikum",
}


@dataclass(frozen=True)
class BAQuery:
    """One page request to the search endpoint."""

    wo: str
    umkreis: int
    was: str | None = None
    angebotsart: int = 1
    arbeitszeit: tuple[str, ...] = ()
    page: int = 1
    size: int = PAGE_SIZE

    def params(self) -> dict:
        params: dict = {
            "wo": self.wo,
            "umkreis": self.umkreis,
            "angebotsart": self.angebotsart,
            "page": self.page,
            "size": self.size,
        }
        if self.was:
            params["was"] = self.was
        if self.arbeitszeit:
            params["arbeitszeit"] = list(self.arbeitszeit)
        return params

    def url(self) -> str:
        return SEARCH_URL + "?" + urllib.parse.urlencode(self.params(), doseq=True)

    def for_page(self, page: int) -> BAQuery:
        return BAQuery(
            wo=self.wo,
            umkreis=self.umkreis,
            was=self.was,
            angebotsart=self.angebotsart,
            arbeitszeit=self.arbeitszeit,
            page=page,
            size=self.size,
        )


def _search_terms(spec: SearchSpec) -> list[str | None]:
    """One search term per keyword she gave; type keywords are appended modifiers.

    "Werkstudent" and "Praktikum" have no API filter, so they travel in `was`.
    They modify each of her keywords rather than spawning their own queries —
    "Datenanalyse" plus a werkstudent filter means one search, not two — and a
    keyword that already says it is not repeated.
    """
    bases = [keyword.strip() for keyword in spec.keywords if keyword.strip()] or [""]
    modifiers = [
        fallback
        for employment_type, fallback in KEYWORD_FOR_TYPE.items()
        if employment_type in spec.employment_types
    ]
    terms: list[str | None] = []
    for base in bases:
        folded = base.casefold()
        additions = [m for m in modifiers if m.casefold() not in folded]
        parts = [part for part in (base, *additions) if part]
        terms.append(" ".join(parts) or None)
    return terms


def build_queries(spec: SearchSpec) -> list[BAQuery]:
    """One query per search term per city — the exact requests a run will make."""
    codes = tuple(
        ARBEITSZEIT_FOR_TYPE[t] for t in spec.employment_types if t in ARBEITSZEIT_FOR_TYPE
    )
    terms = _search_terms(spec)  # always at least one entry, possibly with was=None
    queries: list[BAQuery] = [
        BAQuery(
            wo=city.name,
            umkreis=city.radius_km,
            was=term,
            arbeitszeit=codes,
        )
        for term in terms
        for city in spec.cities
    ]
    return queries
