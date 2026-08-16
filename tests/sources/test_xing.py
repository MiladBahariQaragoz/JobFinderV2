"""Contract tests for the Xing adapter — recorded pages, never hand-made HTML.

`list_aushilfe_ingolstadt.html` is the public SEO page for that search
(2026-08-16, 19 job links, no pagination — `?page=2` serves the same links).
`detail_aushilfe_einzelhandel.html` carries a full schema.org JobPosting,
which is the primary extraction path; the DOM selectors are the fallback for
the day the script block goes missing.
"""

from __future__ import annotations

import re

from jobfinder.search_spec import SearchSpec


def spec(**overrides) -> SearchSpec:
    parts = dict(mode="general", employment_types=["minijob"], city_names=["Ingolstadt"])
    parts.update(overrides)
    return SearchSpec.build(**parts)


def list_html(fixture_path) -> str:
    return fixture_path("xing", "list_aushilfe_ingolstadt.html").read_text(encoding="utf-8")


def detail_html(fixture_path) -> str:
    return fixture_path("xing", "detail_aushilfe_einzelhandel.html").read_text(encoding="utf-8")


class RecordingClient:
    """Stands in for the PoliteClient: serves scripted HTML pages, records calls."""

    def __init__(self, pages: list[str]):
        self.pages = list(pages)
        self.calls: list[str] = []

    def get(self, url, params=None, headers=None):
        from jobfinder.sources.http import Response

        self.calls.append(url)
        return Response(status=200, body=self.pages.pop(0).encode("utf-8"), headers={})


# -- the list page ---------------------------------------------------------------


class TestParseList:
    def test_xing_fixture_yields_expected_listing_urls(self, fixture_path):
        from jobfinder.sources.xing import parse_list

        postings = parse_list(list_html(fixture_path))
        assert len(postings) == 19  # every job anchor on the recorded page
        assert all(p.source == "XI" for p in postings)

        example = next(p for p in postings if p.source_id == "156837029")
        assert example.job_id == "XI:156837029"
        assert (
            example.title == "Aushilfe im Einzelhandel (m/w/d) - Minijob Ingolstadt"
        )  # aria-label
        assert example.source_url == (
            "https://www.xing.com/jobs/ingolstadt-aushilfe-einzelhandel-minijob-ingolstadt-156837029"
        )

    def test_navigation_and_directory_links_are_not_jobs(self, fixture_path):
        from jobfinder.sources.xing import parse_list

        postings = parse_list(list_html(fixture_path))
        assert all(re.fullmatch(r"\d{6,}", p.source_id) for p in postings)

    def test_a_page_with_no_job_links_parses_to_nothing(self):
        from jobfinder.sources.xing import parse_list

        assert parse_list("<html><body><a href='/jobs/directory/a'>A</a></body></html>") == []


# -- query building --------------------------------------------------------------


class TestQueries:
    def test_one_seo_page_per_search_term_and_city(self):
        from jobfinder.sources.xing import build_queries

        urls = [
            q.url
            for q in build_queries(
                spec(employment_types=["minijob", "werkstudent"], city_names=["Ingolstadt"])
            )
        ]
        assert urls == [
            "https://www.xing.com/jobs/minijob-ingolstadt",
            "https://www.xing.com/jobs/werkstudent-ingolstadt",
        ]

    def test_her_keywords_get_pages_of_their_own(self):
        from jobfinder.sources.xing import build_queries

        urls = [
            q.url for q in build_queries(spec(employment_types=["minijob"], keywords=["aushilfe"]))
        ]
        assert "https://www.xing.com/jobs/aushilfe-ingolstadt" in urls

    def test_umluats_fold_into_the_sites_slugs(self):
        from jobfinder.sources.xing import build_queries

        urls = [q.url for q in build_queries(spec(city_names=["München", "Nürnberg"]))]
        assert "https://www.xing.com/jobs/minijob-muenchen" in urls
        assert "https://www.xing.com/jobs/minijob-nuernberg" in urls


# -- the detail page: JSON-LD first, selectors second -----------------------------


