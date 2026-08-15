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
from jobfinder.sources.base import RawPosting

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


DETAIL_PAGE_URL = "https://www.arbeitsagentur.de/jobsuche/jobdetail/{ref}"

_WERKSTUDENT_HINTS = ("werkstudent", "studentische hilfskraft", "hiw")
_PRACTIKUM_HINTS = ("praktikum", "internship")


def _title_flags(title: str) -> tuple[bool, bool]:
    folded = (title or "").casefold()
    is_werkstudent = any(hint in folded for hint in _WERKSTUDENT_HINTS)
    is_internship = any(hint in folded for hint in _PRACTIKUM_HINTS)
    return is_werkstudent, is_internship


def parse_page(payload: dict) -> list[RawPosting]:
    """One search page — `ergebnisliste` entries — into raw postings."""
    postings: list[RawPosting] = []
    for entry in payload.get("ergebnisliste") or []:
        reference = entry.get("referenznummer")
        if not reference:
            continue  # an entry without identity cannot be stored or re-found
        location = (entry.get("stellenlokationen") or [{}])[0]
        adresse = location.get("adresse") or {}
        is_werkstudent, is_internship = _title_flags(entry.get("stellenangebotsTitel", ""))
        postings.append(
            RawPosting(
                job_id=f"BA:{reference}",
                source="BA",
                source_id=reference,
                title=entry.get("stellenangebotsTitel") or "",
                company=entry.get("firma"),
                city=adresse.get("ort"),
                plz=adresse.get("plz"),
                lat=location.get("breite"),
                lon=location.get("laenge"),
                employment_type_raw=_employment_type_raw(entry),
                is_minijob=bool(entry.get("istGeringfuegigeBeschaeftigung")),
                is_parttime=any(
                    bool(entry.get(flag))
                    for flag in entry
                    if flag.startswith("arbeitszeitTeilzeit")
                ),
                is_fulltime=bool(entry.get("arbeitszeitVollzeit")),
                is_internship=is_internship,
                is_werkstudent=is_werkstudent,
                homeoffice=bool(entry.get("homeofficemoeglich")),
                published_at=(entry.get("veroeffentlichungszeitraum") or {}).get("von")
                or entry.get("datumErsteVeroeffentlichung"),
                apply_url=entry.get("externeURL"),
                source_url=DETAIL_PAGE_URL.format(ref=reference),
            )
        )
    return postings


def _employment_type_raw(entry: dict) -> str | None:
    words = []
    if entry.get("arbeitszeitVollzeit"):
        words.append("Vollzeit")
    if any(flag.startswith("arbeitszeitTeilzeit") and entry.get(flag) for flag in entry):
        words.append("Teilzeit")
    if entry.get("istGeringfuegigeBeschaeftigung"):
        words.append("Geringfügig")
    return ", ".join(words) or None


class BAApi:
    """SourceAdapter over the Jobsuche REST endpoints."""

    source = "BA"

    def __init__(self, client):
        self._client = client

    def search(self, spec: SearchSpec):
        for query in build_queries(spec):
            page = 1
            found_for_query = 0
            while True:
                payload = self._client.get_json(
                    SEARCH_URL, params=query.for_page(page).params(), headers=API_HEADERS
                )
                postings = parse_page(payload)
                if not postings:
                    break
                yield from postings
                found_for_query += len(postings)
                try:
                    total = int(payload.get("maxErgebnisse", 0))
                except (TypeError, ValueError):
                    total = 0
                if found_for_query >= total:
                    break
                page += 1
