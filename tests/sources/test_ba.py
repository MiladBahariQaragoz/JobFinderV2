"""Contract tests for the Bundesagentur adapter — recorded fixtures, never hand-made JSON."""

from __future__ import annotations

import dataclasses
import json

import pytest

from jobfinder.search_spec import SearchSpec


def spec(**overrides) -> SearchSpec:
    parts = dict(
        mode="general",
        employment_types=["minijob"],
        city_names=["Ingolstadt"],
    )
    parts.update(overrides)
    return SearchSpec.build(**parts)


# -- building queries from her spec -------------------------------------------


class TestBuildQueries:
    def test_spec_with_minijob_maps_to_ba_angebotsart_and_arbeitszeit_params(self):
        from jobfinder.sources.ba import build_queries

        queries = build_queries(spec(employment_types=["minijob"]))
        assert len(queries) == 1
        params = queries[0].params()
        assert params["angebotsart"] == 1  # ARBEIT — verified live
        assert params["arbeitszeit"] == ["mj"]  # minijob — verified live
        assert "was" not in params

    def test_spec_with_three_cities_produces_three_queries_with_correct_umkreis(self):
        from jobfinder.sources.ba import build_queries

        queries = build_queries(
            spec(
                city_names=["Neuburg an der Donau", "Ingolstadt", "München"],
                radius_km={"München": 40},
            )
        )
        assert len(queries) == 3
        by_city = {query.params()["wo"]: query for query in queries}
        assert by_city["Neuburg an der Donau"].params()["umkreis"] == 25
        assert by_city["Ingolstadt"].params()["umkreis"] == 25
        assert by_city["München"].params()["umkreis"] == 40

    def test_city_name_is_sent_with_its_umlauts(self):
        # The BA geocoder rejects "Muenchen" silently — canonical names only.
        from jobfinder.sources.ba import build_queries

        queries = build_queries(spec(city_names=["München"]))
        assert queries[0].params()["wo"] == "München"
        assert "wo=M%C3%BCnchen" in queries[0].url()

    def test_multiple_employment_types_stack_arbeitszeit_codes(self):
        from jobfinder.sources.ba import build_queries

        queries = build_queries(spec(employment_types=["minijob", "parttime", "fulltime"]))
        assert queries[0].params()["arbeitszeit"] == ["mj", "tz", "vz"]

    def test_werkstudent_has_no_arbeitszeit_code_so_it_rides_in_was(self):
        from jobfinder.sources.ba import build_queries

        queries = build_queries(spec(employment_types=["werkstudent"]))
        params = queries[0].params()
        assert params["was"] == "Werkstudent"
        assert "arbeitszeit" not in params

    def test_internship_rides_in_was_too(self):
        from jobfinder.sources.ba import build_queries

        queries = build_queries(spec(employment_types=["internship"]))
        assert queries[0].params()["was"] == "Praktikum"

    def test_her_keywords_become_the_search_term(self):
        from jobfinder.sources.ba import build_queries

        queries = build_queries(spec(keywords=["umwelttechnik"]))
        assert queries[0].params()["was"] == "umwelttechnik"

    def test_keyword_and_type_keyword_combine(self):
        from jobfinder.sources.ba import build_queries

        queries = build_queries(
            spec(employment_types=["werkstudent", "parttime"], keywords=["Datenanalyse"])
        )
        params = queries[0].params()
        assert params["was"] == "Datenanalyse Werkstudent"
        assert params["arbeitszeit"] == ["tz"]

    def test_werkstudent_keyword_from_her_list_is_not_duplicated(self):
        from jobfinder.sources.ba import build_queries

        queries = build_queries(
            spec(employment_types=["werkstudent"], keywords=["Werkstudent Umwelt"])
        )
        assert queries[0].params()["was"] == "Werkstudent Umwelt"

    def test_keywords_multiply_into_one_query_per_keyword_per_city(self):
        from jobfinder.sources.ba import build_queries

        queries = build_queries(
            spec(city_names=["Ingolstadt", "München"], keywords=["kellner", "küche"])
        )
        assert len(queries) == 4
        terms = {query.params()["was"] for query in queries}
        assert terms == {"kellner", "küche"}

    def test_query_url_carries_the_search_path_and_params(self):
        from jobfinder.sources.ba import build_queries

        query = build_queries(spec())[0]
        url = query.url()
        assert url.startswith(
            "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs?"
        )
        assert "umkreis=25" in url
        assert "page=1" in url


# -- parsing recorded pages ----------------------------------------------------


def load_search_fixture(fixture_path) -> dict:
    path = fixture_path("ba", "jobs_werkstudent_ingolstadt.json")
    return json.loads(path.read_text(encoding="utf-8"))


