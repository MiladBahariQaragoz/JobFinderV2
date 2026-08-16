"""Contract tests for the Kleinanzeigen adapter — recorded pages, never hand-made HTML.

The fixtures are real: `list_ingolstadt.html` is the offers-only location browse
for Ingolstadt (27 ads, 2026-08-16), `detail_alltagshelfer.html` the first of
them — a Minijob-worded ad, chosen on purpose. Where a test needs a signal the
page happens not to carry, it copies a real `article.aditem` and changes that
one thing, the pattern the BA and Arbeitnow suites set.
"""

from __future__ import annotations

import copy

from bs4 import BeautifulSoup

from jobfinder.search_spec import SearchSpec

DETAIL_AD_ID = "2637969782"  # Produktionsmitarbeiter — the first ad on the recorded page
MINIJOB_AD_ID = "3485707105"  # "Studentenjob: Aushilfe Warenverräumung" — Aushilfe wording


def spec(**overrides) -> SearchSpec:
    parts = dict(
        mode="general",
        employment_types=["minijob", "parttime"],
        city_names=["Ingolstadt"],
    )
    parts.update(overrides)
    return SearchSpec.build(**parts)


def list_html(fixture_path) -> str:
    return fixture_path("kleinanzeigen", "list_ingolstadt.html").read_text(encoding="utf-8")


def detail_html(fixture_path) -> str:
    return fixture_path("kleinanzeigen", "detail_produktionsmitarbeiter.html").read_text(
        encoding="utf-8"
    )


class RecordingClient:
    """Stands in for the PoliteClient: serves scripted HTML pages, records calls."""

    def __init__(self, pages: list[str]):
        self.pages = list(pages)
        self.calls: list[str] = []

    def get(self, url, params=None, headers=None):
        from jobfinder.sources.http import Response

        self.calls.append(url)
        body = self.pages.pop(0).encode("utf-8")
        return Response(status=200, body=body, headers={})


def page_of(html: str) -> str:
    return html


# -- the list page ---------------------------------------------------------------


class TestParseList:
    def test_kleinanzeigen_fixture_yields_25_listing_urls_from_one_page(self, fixture_path):
        from jobfinder.sources.kleinanzeigen import parse_list

        postings, next_href = parse_list(list_html(fixture_path))
        assert len(postings) == 27  # the recorded page carries 27 ads (the plan said ~25)
        assert all(p.source == "KA" for p in postings)

    def test_list_fields_map_onto_the_posting(self, fixture_path):
        from jobfinder.sources.kleinanzeigen import parse_list

        postings, _ = parse_list(list_html(fixture_path))
        first = next(p for p in postings if p.source_id == DETAIL_AD_ID)
        assert first.job_id == f"KA:{DETAIL_AD_ID}"
        assert first.title == "Produktionsmitarbeiter (m/w/d)"
        assert first.city == "Ingolstadt"
        assert first.plz == "85053"
        assert first.source_url == (
            "https://www.kleinanzeigen.de/s-anzeige/produktionsmitarbeiter-m-w-d-/"
            "2637969782-111-7614"
        )
        assert first.description is None  # the list page carries only a preview

    def test_the_sites_own_next_link_is_returned(self, fixture_path):
        from jobfinder.sources.kleinanzeigen import parse_list

        _, next_href = parse_list(list_html(fixture_path))
        assert next_href == "/s-jobs/ingolstadt/anzeige:angebote/seite:2/c102l7586"

    def test_a_page_with_no_ads_parses_to_nothing(self):
        from jobfinder.sources.kleinanzeigen import parse_list

        postings, next_href = parse_list("<html><body><div>Keine Anzeigen</div></body></html>")
        assert postings == [] and next_href is None

    def test_minijob_wording_sets_the_minijob_flag(self, fixture_path):
        from jobfinder.sources.kleinanzeigen import parse_list

        postings, _ = parse_list(list_html(fixture_path))
        aushilfe = next(p for p in postings if p.source_id == MINIJOB_AD_ID)
        assert aushilfe.is_minijob is True  # "Aushilfe" — one of the Phase 6 words

    def test_gesuche_ads_are_excluded(self, fixture_path):
        """Offers-only browsing excludes them at the source; the parser holds the line."""
        from jobfinder.sources.kleinanzeigen import parse_list

        soup = BeautifulSoup(list_html(fixture_path), "html.parser")
        wanted = copy.copy(soup.select("article.aditem")[0])
        wanted["data-adid"] = "9999999999"
        wanted["data-href"] = "/s-gesuch/minijob-gesucht/9999999999-123-1"
        soup.select_one("article.aditem").insert_before(wanted)
        postings, _ = parse_list(str(soup))
        assert all(p.source_id != "9999999999" for p in postings)


# -- query building --------------------------------------------------------------


