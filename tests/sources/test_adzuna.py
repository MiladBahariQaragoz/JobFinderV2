"""Adzuna adapter — the aggregator, measured before it was built.

The key arrived on 2026-08-16 and `search_minijob_ingolstadt.json` is a real
50-result response recorded that day (the account's app_id is redacted, since
Adzuna stamps it into every `redirect_url` and fixtures are committed).

What the measurement found and these tests encode: the API's description is
capped at 500 characters and almost always cut mid-sentence, so the teaser is
never stored as the ad — `fetch_detail` follows the redirect and reads the
JSON-LD ad behind it, keeping the teaser only when that redirect is refused.
"""

from __future__ import annotations

import json

import pytest

from jobfinder.config import Settings
from jobfinder.search_spec import SearchSpec
from jobfinder.sources.registry import build_adapters


def spec(**overrides) -> SearchSpec:
    parts = dict(mode="general", employment_types=["parttime"], city_names=["Ingolstadt"])
    parts.update(overrides)
    return SearchSpec.build(**parts)


@pytest.fixture
def no_keys(monkeypatch):
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv("ADZUNA_APP_ID", "test-id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "test-key")


class TestSkip:
    def test_adzuna_adapter_is_skipped_cleanly_without_keys(self, tmp_path, no_keys):
        settings = Settings(project_root=tmp_path, enabled_sources=("ba", "adzuna"))
        built = build_adapters(settings, lambda _s, _delay=None: object())
        assert [adapter.source for adapter in built.adapters] == ["BA"]  # no AZ, no crash
        assert dict(built.skipped)["adzuna"] == "no API key in .env"

    def test_with_keys_the_adapter_is_built(self, tmp_path, keys):
        settings = Settings(project_root=tmp_path, enabled_sources=("adzuna",))
        built = build_adapters(settings, lambda _s, _delay=None: object())
        assert [adapter.source for adapter in built.adapters] == ["AZ"]

    def test_an_adapter_without_keys_refuses_to_search_readably(self, no_keys):
        from jobfinder.sources.adzuna import AdzunaApi

        api = AdzunaApi(client=None)  # constructed directly, keys vanished since
        with pytest.raises(Exception) as excinfo:
            list(api.search_pages(spec()))
        message = str(excinfo.value)
        assert "ADZUNA_APP_ID" in message and ".env" in message


def load_page(fixture_path) -> dict:
    return json.loads(
        fixture_path("adzuna", "search_minijob_ingolstadt.json").read_text(encoding="utf-8")
    )


class RecordingClient:
    """Serves scripted answers, records every URL asked for."""

    def __init__(self, *, pages=(), details=()):
        self.pages = list(pages)
        self.details = list(details)
        self.calls: list[str] = []

    def get_json(self, url, params=None, headers=None):
        self.calls.append(url)
        return self.pages.pop(0)

    def get(self, url, params=None, headers=None):
        from jobfinder.sources.http import Response

        self.calls.append(url)
        status, body = self.details.pop(0)
        return Response(status=status, body=body.encode("utf-8"), headers={})


_AD_TEXT = (
    "<p>Wir suchen eine Aushilfe auf Minijob-Basis f\\u00fcr unsere Theke in Ingolstadt. "
    "Deine Aufgaben: Kunden bedienen, Ware auff\\u00fcllen, Kasse. Wir bieten flexible "
    "Zeiten und ein nettes Team. Deutschkenntnisse auf B1-Niveau sind erw\\u00fcnscht, "
    "Vorkenntnisse nicht n\\u00f6tig.</p>"
)
JOB_AD_PAGE = (
    '<html><body><script type="application/ld+json">'
    '{"@context":"https://schema.org","@type":"JobPosting",'
    '"title":"Aushilfe Verkauf (m/w/d)","datePosted":"2026-08-10",'
    '"hiringOrganization":{"@type":"Organization","name":"Bäckerei Müller"},'
    f'"description":"{_AD_TEXT}"}}'
    "</script></body></html>"
)


class TestParsePage:
    def test_the_recorded_response_parses_into_postings(self, fixture_path):
        from jobfinder.sources.adzuna import parse_page

        postings = parse_page(load_page(fixture_path), spec(employment_types=["minijob"]))
        assert len(postings) == 50
        assert all(posting.source == "AZ" for posting in postings)
        assert all(posting.job_id.startswith("AZ:") for posting in postings)

    def test_a_row_maps_onto_the_posting(self, fixture_path):
        from jobfinder.sources.adzuna import parse_page

        posting = parse_page(load_page(fixture_path), spec(employment_types=["minijob"]))[0]
        assert posting.source_id == "5770531031"
        assert posting.title == "Ausbildung zum Kommunikationsprofi! Promoter als Minijob (m/w/d)"
        assert posting.company == "Apollon Dialogmarketing GmbH"
        assert posting.published_at == "2026-06-20T12:20:44Z"
        assert posting.lat == pytest.approx(48.77669)
        assert posting.source_url.startswith("https://www.adzuna.de/land/ad/5770531031")

    def test_the_city_is_the_one_she_searched_not_the_hamlet(self, fixture_path):
        # Adzuna's display_name reads "Pettenhofen, Ingolstadt" and its area
        # list ends at the district. Her store dedupes on the city, and the
        # Bundesagentur calls the same place "Ingolstadt, Donau".
        from jobfinder.sources.adzuna import parse_page

        posting = parse_page(load_page(fixture_path), spec(employment_types=["minijob"]))[0]
        assert posting.city == "Ingolstadt"

    def test_wording_sets_the_employment_flags(self, fixture_path):
        from jobfinder.sources.adzuna import parse_page

        postings = parse_page(load_page(fixture_path), spec(employment_types=["minijob"]))
        assert any(posting.is_minijob for posting in postings)

    def test_the_teaser_is_never_stored_as_the_ad(self, fixture_path):
        # 500 characters, cut mid-sentence. Storing it would set
        # has_description and stop the runner fetching the real ad.
        from jobfinder.sources.adzuna import parse_page

        postings = parse_page(load_page(fixture_path), spec(employment_types=["minijob"]))
        assert all(posting.description is None for posting in postings)
        assert all(posting.has_description is False for posting in postings)


class TestDetail:
    def adapter(self, fixture_path, details):
        from jobfinder.sources.adzuna import AdzunaApi

        # count is 204, so the walk asks for the pages after this one too.
        client = RecordingClient(
            pages=[load_page(fixture_path), {"count": 204, "results": []}], details=details
        )
        api = AdzunaApi(client)
        pages = list(api.search_pages(spec(employment_types=["minijob"])))
        return api, pages[0].postings[0], client

    def test_fetch_detail_follows_the_redirect_and_reads_the_real_ad(self, fixture_path, keys):
        api, posting, client = self.adapter(fixture_path, [(200, JOB_AD_PAGE)])

        filled = api.fetch_detail(posting)

        assert client.calls[-1] == posting.source_url  # the redirect, followed
        assert filled.has_description is True
        assert "Theke" in filled.description  # the ad, not the teaser
        assert len(filled.description) > 200

    def test_a_refused_redirect_keeps_the_teaser_rather_than_nothing(self, fixture_path, keys):
        # 39 % of them were refused when this was measured. A teaser is thin,
        # but it is what she has to go on, and Phase 7 can say so.
        api, posting, _ = self.adapter(fixture_path, [(403, "<html>Access denied</html>")])

        filled = api.fetch_detail(posting)

        assert filled.has_description is True
        assert filled.description.startswith("Dein Promoter Job mit Sinn")

    def test_a_wall_stops_the_adapter_asking_for_any_more_ads(self, fixture_path, keys):
        # Measured live: after roughly forty redirect follows, adzuna.de began
        # answering "Zugriff verweigert … Melde Dich an um fortzufahren" to
        # every one. §8 rule 6 — a page that wants an account is skipped, not
        # retried — so the first wall ends the following for this run instead
        # of buying fifty more refusals.
        from jobfinder.sources.adzuna import AdzunaApi

        denied = (
            "<html><body><h1>Zugriff verweigert</h1><p>Unsere Systeme haben verdächtiges "
            "Verhalten festgestellt. Melde Dich an um fortzufahren.</p></body></html>"
        )
        client = RecordingClient(
            pages=[load_page(fixture_path), {"count": 204, "results": []}],
            details=[(403, denied)],
        )
        api = AdzunaApi(client)
        postings = next(iter(api.search_pages(spec(employment_types=["minijob"])))).postings

        first = api.fetch_detail(postings[0])
        calls_after_the_wall = len(client.calls)
        second = api.fetch_detail(postings[1])

        assert first.description.startswith("Dein Promoter Job mit Sinn")  # teaser kept
        assert second.has_description is True  # its teaser too
        assert len(client.calls) == calls_after_the_wall  # and no second refusal bought

    def test_a_page_without_an_ad_on_it_keeps_the_teaser_too(self, fixture_path, keys):
        api, posting, _ = self.adapter(fixture_path, [(200, "<html><body>nothing</body></html>")])

        filled = api.fetch_detail(posting)

        assert filled.description.startswith("Dein Promoter Job mit Sinn")


class TestPagination:
    def test_the_walk_covers_the_reported_count(self, fixture_path, keys):
        from jobfinder.sources.adzuna import AdzunaApi

        page = load_page(fixture_path)  # count = 204, 50 per page -> 5 pages
        client = RecordingClient(pages=[page] * 5)
        pages = list(AdzunaApi(client).search_pages(spec(employment_types=["minijob"])))

        assert [result.page for result in pages] == [1, 2, 3, 4, 5]
        assert "/search/5?" in client.calls[-1]  # the page number rides in the path

    def test_an_empty_page_ends_the_walk(self, fixture_path, keys):
        from jobfinder.sources.adzuna import AdzunaApi

        client = RecordingClient(pages=[{"count": 204, "results": []}])
        assert list(AdzunaApi(client).search_pages(spec(employment_types=["minijob"]))) == []

    def test_resume_reenters_at_the_stored_page(self, fixture_path, keys):
        from jobfinder.sources.adzuna import AdzunaApi

        client = RecordingClient(pages=[{"count": 204, "results": []}])
        list(AdzunaApi(client).search_pages(spec(employment_types=["minijob"]), start_page=4))
        assert "/search/4?" in client.calls[0]


def queries_for(**overrides):
    from jobfinder.sources.adzuna import build_queries

    return build_queries(spec(**overrides), app_id="test-id", app_key="test-key")


class TestBuildQueries:
    def test_query_carries_keys_city_and_radius(self, keys):
        queries = queries_for()
        assert len(queries) == 1
        params = queries[0].params()
        assert params["app_id"] == "test-id"
        assert params["app_key"] == "test-key"
        assert params["where"] == "Ingolstadt"
        assert params["distance"] == 25  # her default radius, in km
        assert params["results_per_page"] == 50

    def test_one_query_per_employment_type_never_stacked(self, keys):
        # The Phase 4 audit rule: types are alternatives. Adzuna's full_time /
        # part_time flags are combined with AND server-side, so stacking them
        # would ask for a job that is both — one query per type instead.
        queries = queries_for(employment_types=["parttime", "fulltime"])
        assert len(queries) == 2
        flags = [q.params().get("part_time", 0) + q.params().get("full_time", 0) for q in queries]
        assert flags == [1, 1]  # exactly one flag set per query

    def test_minijob_travels_as_a_search_term(self, keys):
        # Adzuna has no minijob flag, and a query with neither flag nor term
        # asks for every job in the city — 204 real minijobs became noise.
        queries = queries_for(employment_types=["minijob"])
        assert queries[0].params()["what"] == "Minijob"

    def test_werkstudent_and_internship_travel_as_search_terms(self, keys):
        queries = queries_for(employment_types=["werkstudent", "internship"])
        whats = {q.params().get("what") for q in queries}
        assert whats == {"Werkstudent", "Praktikum"}
        for query in queries:
            assert "part_time" not in query.params()
            assert "full_time" not in query.params()

    def test_her_keywords_become_the_what_term(self, keys):
        queries = queries_for(employment_types=["parttime"], keywords=["kellner"])
        assert queries[0].params()["what"] == "kellner"

    def test_the_url_targets_the_german_search_endpoint(self, keys):
        query = queries_for()[0]
        assert query.url().startswith("https://api.adzuna.com/v1/api/jobs/de/search/1?")
