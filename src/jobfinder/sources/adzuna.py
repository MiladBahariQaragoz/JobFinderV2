"""Adzuna jobs API — the aggregator, enabled once she has registered a key.

Measured live on 2026-08-16 before this parser was written (see the Phase 6
plan). What that measurement decided:

- **The API's description is a teaser**, capped at 500 characters and usually
  cut mid-sentence. It is never stored as the ad text — `fetch_detail` follows
  `redirect_url` and reads the JSON-LD ad behind it, which came back full 61 %
  of the time at a median 2 332 characters. The teaser is the fallback for the
  rest, because thin text beats none.
- **That 61 % does not last.** After roughly forty follows in one session,
  adzuna.de began answering every redirect with a bot-detection page —
  "Zugriff verweigert … Melde Dich an um fortzufahren" — and kept doing so.
  §8 rule 6 says a page that wants an account is skipped, not retried, so the
  first wall ends the following for that run. Expect full ads early in a run
  and teasers after, and treat Adzuna as a source of leads rather than of
  readable ads.
- **Which board is behind a row is invisible**: every `redirect_url` is an
  adzuna.de tracker. That stopped mattering once the numbers came in — 84 % of
  the rows are jobs the Bundesagentur search never returned.
- **Minijob has no Adzuna flag**, so it travels as a search term. A query with
  neither flag nor term asks for every job in the city.
"""

from __future__ import annotations

import os
import urllib.parse
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from jobfinder.sources.base import PageResult, RawPosting
from jobfinder.sources.extract import (
    extract_readable_text,
    html_to_text,
    jsonld_jobpostings,
    looks_like_login_wall,
)
from jobfinder.sources.wording import employment_type_signals

if TYPE_CHECKING:
    from jobfinder.search_spec import SearchSpec

BASE_URL = "https://api.adzuna.com/v1/api/jobs/de/search"

PAGE_SIZE = 50  # Adzuna's documented maximum

# Her types that map onto an Adzuna boolean flag. One flag per query — the
# flags AND together server-side, and her types are alternatives (Phase 4
# audit). Types without a flag travel as `what` search terms.
FLAG_FOR_TYPE = {
    "parttime": "part_time",
    "fulltime": "full_time",
}
KEYWORD_FOR_TYPE = {
    "werkstudent": "Werkstudent",
    "internship": "Praktikum",
    # No flag exists for this one, and without a term the query returns every
    # job in the city — 204 real minijobs buried in 815 results.
    "minijob": "Minijob",
}

# A walk is bounded by the reported `count`, but that count can be thousands
# (1 705 for werkstudent in München). §8 makes requests the scarce resource.
MAX_PAGES = 10


class AdzunaNotConfigured(Exception):
    """No API key in the environment — Adzuna is off, which is normal."""


@dataclass(frozen=True)
class AdzunaQuery:
    """One page request to the search endpoint."""

    page: int
    app_id: str
    app_key: str
    what: str | None = None
    where: str | None = None
    distance: int | None = None
    part_time: int = 0
    full_time: int = 0
    size: int = PAGE_SIZE

    def params(self) -> dict:
        params: dict = {"app_id": self.app_id, "app_key": self.app_key}
        if self.size:
            params["results_per_page"] = self.size
        for name, value in (
            ("what", self.what),
            ("where", self.where),
            ("distance", self.distance),
        ):
            if value is not None:
                params[name] = value
        for flag in ("part_time", "full_time"):
            if getattr(self, flag):
                params[flag] = 1
        return params

    def url(self) -> str:
        return f"{BASE_URL}/{self.page}?{urllib.parse.urlencode(self.params())}"

    def for_page(self, page: int) -> AdzunaQuery:
        """The same query, one page along — the number rides in the path."""
        return replace(self, page=page)


def build_queries(spec: SearchSpec, *, app_id: str, app_key: str) -> list[AdzunaQuery]:
    """One query per keyword per city per employment type — alternatives, never stacked."""
    bases = [keyword.strip() for keyword in spec.keywords if keyword.strip()] or [""]
    queries: list[AdzunaQuery] = []
    for base in bases:
        for city in spec.cities:
            for employment_type in spec.employment_types or [""]:
                flag = FLAG_FOR_TYPE.get(employment_type)
                term = KEYWORD_FOR_TYPE.get(employment_type)
                what = " ".join(part for part in (base, term) if part) or None
                queries.append(
                    AdzunaQuery(
                        page=1,
                        app_id=app_id,
                        app_key=app_key,
                        what=what,
                        where=city.name,
                        distance=city.radius_km,
                        **({flag: 1} if flag else {}),
                    )
                )
    return queries


