"""Contract tests for the Arbeitnow adapter — recorded fixture, never hand-made JSON.

The fixture is one real page (175 entries, 2026-08-16): mostly non-Bavarian,
with every messy `job_types` spelling the API actually emits. Where a test
needs a signal the page happens not to carry (a minijob title, say), it copies
a real entry and changes that one field — the pattern the BA tests set.
"""

from __future__ import annotations

import json

from jobfinder.search_spec import SearchSpec

# The real page-1 entry used for field-level assertions.
WERKSTUDENT_SLUG = "werkstudent-strategy-business-development-ai-taskforce-munchen-407715"


def spec(**overrides) -> SearchSpec:
    parts = dict(mode="general", employment_types=["werkstudent"], city_names=["München"])
    parts.update(overrides)
    return SearchSpec.build(**parts)


def load_page(fixture_path) -> dict:
    path = fixture_path("arbeitnow", "job_board_page1.json")
    return json.loads(path.read_text(encoding="utf-8"))


def load_entry(fixture_path, slug: str = WERKSTUDENT_SLUG) -> dict:
    payload = load_page(fixture_path)
    return next(entry for entry in payload["data"] if entry["slug"] == slug)


# -- parsing recorded pages ----------------------------------------------------


class TestParsePage:
    def test_arbeitnow_fixture_parses_into_raw_postings(self, fixture_path):
        from jobfinder.sources.arbeitnow import parse_page

        postings = parse_page(load_page(fixture_path))
        assert len(postings) == 175  # every entry on the page has a slug
        assert all(posting.source == "AN" for posting in postings)

    def test_entry_maps_onto_expected_fields(self, fixture_path):
        from jobfinder.sources.arbeitnow import parse_page

        posting = next(
            p for p in parse_page(load_page(fixture_path)) if p.source_id == WERKSTUDENT_SLUG
        )
        assert posting.job_id == f"AN:{WERKSTUDENT_SLUG}"
        assert posting.title == "Werkstudent (m/w/d) Strategy & Business Development (AI-Taskforce)"
        assert posting.company == "Yoummday GmbH"
        assert posting.city == "München"
        assert posting.employment_type_raw == "Entry, Intern, Part time"
        assert posting.source_url == (
            "https://www.arbeitnow.com/jobs/companies/yoummday-gmbh/"
            "werkstudent-strategy-business-development-ai-taskforce-munchen-407715"
        )
        assert posting.is_werkstudent is True  # from the title, not job_types
        assert posting.is_parttime is True  # from job_types "Part time"
        assert posting.is_fulltime is False
        assert posting.is_internship is True  # job_types carries "Intern"
        assert posting.homeoffice is False  # the entry's `remote` is False

    def test_html_description_is_reduced_to_readable_text(self, fixture_path):
        from jobfinder.sources.arbeitnow import parse_page

        posting = next(
            p for p in parse_page(load_page(fixture_path)) if p.source_id == WERKSTUDENT_SLUG
        )
        assert posting.description
        assert "<" not in posting.description  # tags stripped, entities decoded
        assert "Deine Mission" in posting.description

    def test_epoch_created_at_becomes_iso_published_at(self, fixture_path):
        from jobfinder.sources.arbeitnow import parse_page

        posting = next(
            p for p in parse_page(load_page(fixture_path)) if p.source_id == WERKSTUDENT_SLUG
        )
        assert posting.published_at == "2026-08-16T02:09:29+00:00"

    def test_remote_maps_to_homeoffice(self, fixture_path):
        from jobfinder.sources.arbeitnow import parse_page

        payload = load_page(fixture_path)
        remote_slug = next(e["slug"] for e in payload["data"] if e.get("remote"))
        payload["data"] = [e for e in payload["data"] if e["slug"] == remote_slug]
        assert parse_page(payload)[0].homeoffice is True

    def test_entries_without_a_slug_are_skipped(self, fixture_path):
        from jobfinder.sources.arbeitnow import parse_page

        payload = load_page(fixture_path)
        del payload["data"][0]["slug"]
        assert len(parse_page(payload)) == 174

    def test_minijob_wording_in_the_title_sets_the_flag(self, fixture_path):
        from jobfinder.sources.arbeitnow import parse_page

        payload = load_page(fixture_path)
        payload["data"][0]["title"] = "Aushilfe Verkauf Minijob (m/w/d)"
        assert parse_page(payload)[0].is_minijob is True


# -- client-side filters: city, type, keyword ----------------------------------


class TestCityFilter:
    def test_arbeitnow_results_outside_her_cities_are_filtered_out(self, fixture_path):
        from jobfinder.sources.arbeitnow import postings_for_spec

        postings = postings_for_spec(
            load_page(fixture_path),
            spec(employment_types=["werkstudent", "parttime", "fulltime"]),
        )
        assert postings  # München really is on the page
        assert all(posting.city == "München" for posting in postings)
        assert len(postings) == 8  # every München entry on the page, nothing else

    def test_location_matching_is_exact_on_the_canonical_name(self, fixture_path):
        # "Munich Office" is an office label, not the city — dropped on purpose.
        # A fuzzy match would also let "London" style noise through.
        from jobfinder.sources.arbeitnow import postings_for_spec

        postings = postings_for_spec(
            load_page(fixture_path),
            spec(employment_types=["werkstudent", "parttime", "fulltime"]),
        )
        assert all("Office" not in (posting.city or "") for posting in postings)


