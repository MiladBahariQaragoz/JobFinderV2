"""StepStone and Indeed — built against their verified URL shapes, blocked where they are.

Both boards refused this machine's politely-identified client during Phase 6
recon (StepStone resets the transport on every request; Indeed answers its
standard 403 page — recorded as `indeed/blocked_403.html`). The adapters are
therefore built to the shapes verified through the search engine's own copies
of their pages, and their most important tested behaviour is failing softly:
a blocked host becomes one error line, not a crashed run. The detail parsing
is the shared JSON-LD path, exercised against Xing's real recorded page in
test_xing.py.

Re-record fixtures from a network they answer on, then enable them in
config.yaml — see the Phase 6 plan's known gaps.
"""

from __future__ import annotations

import pytest

from jobfinder.search_spec import SearchSpec
from jobfinder.sources.http import SourceUnavailable


def spec(**overrides) -> SearchSpec:
    parts = dict(mode="general", employment_types=["minijob"], city_names=["Ingolstadt"])
    parts.update(overrides)
    return SearchSpec.build(**parts)


class RecordingClient:
    """Stands in for the PoliteClient: serves scripted pages, records calls."""

    def __init__(self, pages, statuses=None):
        self.pages = list(pages)
        self.statuses = list(statuses or [])
        self.calls: list[str] = []

    def get(self, url, params=None, headers=None):
        from jobfinder.sources.http import Response

        self.calls.append(url)
        status = self.statuses.pop(0) if self.statuses else 200
        body = self.pages.pop(0) if self.pages else b""
        if isinstance(body, str):
            body = body.encode("utf-8")
        return Response(status=status, body=body, headers={})


STEPSTONE_LIST = """
<html><body>
<a href="/stellenangebote--Aushilfe-im-Verkauf-Minijob-m-w-d-Ingolstadt-Lidl--14298033-inline.html">
  Aushilfe im Verkauf Minijob (m/w/d)</a>
<a href="/stellenangebote--Mitarbeiter-Fruehstueck-m-w-d-Ingolstadt-Heidehof--8119146-inline.html">
  Mitarbeiter Frühstücksservice (m/w/d)</a>
<a href="/jobs/minijob/in-muenchen">More Minijob jobs</a>
</body></html>
"""

INDEED_LIST = """
<html><body>
<a class="jcs-JobTitle" href="/rc/clk?jk=8a1b2c3d4e5f60718293a4b5&atk=xyz">Küchenhilfe (m/w/d)</a>
<a href="/viewjob?jk=9b2c3d4e5f60718293a4b5c6">Reinigungskraft Teilzeit</a>
<a href="/company/Lidl">Lidl jobs</a>
</body></html>
"""


# -- StepStone -------------------------------------------------------------------


class TestStepStone:
    def test_search_url_is_keyword_slash_in_city(self):
        from jobfinder.sources.stepstone import build_queries

        urls = [q.url for q in build_queries(spec(city_names=["Ingolstadt", "München"]))]
        assert urls == [
            "https://www.stepstone.de/jobs/minijob/in-ingolstadt",
            "https://www.stepstone.de/jobs/minijob/in-muenchen",
        ]

    def test_page_two_is_a_query_parameter(self):
        from jobfinder.sources.stepstone import build_queries

        query = build_queries(spec())[0]
        assert query.url_for_page(2) == "https://www.stepstone.de/jobs/minijob/in-ingolstadt?page=2"

    def test_listing_urls_parse_with_their_ids(self):
        from jobfinder.sources.stepstone import parse_list

        postings = parse_list(STEPSTONE_LIST)
        assert [p.source_id for p in postings] == ["14298033", "8119146"]
        assert all(p.source == "SS" for p in postings)
        assert postings[0].title == "Aushilfe im Verkauf Minijob (m/w/d)"
        assert postings[0].job_id == "SS:14298033"
        assert postings[0].source_url == (
            "https://www.stepstone.de/stellenangebote--"
            "Aushilfe-im-Verkauf-Minijob-m-w-d-Ingolstadt-Lidl--14298033-inline.html"
        )

    def test_navigation_links_are_not_postings(self):
        from jobfinder.sources.stepstone import parse_list

        assert len(parse_list(STEPSTONE_LIST)) == 2  # the /jobs/ browse link stays out

    def test_a_blocked_search_page_raises_source_unavailable_not_a_crash(self, fixture_path):
        from jobfinder.sources.stepstone import StepStoneScraper

        blocked = fixture_path("indeed", "blocked_403.html").read_bytes()
        client = RecordingClient([blocked], statuses=[403])
        with pytest.raises(SourceUnavailable):
            list(StepStoneScraper(client).search_pages(spec()))

    def test_a_junk_200_page_yields_no_postings_and_no_crash(self):
        from jobfinder.sources.stepstone import StepStoneScraper

        client = RecordingClient(["<html><body>esp: <div></div></body></html>"])
        pages = list(StepStoneScraper(client).search_pages(spec()))
        assert len(pages) == 1 and pages[0].postings == []


