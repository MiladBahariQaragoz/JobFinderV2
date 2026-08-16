"""Kleinanzeigen classifieds — probably her best source for minijobs.

Facts verified live 2026-08-16 (see the Phase 6 plan): the location browse is
`/s-jobs/{slug}/anzeige:angebote/c102l{id}` — 27 ads a page, every ad in the
chosen city, and `anzeige:angebote` keeps the wanted-ads out at the source.
Keyword and location **do not combine** (the site's own next-link drops the
keyword segment), so a search is one browse per city with employment types
filtered client-side from the wording — alternatives, never stacked.

There is no JSON-LD on either page; the selectors below are the primary
extraction, and that is what the site offers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from bs4 import BeautifulSoup

from jobfinder.cities import kleinanzeigen_location
from jobfinder.sources.base import LoginWall, PageResult, RawPosting
from jobfinder.sources.extract import looks_like_login_wall
from jobfinder.sources.wording import employment_type_signals

if TYPE_CHECKING:
    from jobfinder.search_spec import SearchSpec

BASE_URL = "https://www.kleinanzeigen.de"

# One city's browse can run to many pages; the newest market she can act on
# is the first few. The request budget is the real ceiling; this keeps a
# single city from spending it all.
MAX_PAGES = 5

# "86343 Bayern - Königsbrunn" on the detail page; "85053 Ingolstadt" on lists.
_PLZ = re.compile(r"^(\d{5})\s+")


@dataclass(frozen=True)
class BrowseQuery:
    """One city's offers-only browse, with the resume URL shape."""

    url: str
    slug: str
    location_id: str

    def url_for_page(self, page: int) -> str:
        if page <= 1:
            return self.url
        stem, _, tail = self.url.partition("/c102l")
        return f"{stem}/seite:{page}/c102l{tail}"


def build_queries(spec: SearchSpec) -> list[BrowseQuery]:
    """One browse per city — a city without a recorded id is refused loudly.

    A guessed id returns jobs in the wrong part of Germany, which looks like
    success; an error she can act on is the better failure.
    """
    queries = []
    unmapped = []
    for city in spec.cities:
        location = kleinanzeigen_location(city.name)
        if location is None:
            unmapped.append(city.name)
            continue
        slug, location_id = location
        queries.append(
            BrowseQuery(
                url=f"{BASE_URL}/s-jobs/{slug}/anzeige:angebote/c102l{location_id}",
                slug=slug,
                location_id=location_id,
            )
        )
    if unmapped:
        raise ValueError(
            f"Kleinanzeigen has no location id for {', '.join(unmapped)}. Record one in "
            f"cities.py (KLEINANZEIGEN_LOCATIONS) or search without that city — "
            f"a guessed id returns jobs in the wrong part of Germany."
        )
    return queries


def _city_plz(text: str | None) -> tuple[str | None, str | None]:
    """'85053 Ingolstadt' -> ('85053', 'Ingolstadt'); no plz stays None."""
    if not text:
        return None, None
    text = " ".join(text.split())
    match = _PLZ.match(text)
    if match:
        return match.group(1), text[match.end() :]
    return None, text or None


def _posting_from_article(article, source_url: str) -> RawPosting | None:
    ad_id = article.get("data-adid")
    path = article.get("data-href")
    if not ad_id or not path:
        return None
    if "/s-gesuch/" in path:  # someone seeking work, not offering it
        return None
    title_el = article.select_one(".text-module-begin a.ellipsis") or article.select_one(
        "a.ellipsis"
    )
    title = title_el.get_text(" ", strip=True) if title_el else None
    if not title:
        return None
    plz, city = _city_plz(
        (article.select_one(".aditem-main--top--left") or article.select_one(".aditem-main--top"))
        and article.select_one(".aditem-main--top--left").get_text(" ", strip=True)
    )
    signals = employment_type_signals(title)
    return RawPosting(
        job_id=f"KA:{ad_id}",
        source="KA",
        source_id=ad_id,
        title=title,
        city=city,
        plz=plz,
        source_url=f"{BASE_URL}{path}",
        is_minijob="minijob" in signals,
        is_parttime="parttime" in signals,
        is_fulltime="fulltime" in signals,
        is_internship="internship" in signals,
        is_werkstudent="werkstudent" in signals,
    )