class TestDetail:
    def test_jsonld_extraction_is_preferred_over_css_selectors(self, fixture_path):
        # One field changed in the DOM only: the h1 says something else, the
        # JobPosting block still says the truth — and it wins.
        import re as re_lib

        from jobfinder.sources.xing import parse_detail

        real_title = "Aushilfe im Einzelhandel (m/w/d) - Minijob Ingolstadt"
        doctored = re_lib.sub(
            r"<h1[^>]*>.*?</h1>",
            "<h1>DOM-Lüge: Fensterputzer Vollzeit</h1>",
            detail_html(fixture_path),
            count=1,
            flags=re_lib.DOTALL,
        )
        assert "DOM-Lüge" in doctored  # the swap really happened
        posting = parse_detail(doctored, source_url="https://x")
        assert posting.title == real_title  # from the structured data, not the DOM

    def test_the_recorded_detail_maps_onto_the_posting(self, fixture_path):
        from jobfinder.sources.xing import parse_detail

        posting = parse_detail(detail_html(fixture_path), source_url="https://x")
        assert posting.title == "Aushilfe im Einzelhandel (m/w/d) - Minijob Ingolstadt"
        assert posting.company == "Walbusch Walter Busch GmbH & Co. KG"
        assert posting.city == "Ingolstadt"
        assert "<" not in posting.description  # JSON-LD HTML became text
        assert "Unsere Zielgruppe kennen und studieren wir genau" in posting.description
        assert posting.is_minijob is True  # "Minijob" in title and description
        assert posting.published_at  # datePosted made it through

    def test_missing_jsonld_falls_back_to_selectors_on_a_real_saved_page(self, fixture_path):
        import re

        from jobfinder.sources.xing import parse_detail

        stripped = re.sub(
            r"<script[^>]*application/ld\+json[^>]*>.*?</script>",
            "",
            detail_html(fixture_path),
            flags=re.DOTALL,
        )
        posting = parse_detail(stripped, source_url="https://x")
        assert posting is not None
        assert posting.title == "Aushilfe im Einzelhandel (m/w/d) - Minijob Ingolstadt"
        assert posting.company  # the DOM fallback still names the employer
        assert posting.description is None  # no structured data, no body we can trust

    def test_a_page_with_neither_jsonld_nor_dom_parses_to_none(self):
        from jobfinder.sources.xing import parse_detail

        assert parse_detail("<html><body>404</body></html>", source_url="https://x") is None


# -- search_pages and fetch_detail ------------------------------------------------


class TestSearchPages:
    def scraper(self, payloads):
        from jobfinder.sources.xing import XingScraper

        client = RecordingClient(payloads)
        return XingScraper(client), client

    def test_one_page_per_query_and_no_pagination_requests(self, fixture_path):
        scraper, client = self.scraper([list_html(fixture_path), list_html(fixture_path)])
        pages = list(scraper.search_pages(spec(employment_types=["minijob", "werkstudent"])))
        assert [p.query_index for p in pages] == [0, 1]
        assert all(p.page == 1 for p in pages)  # SEO pages do not paginate
        assert len(client.calls) == 2

    def test_the_same_job_on_two_queries_appears_once_per_page_anyway(self, fixture_path):
        # Both the minijob and aushilfe pages list the same Walbusch ad; the
        # store dedupes on job_id — the adapter's job is only to report it.
        scraper, _ = self.scraper([list_html(fixture_path), list_html(fixture_path)])
        both = spec(keywords=["aushilfe"], employment_types=["minijob"])
        pages = list(scraper.search_pages(both))
        assert pages[0].postings and pages[1].postings

    def test_resume_past_the_first_query_starts_at_the_second(self, fixture_path):
        scraper, client = self.scraper([list_html(fixture_path)])
        pages = list(scraper.search_pages(spec(), start_query_index=1, start_page=1))
        assert pages == []  # only one query in this spec; nothing left to do
        assert client.calls == []

    def test_fetch_detail_fills_the_recorded_posting(self, fixture_path):
        from jobfinder.sources.xing import parse_list

        scraper, client = self.scraper([detail_html(fixture_path)])
        stub = next(p for p in parse_list(list_html(fixture_path)) if p.source_id == "156837029")
        posting = scraper.fetch_detail(stub)
        assert posting.job_id == stub.job_id
        assert posting.company == "Walbusch Walter Busch GmbH & Co. KG"
        assert posting.city == "Ingolstadt"
        assert posting.description
        assert client.calls == [stub.source_url]

    def test_a_login_walled_detail_page_returns_the_stub_not_a_crash(self, fixture_path):
        from jobfinder.sources.xing import parse_list

        wall = "<html><body><h1>Bitte melde dich an, um fortzufahren</h1></body></html>"
        scraper, client = self.scraper([wall])
        stub = parse_list(list_html(fixture_path))[0]
        posting = scraper.fetch_detail(stub)
        assert posting is stub  # the job stays listed, just unenriched
        assert len(client.calls) == 1

    def test_a_login_walled_list_page_raises_once(self):
        import pytest

        from jobfinder.sources.base import LoginWall
        from jobfinder.sources.xing import XingScraper

        wall = "<html><body><h1>Bitte melde dich an, um fortzufahren</h1></body></html>"
        client = RecordingClient([wall])
        with pytest.raises(LoginWall):
            list(XingScraper(client).search_pages(spec()))
        assert len(client.calls) == 1
