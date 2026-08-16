"""Do the scraped sites still answer this laptop, and still parse? (`pytest -m live`)

Shape only, never counts — how many minijobs Ingolstadt has today is not a
promise anyone made. What is asserted: the site answers, the adapter finds
listings on the page it gets back, and a board that blocks us fails the way
the run expects rather than by crashing.

StepStone and Indeed are checked too, and are *allowed* to refuse: both
blocked this client during Phase 6. Their test fails only if they answer and
the adapter cannot parse what came back — which is the day to enable them.
"""

from __future__ import annotations

import pytest

from jobfinder.search_spec import SearchSpec
from jobfinder.sources.http import PoliteClient, SourceUnavailable
from jobfinder.sources.indeed import IndeedScraper
from jobfinder.sources.kleinanzeigen import KleinanzeigenScraper
from jobfinder.sources.stepstone import StepStoneScraper
from jobfinder.sources.xing import XingScraper

pytestmark = pytest.mark.live


def spec(city: str = "Ingolstadt", types=("minijob",)) -> SearchSpec:
    return SearchSpec.build(mode="general", employment_types=list(types), city_names=[city])


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    """One polite client for the module, at the careful scraped-site pace."""
    return PoliteClient(
        cache_dir=tmp_path_factory.mktemp("scrapers-live-cache"), budget=8, min_delay=3.0
    )


def first_page(adapter, search_spec):
    return next(iter(adapter.search_pages(search_spec)), None)


class TestSitesThatAnswer:
    def test_kleinanzeigen_returns_parseable_ads(self, client):
        page = first_page(KleinanzeigenScraper(client), spec())

        assert page is not None, "Kleinanzeigen returned no page at all"
        assert page.postings, "the page parsed to zero ads — the list markup drifted"
        first = page.postings[0]
        assert first.job_id.startswith("KA:")
        assert first.title and first.source_url

    def test_xing_returns_parseable_listings(self, client):
        page = first_page(XingScraper(client), spec(types=("parttime",)))

        assert page is not None, "Xing returned no page at all"
        assert page.postings, "the SEO page parsed to zero listings — its anchors drifted"
        assert page.postings[0].job_id.startswith("XI:")


class TestBoardsAllowedToRefuse:
    """Blocked is a known state. Answering-but-unparseable is the finding."""

    @pytest.mark.parametrize(
        ("scraper", "code"),
        [(StepStoneScraper, "SS"), (IndeedScraper, "ID")],
        ids=["stepstone", "indeed"],
    )
    def test_it_either_refuses_cleanly_or_parses(self, client, scraper, code):
        try:
            page = first_page(scraper(client), spec(types=("parttime",)))
        except SourceUnavailable:
            pytest.skip(f"{code} still refuses this client — the state Phase 6 shipped")
        assert page is not None
        assert page.postings, (
            f"{code} answered but nothing parsed — record a fixture and enable it"
        )