def _city_from(location: dict, spec: SearchSpec) -> str | None:
    """The city she searched, when Adzuna's area names it.

    `area` reads ["Deutschland", "Bayern", "Ingolstadt", "Pettenhofen"] — the
    last entry is a hamlet, and her store dedupes on the city, where the
    Bundesagentur calls the same place "Ingolstadt, Donau".
    """
    area = [part for part in (location or {}).get("area") or [] if part]
    wanted = {city.name.casefold(): city.name for city in spec.cities}
    for part in reversed(area):
        if part.casefold() in wanted:
            return wanted[part.casefold()]
    if len(area) >= 3:
        return area[2]  # country, state, city
    return area[-1] if area else None


def parse_row(row: dict, spec: SearchSpec) -> RawPosting | None:
    """One `results[]` row into a posting. The teaser informs, it is not stored."""
    job_id = row.get("id")
    if not job_id:
        return None
    title = row.get("title") or ""
    teaser = row.get("description") or ""
    signals = employment_type_signals(title, teaser)
    redirect = row.get("redirect_url")
    return RawPosting(
        job_id=f"AZ:{job_id}",
        source="AZ",
        source_id=str(job_id),
        title=title,
        company=((row.get("company") or {}).get("display_name")),
        city=_city_from(row.get("location") or {}, spec),
        lat=row.get("latitude"),
        lon=row.get("longitude"),
        employment_type_raw=((row.get("category") or {}).get("label")),
        is_minijob="minijob" in signals,
        is_parttime="parttime" in signals,
        is_fulltime="fulltime" in signals,
        is_internship="internship" in signals,
        is_werkstudent="werkstudent" in signals,
        published_at=row.get("created"),
        apply_url=redirect,
        source_url=redirect,
        # description stays None on purpose: the teaser is 500 characters cut
        # mid-sentence, and storing it would stop the runner fetching the ad.
    )


def parse_page(payload: dict, spec: SearchSpec) -> list[RawPosting]:
    return [posting for row in payload.get("results") or [] if (posting := parse_row(row, spec))]


class AdzunaApi:
    """SourceAdapter over the Adzuna search endpoint. Source code: `AZ`."""

    source = "AZ"

    def __init__(self, client):
        self._client = client
        # job_id -> the 500-character teaser, kept for the ads whose redirect
        # is refused. Lives only as long as this leg's adapter, which is all
        # it needs to: `fetch_detail` runs page by page as the search walks.
        self._teasers: dict[str, str] = {}
        # Set once adzuna.de asks us to sign in; stops the following.
        self._walled = False

    def _credentials(self) -> tuple[str, str]:
        app_id = os.environ.get("ADZUNA_APP_ID")
        app_key = os.environ.get("ADZUNA_APP_KEY")
        if not app_id or not app_key:
            raise AdzunaNotConfigured(
                "Adzuna has no API key — add ADZUNA_APP_ID and ADZUNA_APP_KEY to .env, "
                "or remove adzuna from enabled_sources."
            )
        return app_id, app_key

    def search_pages(self, spec: SearchSpec, *, start_query_index: int = 0, start_page: int = 1):
        """Walk each query's pages until its reported count is covered."""
        app_id, app_key = self._credentials()  # fail readably before the first request
        queries = build_queries(spec, app_id=app_id, app_key=app_key)
        for query_index, query in enumerate(queries):
            if query_index < start_query_index:
                continue
            page = max(1, start_page if query_index == start_query_index else 1)
            for _ in range(MAX_PAGES):
                payload = self._client.get_json(query.for_page(page).url())
                postings = parse_page(payload, spec)
                if not (payload.get("results") or []):
                    break  # past the end
                for posting, row in zip(postings, payload["results"], strict=False):
                    self._teasers[posting.job_id] = row.get("description") or ""
                yield PageResult(
                    source=self.source,
                    query_index=query_index,
                    page=page,
                    postings=postings,
                )
                if page * query.size >= int(payload.get("count") or 0):
                    break  # the count says there is nothing after this page
                page += 1

    def fetch_detail(self, posting: RawPosting) -> RawPosting:
        """Follow the redirect and read the real ad; keep the teaser if refused.

        Measured live: adzuna.de answers a share of these with a bot-detection
        page — "Zugriff verweigert … Melde Dich an um fortzufahren" — and once
        it starts, it answers every one that way. §8 rule 6 says a page that
        wants an account is skipped rather than retried, so the first wall ends
        the following for this run and the rest of the ads keep their teasers.
        """
        teaser = self._teasers.get(posting.job_id) or None
        if self._walled or not posting.source_url:
            return replace(posting, description=teaser)
        response = self._client.get(posting.source_url)
        if response.status != 200:
            self._walled = True
            return replace(posting, description=teaser)
        markup = response.body.decode("utf-8", "replace")
        if looks_like_login_wall(markup):
            self._walled = True
            return replace(posting, description=teaser)
        ads = jsonld_jobpostings(markup)
        description = html_to_text(ads[0].get("description") or "") if ads else None
        if not description:
            description = extract_readable_text(markup)
        return replace(posting, description=description or teaser)

    def search(self, spec: SearchSpec):
        for page in self.search_pages(spec):
            yield from page.postings