class TestListSnippet:
    """The list page carries the first lines of each ad — free signal.

    Hand-check of the recorded page: 27 ads, 3 of them genuinely small jobs,
    and filtering on the title alone found one. The snippet is already in the
    response we paid for, so reading it costs nothing and no extra request.
    """

    def snippet_ad(self, fixture_path, *, title: str, snippet: str):
        from jobfinder.sources.kleinanzeigen import parse_list

        soup = BeautifulSoup(list_html(fixture_path), "html.parser")
        article = copy.copy(soup.select("article.aditem")[0])
        article.select_one(".text-module-begin a.ellipsis").string = title
        article.select_one(".aditem-main--middle--description").string = snippet
        postings, _ = parse_list(str(article))
        return postings[0]

    def test_wording_in_the_snippet_sets_the_flag(self, fixture_path):
        posting = self.snippet_ad(
            fixture_path,
            title="Fahrscheinkontrolleur (m|w|d) | Sicherheit",  # says nothing
            snippet="Wir zahlen auf 450 € Basis, ideal als Nebenjob.",
        )
        assert posting.is_minijob is True

    def test_the_snippet_is_not_stored_as_the_ad_text(self, fixture_path):
        # It is two lines of teaser. Storing it would set has_description and
        # rob her of the real ad, because the runner skips the detail fetch
        # for a posting that already carries text.
        posting = self.snippet_ad(
            fixture_path, title="Produktionsmitarbeiter (m/w/d)", snippet="Wir verbinden Jobs..."
        )
        assert posting.description is None
        assert posting.has_description is False

    def test_an_ad_the_snippet_rescues_survives_the_filter(self, fixture_path):
        from jobfinder.sources.kleinanzeigen import KleinanzeigenScraper

        soup = BeautifulSoup(list_html(fixture_path), "html.parser")
        article = soup.select("article.aditem")[0]
        article.select_one(".text-module-begin a.ellipsis").string = "Fahrscheinkontrolleur (m|w|d)"
        article.select_one(".aditem-main--middle--description").string = "Minijob, 15 Std./Woche"

        # The recorded page carries a next link, so the walk asks for one more.
        client = RecordingClient([str(soup), "<html><body></body></html>"])
        pages = list(KleinanzeigenScraper(client).search_pages(spec(employment_types=["minijob"])))
        kept = [posting.title for page in pages for posting in page.postings]
        assert "Fahrscheinkontrolleur (m|w|d)" in kept


class TestQueries:
    def test_one_browse_query_per_city_and_it_is_offers_only(self):
        from jobfinder.sources.kleinanzeigen import build_queries

        queries = build_queries(spec(city_names=["Ingolstadt", "München"]))
        assert [q.url for q in queries] == [
            "https://www.kleinanzeigen.de/s-jobs/ingolstadt/anzeige:angebote/c102l7586",
            "https://www.kleinanzeigen.de/s-jobs/muenchen/anzeige:angebote/c102l6411",
        ]

    def test_resuming_page_three_builds_the_seite_url(self):
        from jobfinder.sources.kleinanzeigen import build_queries

        query = build_queries(spec())[0]
        assert query.url_for_page(3) == (
            "https://www.kleinanzeigen.de/s-jobs/ingolstadt/anzeige:angebote/seite:3/c102l7586"
        )

    def test_a_city_without_a_location_id_is_skipped_loudly(self, monkeypatch):
        import jobfinder.cities as cities
        from jobfinder.sources.kleinanzeigen import build_queries

        monkeypatch.delitem(cities.KLEINANZEIGEN_LOCATIONS, "Ingolstadt")
        try:
            build_queries(spec())
            raise AssertionError("expected a loud failure")
        except ValueError as exc:
            assert "Ingolstadt" in str(exc)
            assert "location id" in str(exc)


# -- the detail page -------------------------------------------------------------


class TestDetail:
    def test_listing_parses_title_location_date_and_body(self, fixture_path):
        from jobfinder.sources.kleinanzeigen import parse_detail

        posting = parse_detail(detail_html(fixture_path), source_url="https://x")
        assert posting.title == "Produktionsmitarbeiter (m/w/d)"
        assert posting.city == "Ingolstadt"  # "85053 Bayern - Ingolstadt" on the page
        assert posting.plz == "85053"
        assert posting.published_at == "2026-08-14"  # 14.08.2026, ISO for the store
        assert "ZeitWerk Personal" in posting.description
        assert not posting.description.startswith("Beschreibung")  # the heading is dropped

    def test_detail_wording_sets_the_flags(self, fixture_path):
        # The recorded ad's own wording signals nothing, so one field changes:
        # the real page with its title rewritten to carry the Phase 6 words.
        from jobfinder.sources.kleinanzeigen import parse_detail

        markup = detail_html(fixture_path).replace(
            "Produktionsmitarbeiter (m/w/d)", "Aushilfe Verkauf, Minijob (m/w/d)"
        )
        posting = parse_detail(markup, source_url="https://x")
        assert posting.is_minijob is True

    def test_a_page_that_is_not_an_ad_parses_to_none(self):
        from jobfinder.sources.kleinanzeigen import parse_detail

        assert parse_detail("<html><body>404</body></html>", source_url="https://x") is None

    def test_a_login_walled_list_page_is_detected_and_skipped_not_retried(self):
        import pytest

        from jobfinder.sources.base import LoginWall
        from jobfinder.sources.kleinanzeigen import KleinanzeigenScraper

        wall = "<html><body><h1>Bitte melde dich an, um fortzufahren</h1></body></html>"
        client = RecordingClient([wall])
        with pytest.raises(LoginWall):
            list(KleinanzeigenScraper(client).search_pages(spec()))
        assert len(client.calls) == 1  # looked once, did not hammer the wall


