"""Xing jobs — the public SEO pages, nothing behind a login.

Facts verified live 2026-08-16 (see the Phase 6 plan): robots.txt disallows
the search endpoints but not the SEO pages, so the adapter reads exactly
those — one page per (search term, city), `?page=2` serves the same links,
so there is no pagination to walk. List anchors carry the title in
`aria-label` and nothing else; every field of substance comes from the
detail page's schema.org JobPosting, which is the primary extraction. The
DOM fallback (`h1`, the company testid) exists for the day the script block
goes missing — and it deliberately does not guess a description.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from bs4 import BeautifulSoup

from jobfinder.sources.base import PageResult, RawPosting
from jobfinder.sources.extract import (
    html_to_text,
    jobposting_city,
    jobposting_company,
    jsonld_jobpostings,
    looks_like_login_wall,
)
from jobfinder.sources.wording import employment_type_signals, search_term_for, slugify

if TYPE_CHECKING:
    from jobfinder.search_spec import SearchSpec

BASE_URL = "https://www.xing.com"

# `/jobs/{city}-aushilfe-…-156837029` — a slug ending in the posting id.
_JOB_HREF = re.compile(r"^/jobs/[a-z0-9-]*[a-z]-(\d{6,})$")


@dataclass(frozen=True)
class SeoQuery:
    """One SEO page — the whole query, since there is no pagination."""

    url: str
    term: str


def build_queries(spec: SearchSpec) -> list[SeoQuery]:
    """One page per (search term, city); her keywords get terms of their own."""
    terms = [search_term_for(t) for t in spec.employment_types]
    terms += [keyword for keyword in spec.keywords if keyword not in terms]
    return [
        SeoQuery(url=f"{BASE_URL}/jobs/{slugify(term)}-{slugify(city.name)}", term=term)
        for term in terms
        for city in spec.cities
    ]


def parse_list(markup: str) -> list[RawPosting]:
    """Job anchors into posting stubs — title and link is all the page offers."""
    soup = BeautifulSoup(markup, "html.parser")
    postings = []
    for anchor in soup.select('a[href^="/jobs/"]'):
        match = _JOB_HREF.match(anchor.get("href") or "")
        if match is None:
            continue
        source_id = match.group(1)
        title = anchor.get("aria-label") or anchor.get_text(" ", strip=True)
        if not title:
            continue
        signals = employment_type_signals(title)
        postings.append(
            RawPosting(
                job_id=f"XI:{source_id}",
                source="XI",
                source_id=source_id,
                title=title,
                source_url=f"{BASE_URL}{anchor['href']}",
                is_minijob="minijob" in signals,
                is_parttime="parttime" in signals,
                is_fulltime="fulltime" in signals,
                is_internship="internship" in signals,
                is_werkstudent="werkstudent" in signals,
            )
        )
    return postings


def parse_detail(markup: str, *, source_url: str) -> RawPosting | None:
    """One job page into a full posting — JSON-LD first, DOM second."""
    postings = jsonld_jobpostings(markup)
    if postings:
        data = postings[0]
        description = html_to_text(data.get("description") or "")
        posted = data.get("datePosted") or ""
        title = data.get("title") or ""
        company = jobposting_company(data)
        city = jobposting_city(data)
    else:
        soup = BeautifulSoup(markup, "html.parser")
        title_el = soup.select_one("h1")
        company_el = soup.select_one("[data-testid*=company]")
        if title_el is None:
            return None
        title = title_el.get_text(" ", strip=True)
        raw_company = company_el.get_text(" ", strip=True) if company_el else ""
        company, _, city = raw_company.partition(" - ")
        company, city = company.strip() or None, city.strip() or None
        description, posted = None, ""  # no structured data, no body we can trust

    signals = employment_type_signals(title, description or "")
    return RawPosting(
        job_id="",  # filled by the caller, which knows the posting id
        source="XI",
        source_id="",
        title=title,
        company=company,
        city=city,
        published_at=posted[:10] or None,
        apply_url=source_url,
        source_url=source_url,
        description=description or None,
        is_minijob="minijob" in signals,
        is_parttime="parttime" in signals,
        is_fulltime="fulltime" in signals,
        is_internship="internship" in signals,
        is_werkstudent="werkstudent" in signals,
    )


class XingScraper:
    """SourceAdapter over the public SEO pages. Source code: `XI`."""

    source = "XI"

    def __init__(self, client):
        self._client = client

    def search(self, spec: SearchSpec):
        for page in self.search_pages(spec):
            yield from page.postings

    def search_pages(self, spec: SearchSpec, *, start_query_index: int = 0, start_page: int = 1):
        for query_index, query in enumerate(build_queries(spec)):
            if query_index < start_query_index:
                continue  # this page finished before the interruption
            markup = self._get(query.url)
            postings = parse_list(markup)
            yield PageResult(
                source=self.source,
                query_index=query_index,
                page=1,  # SEO pages do not paginate — verified live
                postings=postings,
            )

    def fetch_detail(self, posting: RawPosting) -> RawPosting:
        from jobfinder.sources.base import LoginWall

        try:
            markup = self._get(posting.source_url)
        except LoginWall:
            return posting  # walled job stays listed, just unenriched
        parsed = parse_detail(markup, source_url=posting.source_url)
        if parsed is None:
            return posting  # unparseable stays unenriched, not broken
        return RawPosting(
            **{
                **parsed.__dict__,
                "job_id": posting.job_id,
                "source_id": posting.source_id,
                "title": parsed.title or posting.title,
            }
        )

    def _get(self, url: str) -> str:
        response = self._client.get(url)
        markup = response.body.decode("utf-8", errors="replace")
        if looks_like_login_wall(markup):
            from jobfinder.sources.base import LoginWall

            raise LoginWall(f"{url} wants an account — skipped, not retried.")
        return markup