class TestParsePage:
    def test_ba_fixture_parses_into_raw_postings_with_expected_fields(self, fixture_path):
        from jobfinder.sources.ba import parse_page

        postings = parse_page(load_search_fixture(fixture_path))
        assert len(postings) == 5
        first = postings[0]
        assert first.title == "Werkstudent (m/w/d)"
        assert first.company == "DEKRA Arbeit GmbH"
        assert first.city == "Ingolstadt, Donau"
        assert first.plz == "85051"
        assert first.lat == pytest.approx(48.7258019)
        assert first.lon == pytest.approx(11.4118102)
        assert first.published_at == "2026-08-11"
        assert first.source_url == (
            "https://www.arbeitsagentur.de/jobsuche/jobdetail/11119-4913285274-S"
        )
        assert first.apply_url == "https://jobboard.compleet.com/?externalId=4913285274"

    def test_ba_posting_id_is_source_prefixed_referenznummer(self, fixture_path):
        from jobfinder.sources.ba import parse_page

        first = parse_page(load_search_fixture(fixture_path))[0]
        assert first.job_id == "BA:11119-4913285274-S"
        assert first.source == "BA"
        assert first.source_id == "11119-4913285274-S"

    def test_ba_minijob_flag_is_read_from_istGeringfuegigeBeschaeftigung(self, fixture_path):
        from jobfinder.sources.ba import parse_page

        payload = load_search_fixture(fixture_path)
        assert parse_page(payload)[0].is_minijob is False
        payload["ergebnisliste"][0]["istGeringfuegigeBeschaeftigung"] = True
        assert parse_page(payload)[0].is_minijob is True

    def test_fulltime_and_parttime_flags_follow_the_arbeitszeit_fields(self, fixture_path):
        from jobfinder.sources.ba import parse_page

        payload = load_search_fixture(fixture_path)
        first = parse_page(payload)[0]
        assert first.is_fulltime is True  # arbeitszeitVollzeit
        assert first.is_parttime is False

        payload["ergebnisliste"][0]["arbeitszeitVollzeit"] = False
        payload["ergebnisliste"][0]["arbeitszeitTeilzeitAbend"] = True
        again = parse_page(payload)[0]
        assert again.is_fulltime is False
        assert again.is_parttime is True

    def test_homeoffice_flag_is_read_from_homeofficemoeglich(self, fixture_path):
        from jobfinder.sources.ba import parse_page

        payload = load_search_fixture(fixture_path)
        assert parse_page(payload)[0].homeoffice is False
        payload["ergebnisliste"][0]["homeofficemoeglich"] = True
        assert parse_page(payload)[0].homeoffice is True

    def test_werkstudent_in_the_title_sets_the_werkstudent_flag(self, fixture_path):
        from jobfinder.sources.ba import parse_page

        payload = load_search_fixture(fixture_path)
        payload["ergebnisliste"][0]["stellenangebotsTitel"] = "Praktikum Umweltschutz (m/w/d)"
        posting = parse_page(payload)[0]
        assert posting.is_werkstudent is False
        assert posting.is_internship is True

    def test_entries_without_a_location_still_parse(self, fixture_path):
        from jobfinder.sources.ba import parse_page

        payload = load_search_fixture(fixture_path)
        del payload["ergebnisliste"][0]["stellenlokationen"]
        posting = parse_page(payload)[0]
        assert posting.city is None and posting.plz is None

    def test_search_results_never_claim_a_description(self, fixture_path):
        from jobfinder.sources.ba import parse_page

        postings = parse_page(load_search_fixture(fixture_path))
        assert all(posting.description is None for posting in postings)


class RecordingClient:
    """Stands in for the PoliteClient: serves scripted payloads, records calls."""

    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.html_responses: list[bytes] = []
        self.calls: list[dict] = []
        self.get_calls: list[dict] = []

    def get_json(self, url, params=None, headers=None):
        self.calls.append({"url": url, "params": dict(params or {}), "headers": headers or {}})
        return self.payloads.pop(0)

    def get(self, url, params=None, headers=None):
        from jobfinder.sources.http import Response

        self.get_calls.append({"url": url, "params": dict(params or {}), "headers": headers or {}})
        return Response(status=200, body=self.html_responses.pop(0), headers={})