# -- pagination and the spec filter ----------------------------------------------


def art(adid: str, title: str, city_plz: str = "85053 Ingolstadt") -> str:
    return (
        f'<article class="aditem" data-adid="{adid}" data-href="/s-anzeige/x/{adid}-123-1">'
        f'<div class="aditem-main"><div class="aditem-main--top">'
        f'<div class="aditem-main--top--left">{city_plz}</div></div>'
        f'<div class="aditem-main--middle"><h2 class="text-module-begin">'
        f'<a class="ellipsis" href="/s-anzeige/x/{adid}-123-1">{title}</a></h2>'
        f'<p class="aditem-main--middle--description">v</p></div></div></article>'
    )


def list_page(ads: str, next_href: str | None = None) -> str:
    nxt = f'<a class="pagination-next" href="{next_href}">next</a>' if next_href else ""
    return f'<html><body><ul class="mvbox">{ads}</ul>{nxt}</body></html>'


class TestSearchPages:
    def scraper(self, payloads):
        from jobfinder.sources.kleinanzeigen import KleinanzeigenScraper

        client = RecordingClient(payloads)
        return KleinanzeigenScraper(client), client

    def test_pagination_follows_the_sites_next_links(self):
        scraper, client = self.scraper(
            [
                list_page(art("1", "Reinigungskraft Minijob"), "/s-jobs/ingolstadt/seite:2/c102"),
                list_page(art("2", "Küchenhilfe Aushilfe")),
            ]
        )
        pages = list(scraper.search_pages(spec()))
        assert [p.page for p in pages] == [1, 2]
        assert client.calls[0].startswith("https://www.kleinanzeigen.de/s-jobs/")

    def test_the_walk_is_capped_at_max_pages(self):
        from jobfinder.sources.kleinanzeigen import MAX_PAGES

        pages_of_ads = [list_page(art(str(i), "Minijob Kraft"), "/next") for i in range(99)]
        scraper, _ = self.scraper(pages_of_ads)
        assert len(list(scraper.search_pages(spec()))) == MAX_PAGES

    def test_resume_reenters_at_the_stored_page(self):
        scraper, client = self.scraper([list_page(art("1", "Minijob"))])
        pages = list(scraper.search_pages(spec(), start_query_index=0, start_page=3))
        assert "seite:3" in client.calls[0]
        assert pages[0].page == 3

    def test_types_are_alternatives_minijob_wording_passes_a_minijob_spec(self):
        scraper, _ = self.scraper([list_page(art("1", "Reinigungskraft Minijob"))])
        pages = list(scraper.search_pages(spec(employment_types=["minijob"])))
        assert [p.source_id for p in pages[0].postings] == ["1"]

    def test_an_ad_signalling_none_of_her_types_is_filtered_out(self):
        scraper, _ = self.scraper([list_page(art("1", "Produktionsmitarbeiter (m/w/d)"))])
        pages = list(scraper.search_pages(spec(employment_types=["minijob", "werkstudent"])))
        assert pages[0].postings == []

    def test_fetch_detail_parses_the_recorded_ad(self, fixture_path):
        from jobfinder.sources.kleinanzeigen import KleinanzeigenScraper, parse_list

        stub = parse_list(list_html(fixture_path))[0][0]
        client = RecordingClient([detail_html(fixture_path)])
        posting = KleinanzeigenScraper(client).fetch_detail(stub)
        assert posting.job_id == stub.job_id  # the ad's identity survives the merge
        assert posting.description and "ZeitWerk Personal" in posting.description
        assert posting.city == "Ingolstadt"
        assert client.calls == [stub.source_url]

    def test_a_login_walled_detail_page_returns_the_stub_not_a_crash(self, fixture_path):
        from jobfinder.sources.kleinanzeigen import KleinanzeigenScraper, parse_list

        wall = "<html><body><h1>Bitte melde dich an, um fortzufahren</h1></body></html>"
        scraper = KleinanzeigenScraper(RecordingClient([wall]))
        stub = parse_list(list_html(fixture_path))[0][0]
        assert scraper.fetch_detail(stub) is stub  # listed, just unenriched
