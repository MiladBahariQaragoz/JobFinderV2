"""StepStone — the SEO search pages, built to fail softly.

Verified shapes (Phase 6 recon, 2026-08-16): search lives at
`/jobs/{keyword}/in-{city}` — server-rendered, job links
`/stellenangebote--{slug}--{id}-inline.html`, paginated with `?page=N`. The
site answered none of that to this machine's politely-identified client
(transport-level resets on every request, robots.txt included), which is why
the adapter ships **disabled by default**: §8 rule 4 forbids pretending to be
a browser, so a refusing host gets the kill switch, not a workaround.

Detail pages are read through the shared schema.org JobPosting path; the DOM
fallback (`h1`) exists for pages whose script block goes missing.
"""

from __future__ import annotations

import re
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
from jobfinder.sources.wording import search_term_for, slugify

if TYPE_CHECKING:
    from jobfinder.search_spec import SearchSpec

BASE_URL = "https://www.stepstone.de"
MAX_PAGES = 3

_DETAIL_ID = re.compile(r"--(\d+)-inline\.html$")


@dataclass(frozen=True)
class SearchQuery:
    url: str
    term: str

    def url_for_page(self, page: int) -> str:
        return self.url if page <= 1 else f"{self.url}?page={page}"


def build_queries(spec: SearchSpec) -> list[SearchQuery]:
    """One SEO search per (term, city); her keywords add terms of their own."""
    terms = [search_term_for(t) for t in spec.employment_types]
    terms += [keyword for keyword in spec.keywords if keyword not in terms]
    return [
        SearchQuery(url=f"{BASE_URL}/jobs/{slugify(term)}/in-{slugify(city.name)}", term=term)
        for term in terms
        for city in spec.cities
    ]


def parse_list(markup: str) -> list[RawPosting]:
    """Listing anchors into posting stubs — `/stellenangebote--…-{id}-inline.html`."""
    soup = BeautifulSoup(markup, "html.parser")
    postings = []
    for anchor in soup.select('a[href^="/stellenangebote--"]'):
        match = _DETAIL_ID.search(anchor.get("href") or "")
        if match is None:
            continue
        source_id = match.group(1)
        title = anchor.get("aria-label") or anchor.get_text(" ", strip=True)
        if not title:
            continue
        postings.append(
            RawPosting(
                job_id=f"SS:{source_id}",
                source="SS",
                source_id=source_id,
                title=title,
                source_url=f"{BASE_URL}{anchor['href']}",
            )
        )
    return postings


class StepStoneScraper:
    """SourceAdapter over the SEO pages. Source code: `SS`."""

    source = "SS"

    def __init__(self, client):
        self._client = client

    def search(self, spec: SearchSpec):
        for page in self.search_pages(spec):
            yield from page.postings

    def search_pages(
        self, spec: SearchSpec, *, start_query_index: int = 0, start_page: int = 1
    ):
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
                    break  # a page with nothing left is the end of the walk
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
                "www.stepstone.de answered "
                f"{response.status} — blocked or gone. "
                "Re-record fixtures from a network it answers on (Phase 6 plan)."
            )
        if looks_like_login_wall(markup):
            raise LoginWall(f"{url} wants an account — skipped, not retried.")
        return markup