def parse_list(markup: str) -> tuple[list[RawPosting], str | None]:
    """One results page into postings (no descriptions yet) and the next href."""
    soup = BeautifulSoup(markup, "html.parser")
    postings = [
        posting
        for article in soup.select("article.aditem")
        if (posting := _posting_from_article(article, BASE_URL))
    ]
    next_link = soup.select_one("a.pagination-next")
    return postings, (next_link.get("href") if next_link else None)


def parse_detail(markup: str, *, source_url: str) -> RawPosting | None:
    """One ad page into a full posting — or None when it is not an ad page."""
    soup = BeautifulSoup(markup, "html.parser")
    title_el = soup.select_one("#viewad-title")
    body_el = soup.select_one("#viewad-description")
    if title_el is None or body_el is None:
        return None
    title = title_el.get_text(" ", strip=True)
    description = body_el.get_text("\n", strip=True)
    if description.lower().startswith("beschreibung"):
        description = description[len("beschreibung") :].lstrip()
    plz, city = _city_plz(
        soup.select_one("#viewad-locality").get_text(" ", strip=True)
        if soup.select_one("#viewad-locality")
        else None
    )
    if city and " - " in city:  # "Bayern - Königsbrunn" — the city is the last part
        city = city.rsplit(" - ", 1)[-1].strip()
    published_at = None
    date_el = soup.select_one("#viewad-extra-info")
    if date_el:
        match = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", date_el.get_text(" ", strip=True))
        if match:
            published_at = f"{match.group(3)}-{match.group(2)}-{match.group(1)}"
    signals = employment_type_signals(title, description)
    return RawPosting(
        job_id="",  # filled by the caller, which knows the ad id
        source="KA",
        source_id="",
        title=title,
        city=city,
        plz=plz,
        published_at=published_at,
        source_url=source_url,
        description=description or None,
        is_minijob="minijob" in signals,
        is_parttime="parttime" in signals,
        is_fulltime="fulltime" in signals,
        is_internship="internship" in signals,
        is_werkstudent="werkstudent" in signals,
    )


class KleinanzeigenScraper:
    """SourceAdapter over the classifieds. Source code: `KA`."""

    source = "KA"

    def __init__(self, client):
        self._client = client

    def search(self, spec: SearchSpec):
        for page in self.search_pages(spec):
            yield from page.postings

    def search_pages(self, spec: SearchSpec, *, start_query_index: int = 0, start_page: int = 1):
        """One browse per city, following the site's own next-links."""
        queries = build_queries(spec)
        for query_index, query in enumerate(queries):
            if query_index < start_query_index:
                continue  # this city finished before the interruption
            resuming = query_index == start_query_index
            url = query.url_for_page(max(1, start_page)) if resuming else query.url
            page_number = max(1, start_page) if resuming else 1
            for _ in range(MAX_PAGES):
                markup = self._get(url)
                postings, next_href = parse_list(markup)
                yield PageResult(
                    source=self.source,
                    query_index=query_index,
                    page=page_number,
                    postings=self._matching(postings, spec),
                )
                if not next_href:
                    break
                url = f"{BASE_URL}{next_href}"
                page_number += 1

    def fetch_detail(self, posting: RawPosting) -> RawPosting:
        markup = self._get(posting.source_url)
        parsed = parse_detail(markup, source_url=posting.source_url)
        if parsed is None:
            return posting  # an unparseable ad stays unenriched, not broken
        return RawPosting(
            **{**parsed.__dict__, "job_id": posting.job_id, "source_id": posting.source_id}
        )

    def _get(self, url: str) -> str:
        response = self._client.get(url)
        markup = response.body.decode("utf-8", errors="replace")
        if looks_like_login_wall(markup):
            raise LoginWall(f"{url} wants an account — skipped, not retried.")
        return markup

    @staticmethod
    def _matching(postings: list[RawPosting], spec: SearchSpec) -> list[RawPosting]:
        """Types are alternatives: wording for any one of her types passes."""
        wanted = set(spec.employment_types)
        kept = []
        for posting in postings:
            signals = employment_type_signals(posting.title)
            if not wanted or signals & wanted:
                kept.append(posting)
        return kept