# -- Indeed -----------------------------------------------------------------------


class TestIndeed:
    def test_search_url_is_the_classic_query_form(self):
        from jobfinder.sources.indeed import build_queries

        urls = [q.url for q in build_queries(spec(city_names=["Ingolstadt"]))]
        assert urls == ["https://de.indeed.com/jobs?q=minijob&l=Ingolstadt"]

    def test_page_two_is_the_start_parameter(self):
        from jobfinder.sources.indeed import build_queries

        query = build_queries(spec())[0]
        assert query.url_for_page(2) == "https://de.indeed.com/jobs?q=minijob&l=Ingolstadt&start=10"

    def test_listing_urls_parse_with_their_jk_ids(self):
        from jobfinder.sources.indeed import parse_list

        postings = parse_list(INDEED_LIST)
        assert [p.source_id for p in postings] == [
            "8a1b2c3d4e5f60718293a4b5",
            "9b2c3d4e5f60718293a4b5c6",
        ]
        assert all(p.source == "ID" for p in postings)
        assert postings[0].title == "Küchenhilfe (m/w/d)"
        assert postings[1].is_parttime is True  # "Teilzeit" in that title
        assert postings[0].is_parttime is False

    def test_the_recorded_block_page_raises_source_unavailable(self, fixture_path):
        from jobfinder.sources.indeed import IndeedScraper

        blocked = fixture_path("indeed", "blocked_403.html").read_bytes()
        client = RecordingClient([blocked], statuses=[403])
        with pytest.raises(SourceUnavailable):
            list(IndeedScraper(client).search_pages(spec()))
        assert len(client.calls) == 1

    def test_a_junk_200_page_yields_no_postings_and_no_crash(self):
        from jobfinder.sources.indeed import IndeedScraper

        client = RecordingClient(["<html><body>{}</body></html>"])
        pages = list(IndeedScraper(client).search_pages(spec()))
        assert len(pages) == 1 and pages[0].postings == []


# -- the shared JobPosting mapping, at source level --------------------------------


class TestSharedDetail:
    def test_stepstone_detail_uses_the_shared_jsonld_path(self, fixture_path):
        from jobfinder.sources.base import RawPosting
        from jobfinder.sources.stepstone import StepStoneScraper

        detail = fixture_path("xing", "detail_aushilfe_einzelhandel.html").read_text(
            encoding="utf-8"
        )
        client = RecordingClient([detail])
        stub = RawPosting(
            job_id="SS:14298033",
            source="SS",
            source_id="14298033",
            title="Aushilfe im Verkauf Minijob (m/w/d)",
            source_url="https://www.stepstone.de/x",
        )
        posting = StepStoneScraper(client).fetch_detail(stub)
        assert posting.company == "Walbusch Walter Busch GmbH & Co. KG"  # from JSON-LD
        assert posting.is_minijob is True

    def test_indeed_detail_uses_the_shared_jsonld_path(self, fixture_path):
        from jobfinder.sources.base import RawPosting
        from jobfinder.sources.indeed import IndeedScraper

        detail = fixture_path("xing", "detail_aushilfe_einzelhandel.html").read_text(
            encoding="utf-8"
        )
        client = RecordingClient([detail])
        stub = RawPosting(
            job_id="ID:8a1b2c3d4e5f60718293a4b5",
            source="ID",
            source_id="8a1b2c3d4e5f60718293a4b5",
            title="Küchenhilfe (m/w/d)",
            source_url="https://de.indeed.com/x",
        )
        posting = IndeedScraper(client).fetch_detail(stub)
        assert posting.city == "Ingolstadt"  # from JSON-LD
        assert posting.description and "<" not in posting.description