class TestTypeFilter:
    def test_working_student_job_type_passes_a_werkstudent_spec(self, fixture_path):
        from jobfinder.sources.arbeitnow import postings_for_spec

        payload = load_page(fixture_path)
        payload["data"] = [
            {
                **payload["data"][0],
                "title": "Junior Analyst (m/w/d)",  # no type wording in the title
                "location": "München",
                "job_types": ["Working Student"],  # the signal under test
            }
        ]
        assert postings_for_spec(payload, spec(employment_types=["werkstudent"]))

    def test_full_time_only_jobs_do_not_pass_a_werkstudent_and_parttime_spec(self, fixture_path):
        from jobfinder.sources.arbeitnow import postings_for_spec

        postings = postings_for_spec(
            load_page(fixture_path),
            spec(employment_types=["werkstudent", "parttime"]),
        )
        titles = {posting.title for posting in postings}
        assert "Platform & DevOps Engineer (m/w/d)" not in titles  # Full time only
        assert len(postings) == 5  # 4 Werkstudent titles + 1 "Full or part time"

    def test_title_wording_counts_as_a_type_signal(self, fixture_path):
        # The real entry's job_types say Entry/Intern/Part time — no
        # "working student" — yet the title says Werkstudent, and that is the
        # word a German employer actually uses.
        from jobfinder.sources.arbeitnow import postings_for_spec

        payload = load_page(fixture_path)
        payload["data"] = [e for e in payload["data"] if e["slug"] == WERKSTUDENT_SLUG]
        assert postings_for_spec(payload, spec(employment_types=["werkstudent"]))

    def test_empty_job_types_with_no_title_hint_is_excluded(self, fixture_path):
        from jobfinder.sources.arbeitnow import postings_for_spec

        payload = load_page(fixture_path)
        payload["data"] = [
            {
                **payload["data"][0],
                "title": "Regional Sales Manager",
                "location": "München",
                "job_types": [],
            }
        ]
        assert postings_for_spec(payload, spec(employment_types=["werkstudent"])) == []

    def test_minijob_wording_passes_a_minijob_spec(self, fixture_path):
        from jobfinder.sources.arbeitnow import postings_for_spec

        payload = load_page(fixture_path)
        payload["data"] = [
            {
                **payload["data"][0],
                "title": "Reinigungskraft Minijob",
                "location": "München",
                "job_types": [],
            }
        ]
        assert postings_for_spec(payload, spec(employment_types=["minijob"]))


class TestKeywordFilter:
    def test_keywords_match_title_and_tags(self, fixture_path):
        from jobfinder.sources.arbeitnow import postings_for_spec

        payload = load_page(fixture_path)
        payload["data"] = [e for e in payload["data"] if e["slug"] == WERKSTUDENT_SLUG]
        # "Consulting" is one of the entry's tags, not its title.
        assert postings_for_spec(payload, spec(keywords=["consulting"]))
        # And the title surface works too.
        assert postings_for_spec(payload, spec(keywords=["strategy"]))
        assert postings_for_spec(payload, spec(keywords=["bäckerei"])) == []


# -- pagination over the polite client -----------------------------------------


class RecordingClient:
    """Stands in for the PoliteClient: serves scripted payloads, records calls."""

    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls: list[dict] = []

    def get_json(self, url, params=None, headers=None):
        self.calls.append({"url": url, "params": dict(params or {})})
        return self.payloads.pop(0)


def page_payload(entries, *, next_url: str | None) -> dict:
    return {
        "data": entries,
        "links": {"next": next_url, "last": None},
        "meta": {"current_page": 1, "per_page": 175},
    }


class TestPagination:
    def api(self, payloads):
        from jobfinder.sources.arbeitnow import ArbeitnowApi

        client = RecordingClient(payloads)
        return ArbeitnowApi(client), client

    def test_pagination_stops_at_the_last_page(self, fixture_path):
        entry = load_entry(fixture_path)
        api, client = self.api(
            [
                page_payload([entry], next_url="...?page=2"),
                page_payload([entry], next_url=None),  # links.next null — the end
            ]
        )
        pages = list(api.search_pages(spec()))
        assert [page.page for page in pages] == [1, 2]
        assert len(client.calls) == 2
        assert client.calls[1]["params"] == {"page": 2}

    def test_an_empty_page_ends_the_walk_without_being_served(self):
        api, client = self.api([page_payload([], next_url="...?page=2")])
        assert list(api.search_pages(spec())) == []
        assert len(client.calls) == 1

    def test_pages_are_capped_at_max_pages(self, fixture_path):
        from jobfinder.sources.arbeitnow import MAX_PAGES

        entry = load_entry(fixture_path)
        api, client = self.api(
            [page_payload([entry], next_url="...?page=2") for _ in range(MAX_PAGES + 5)]
        )
        pages = list(api.search_pages(spec()))
        assert len(pages) == MAX_PAGES
        assert len(client.calls) == MAX_PAGES

    def test_resume_reenters_at_the_stored_page(self, fixture_path):
        entry = load_entry(fixture_path)
        api, client = self.api([page_payload([entry], next_url=None)])
        pages = list(api.search_pages(spec(), start_query_index=0, start_page=3))
        assert client.calls[0]["params"] == {"page": 3}
        assert pages[0].page == 3

    def test_a_resume_cursor_past_the_only_query_yields_nothing(self, fixture_path):
        entry = load_entry(fixture_path)
        api, client = self.api([page_payload([entry], next_url=None)])
        assert list(api.search_pages(spec(), start_query_index=1)) == []
        assert client.calls == []  # the walk was already finished

    def test_fetch_detail_makes_no_request(self, fixture_path):
        from jobfinder.sources.arbeitnow import parse_page

        entry = load_entry(fixture_path)
        api, client = self.api([])
        posting = parse_page(page_payload([entry], next_url=None))[0]
        assert api.fetch_detail(posting) is posting  # the listing already has it all
        assert client.calls == []