class TestSearchPagination:
    def test_search_paginates_until_max_ergebnisse_is_reached(self, fixture_path):
        from jobfinder.sources.ba import BAApi

        page_one = load_search_fixture(fixture_path)
        page_two = json.loads(json.dumps(page_one))
        page_two["maxErgebnisse"] = 10
        client = RecordingClient([page_one, page_two])
        postings = list(BAApi(client).search(spec()))

        assert len(postings) == 10
        assert len(client.calls) == 2
        assert client.calls[0]["params"]["page"] == 1
        assert client.calls[1]["params"]["page"] == 2
        assert client.calls[0]["url"].endswith("/pc/v6/jobs")

    def test_search_stops_when_a_page_comes_back_empty(self, fixture_path):
        from jobfinder.sources.ba import BAApi

        page_one = load_search_fixture(fixture_path)
        page_one["maxErgebnisse"] = 999  # would keep going — the empty page must stop it
        empty = {"ergebnisliste": [], "maxErgebnisse": 999, "page": 2, "size": 50}
        client = RecordingClient([page_one, empty])
        postings = list(BAApi(client).search(spec()))
        assert len(postings) == 5
        assert len(client.calls) == 2

    def test_search_carries_the_api_key_header(self, fixture_path):
        from jobfinder.sources.ba import API_HEADERS, BAApi

        payload = load_search_fixture(fixture_path)
        payload["maxErgebnisse"] = 5  # one page is the whole result set
        client = RecordingClient([payload])
        list(BAApi(client).search(spec()))
        assert client.calls[0]["headers"] == API_HEADERS


# -- details and the external-URL fallback --------------------------------------


class TestFetchDetail:
    def test_detail_fetch_base64_encodes_the_reference_number(self, fixture_path):
        from jobfinder.sources.ba import BAApi, parse_page

        details = json.loads(
            fixture_path("ba", "jobdetails_4913285274.json").read_text(encoding="utf-8")
        )
        posting = parse_page(load_search_fixture(fixture_path))[0]
        client = RecordingClient([details])
        enriched = BAApi(client).fetch_detail(posting)

        url = client.calls[0]["url"]
        assert url.startswith(
            "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobdetails/"
        )
        assert url.endswith("MTExMTktNDkxMzI4NTI3NC1T")  # base64("11119-4913285274-S")

        assert enriched.description is not None
        assert "DEKRA Arbeit GmbH" in enriched.description
        assert enriched.job_id == posting.job_id
        assert enriched.title == posting.title

    def test_detail_headers_carry_the_api_key(self, fixture_path):
        from jobfinder.sources.ba import API_HEADERS, BAApi, parse_page

        details = json.loads(
            fixture_path("ba", "jobdetails_4913285274.json").read_text(encoding="utf-8")
        )
        posting = parse_page(load_search_fixture(fixture_path))[0]
        client = RecordingClient([details])
        BAApi(client).fetch_detail(posting)
        assert client.calls[0]["headers"] == API_HEADERS

    def test_empty_description_triggers_external_url_fallback(self, fixture_path):
        from jobfinder.sources.ba import BAApi, parse_page

        details = json.loads(
            fixture_path("ba", "jobdetails_4913285274.json").read_text(encoding="utf-8")
        )
        details["stellenangebotsBeschreibung"] = ""  # ~1 in 3 ads looks like this
        external_html = fixture_path("ba", "external_compleet_4913285274.html").read_bytes()
        posting = parse_page(load_search_fixture(fixture_path))[0]
        assert posting.apply_url  # the fixture's first ad has an externeURL

        client = RecordingClient([details])
        client.html_responses = [external_html]
        enriched = BAApi(client).fetch_detail(posting)

        # The external page was fetched…
        assert client.get_calls[0]["url"] == "https://jobboard.compleet.com/?externalId=4913285274"
        # …but it is a client-rendered SPA with no static text, so nothing is
        # invented: the posting survives without a description.
        assert enriched.description is None
        assert enriched.has_description is False

    def test_external_fallback_text_becomes_the_description(self, fixture_path):
        from jobfinder.sources.ba import BAApi, parse_page

        details = json.loads(
            fixture_path("ba", "jobdetails_4913285274.json").read_text(encoding="utf-8")
        )
        details["stellenangebotsBeschreibung"] = ""
        static_page = (
            "<html><body><h1>Küchenhilfe (m/w/d)</h1><p>Bäckerei Müller & Söhne sucht "
            "eine Küchenhilfe für Samstag und Sonntag. Wir bieten ein freundliches "
            "Team, Schichtzulagen und kostenlose Getränke während der Arbeit.</p>"
            "</body></html>"
        ).encode()
        posting = parse_page(load_search_fixture(fixture_path))[0]
        client = RecordingClient([details])
        client.html_responses = [static_page]
        enriched = BAApi(client).fetch_detail(posting)

        assert enriched.description is not None
        assert "Bäckerei Müller & Söhne" in enriched.description
        assert enriched.has_description is True

    def test_no_description_and_no_external_url_leaves_the_posting_as_is(self, fixture_path):
        from jobfinder.sources.ba import BAApi, parse_page

        details = json.loads(
            fixture_path("ba", "jobdetails_4913285274.json").read_text(encoding="utf-8")
        )
        details["stellenangebotsBeschreibung"] = ""
        posting = parse_page(load_search_fixture(fixture_path))[0]
        posting = dataclasses.replace(posting, apply_url=None)
        client = RecordingClient([details])
        enriched = BAApi(client).fetch_detail(posting)
        assert enriched.description is None
        assert len(client.calls) == 1  # details only, nothing else fetched
