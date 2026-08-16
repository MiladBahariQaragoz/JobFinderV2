"""Indeed — the classic query form, built to fail softly.

`de.indeed.com/jobs?q={term}&l={city}` paginates with `&start={10*(page-1)}`,
job links carry their `jk=` id. During Phase 6 recon (2026-08-16) the site
answered every request with its standard 403 block page — recorded as
`tests/fixtures/indeed/blocked_403.html` — and the RSS feed it once offered
is retired. The adapter therefore ships **disabled by default** and its most
tested behaviour is the blocked path: one error line, one failure counted,
the run continues. The detail mapping is the shared schema.org JobPosting
path.
"""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass
from typing import TYPE_CHECKING

from bs4 import BeautifulSoup

from jobfinder.sources.base import LoginWall, PageResult, RawPosting
from jobfinder.sources.extract import (
    jobposting_to_posting,
    jsonld_jobpostings,
    looks_like_login_wall,
)
from jobfinder.sources.http import SourceUnavailable
from jobfinder.sources.wording import employment_type_signals, search_term_for

if TYPE_CHECKING:
    from jobfinder.search_spec import SearchSpec

BASE_URL = "https://de.indeed.com"
MAX_PAGES = 3

_JK_ID = re.compile(r"[?&]jk=([0-9a-f]{16,})")


@dataclass(frozen=True)
class SearchQuery:
    url: str
    term: str
    city: str

    def url_for_page(self, page: int) -> str:
        if page <= 1:
            return self.url
        return f"{self.url}&start={10 * (page - 1)}"


def build_queries(spec: SearchSpec) -> list[SearchQuery]:
    """One search per (term, city); her keywords add terms of their own."""
    terms = [search_term_for(t) for t in spec.employment_types]
    terms += [keyword for keyword in spec.keywords if keyword not in terms]
    return [
        SearchQuery(
            url=f"{BASE_URL}/jobs?q={urllib.parse.quote(term)}&l={urllib.parse.quote(city.name)}",
            term=term,
            city=city.name,
        )
        for term in terms
        for city in spec.cities
    ]


def parse_list(markup: str) -> list[RawPosting]:
    """Job anchors into posting stubs — every link carrying a `jk=` id."""
    soup = BeautifulSoup(markup, "html.parser")
    seen: set[str] = set()
    postings = []
    for anchor in soup.select("a[href]"):
        match = _JK_ID.search(anchor["href"])
        if match is None:
            continue
        source_id = match.group(1)
        if source_id in seen:
            continue  # the same jk appears in several links on one card
        title = anchor.get("aria-label") or anchor.get_text(" ", strip=True)
        if not title:
            continue
        seen.add(source_id)
        signals = employment_type_signals(title)
        postings.append(
            RawPosting(
                job_id=f"ID:{source_id}",
                source="ID",
                source_id=source_id,
                title=title,
                source_url=f"{BASE_URL}/viewjob?jk={source_id}",
                is_minijob="minijob" in signals,
                is_parttime="parttime" in signals,
                is_fulltime="fulltime" in signals,
                is_internship="internship" in signals,
                is_werkstudent="werkstudent" in signals,
            )
        )
    return postings


class IndeedScraper:
    """SourceAdapter over the classic search. Source code: `ID`."""

    source = "ID"

    def __init__(self, client):
        self._client = client

    def search(self, spec: SearchSpec):
        for page in self.search_pages(spec):
            yield from page.postings

    def search_pages(self, spec: SearchSpec, *, start_query_index: int = 0, start_page: int = 1):
        for query_index, query in enumerate(build_queries(spec)):
            if query_index < start_query_index:
                continue
            resuming = query_index == start_query_index
            page_number = max(1, start_page) if resuming else 1
            for _ in range(MAX_PAGES):
                markup = self._get(query.url_for_page(page_number))
                postings = parse_list(markup)
                yield PageResult(
                    source=self.source,
                    query_index=query_index,
                    page=page_number,
                    postings=postings,
                )
                if not postings:
                    break  # past the last page, Indeed serves its empty shell
                page_number += 1

    def fetch_detail(self, posting: RawPosting) -> RawPosting:
        try:
            markup = self._get(posting.source_url)
        except LoginWall:
            return posting  # walled job stays listed, just unenriched
        postings = jsonld_jobpostings(markup)
        if postings:
            parsed = jobposting_to_posting(
                postings[0],
                source=self.source,
                job_id=posting.job_id,
                source_id=posting.source_id,
                source_url=posting.source_url,
            )
            if parsed is not None:
                return parsed
        soup = BeautifulSoup(markup, "html.parser")
        title_el = soup.select_one("h1")
        if title_el is None:
            return posting  # unparseable stays unenriched, not broken
        return RawPosting(**{**posting.__dict__, "title": title_el.get_text(" ", strip=True)})

    def _get(self, url: str) -> str:
        response = self._client.get(url)
        markup = response.body.decode("utf-8", errors="replace")
        if response.status in (403, 404, 410):
            raise SourceUnavailable(
                f"de.indeed.com answered {response.status} — blocked or gone. "
                "Re-record fixtures from a network it answers on (Phase 6 plan)."
            )
        if looks_like_login_wall(markup):
            raise LoginWall(f"{url} wants an account — skipped, not retried.")
        return markup
