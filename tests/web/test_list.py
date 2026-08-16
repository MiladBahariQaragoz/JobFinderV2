"""The list page — MASTER_PLAN Phase 8's first promise.

Filters that bite, sorts that mean something, deleted jobs gone from view,
skeleton rows in every response, and an empty state that names the filters
that produced it instead of saying nothing.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from tests.web.conftest import store_job

from jobfinder.store.db import connect
from jobfinder.web.app import create_app


class TestListBasics:
    def test_index_lists_only_non_deleted_jobs(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "Aushilfe Verkauf Minijob" in response.text
        assert "Gelöscht hier" not in response.text  # soft-deleted, invisible

    def test_deleted_job_appears_again_when_she_asks_for_it(self, client):
        response = client.get("/?status=deleted")
        assert "Gelöscht hier" in response.text
        assert "Aushilfe Verkauf Minijob" not in response.text


class TestFilters:
    def test_filter_by_city_returns_only_that_city(self, client):
        response = client.get("/?city=Ingolstadt")
        assert "Aushilfe Verkauf Minijob" in response.text
        assert "Werkstudent Datenanalyse" not in response.text  # München

    def test_filter_by_max_german_level_excludes_c1_when_she_selects_b1(self, client):
        response = client.get("/?max_german=B1")
        body = response.text
        assert "Retail Assistant" in body  # A2 — comfortable
        assert "Aushilfe Verkauf Minijob" in body  # B1 — at her bound
        assert "Werkstudent Datenanalyse" not in body  # C1 — over the bound
        assert "Küchenhilfe" not in body  # unclear cannot promise it fits

    def test_filter_combination_city_and_type_and_fit(self, client):
        response = client.get("/?city=Ingolstadt&type=minijob&min_fit=50")
        body = response.text
        assert "Aushilfe Verkauf Minijob" in body  # all three match
        assert "Küchenhilfe" not in body  # fit 40, under the floor
        assert "Werkstudent Datenanalyse" not in body  # wrong city and type
        assert "Retail Assistant" not in body  # wrong city and type

    def test_filter_by_source(self, client):
        response = client.get("/?source=AN")
        assert "Retail Assistant" in response.text
        assert "Aushilfe Verkauf Minijob" not in response.text


class TestPickingSeveralAtOnce:
    """She lives in one place but can reach several — one city at a time is
    the wrong question. The same goes for the contract types she will take."""

    def test_two_cities_return_the_jobs_in_both(self, client):
        body = client.get("/?city=Ingolstadt&city=M%C3%BCnchen").text
        assert "Aushilfe Verkauf Minijob" in body  # Ingolstadt
        assert "Werkstudent Datenanalyse" in body  # München
        assert "Retail Assistant" in body  # München

    def test_two_types_return_the_jobs_of_either(self, client):
        body = client.get("/?type=minijob&type=werkstudent").text
        assert "Aushilfe Verkauf Minijob" in body  # minijob
        assert "Werkstudent Datenanalyse" in body  # werkstudent
        assert "Retail Assistant" not in body  # part-time only

    def test_two_sources_return_the_jobs_of_either(self, client):
        body = client.get("/?source=AN&source=BA").text
        assert "Retail Assistant" in body  # AN
        assert "Aushilfe Verkauf Minijob" in body  # BA

    def test_picking_several_still_narrows_against_the_other_filters(self, client):
        body = client.get("/?city=Ingolstadt&city=M%C3%BCnchen&type=minijob").text
        assert "Aushilfe Verkauf Minijob" in body
        assert "Küchenhilfe" in body  # Ingolstadt minijob
        assert "Retail Assistant" not in body  # München, but part-time

    def test_the_empty_state_names_every_city_she_picked(self, client):
        body = client.get("/?city=Passau&city=Bayreuth").text
        assert "No jobs match" in body
        assert "Passau" in body
        assert "Bayreuth" in body

    def test_one_value_still_behaves_exactly_as_before(self, client):
        body = client.get("/?city=Ingolstadt").text
        assert "Aushilfe Verkauf Minijob" in body
        assert "Werkstudent Datenanalyse" not in body

    def test_paging_keeps_every_city_she_picked(self, settings, client):
        """The next-page link is built from the query string, and a plain
        dict() over repeated parameters keeps only the last one — which would
        silently drop her other cities at page two."""
        connection = connect(settings.db_path)
        try:
            for n in range(60):  # past one 50-row page
                store_job(connection, job_id=f"BA:2{n}", title=f"Filler {n}", city="München")
        finally:
            connection.close()

        body = client.get("/?city=Ingolstadt&city=M%C3%BCnchen").text
        next_link = body.split('href="/?', 1)[1].split('"', 1)[0]
        assert next_link.count("city=") == 2, f"the next page drops a city: {next_link}"


class TestSearchLivesOnItsOwnPage:
    """Searching and filtering are different questions — one asks the internet
    for more jobs, the other narrows the ones already stored. Side by side on
    one page they read as the same control."""

    def test_the_list_page_does_not_carry_the_search_form(self, client):
        body = client.get("/").text
        assert "Explain jobs in English while searching" not in body
        assert 'action="/run/start"' not in body

    def test_the_search_page_carries_it(self, client):
        response = client.get("/search")
        assert response.status_code == 200
        body = response.text
        assert "Explain jobs in English while searching" in body
        assert 'action="/run/start"' in body

    def test_both_pages_are_reachable_from_every_page(self, client):
        for path in ("/", "/search", "/jobs/BA%3A1"):
            body = client.get(path).text
            assert 'href="/search"' in body, f"no way to reach the search from {path}"
            assert 'href="/"' in body, f"no way back to the jobs from {path}"


class TestSorting:
    def test_sort_by_fit_score_descending(self, client):
        response = client.get("/?sort=fit")
        positions = [
            response.text.find(title)
            for title in ("Retail Assistant", "Werkstudent Datenanalyse", "Aushilfe Verkauf")
        ]
        assert all(position != -1 for position in positions)
        assert positions == sorted(positions)  # 95, 85, 60 in page order

    def test_sort_by_date_puts_the_newest_first(self, settings, client):
        connection = connect(settings.db_path)
        try:
            store_job(connection, job_id="BA:8", title="Ältere Annonce", published_at="2026-08-01")
            store_job(connection, job_id="BA:9", title="Neue Annonce", published_at="2026-08-15")
        finally:
            connection.close()

        body = client.get("/?sort=date").text
        assert body.find("Neue Annonce") < body.find("Ältere Annonce")


class TestStates:
    def test_every_list_page_renders_a_skeleton_state(self, client):
        body = client.get("/").text
        # skeleton rows ship with the page: loading reads as loading (§10),
        # and the placeholders match the real grid, not a spinner.
        assert body.count('class="skeleton-row"') >= 3

    def test_empty_result_page_names_the_filters_that_were_applied(self, client):
        response = client.get("/?city=Passau&max_german=A1")
        assert response.status_code == 200
        body = response.text
        assert "No jobs match" in body
        assert "Passau" in body  # the filters, named in her words
        assert "A1" in body
        # The one thing to try next, however the sentence is capitalised.
        assert "loosen" in body.lower() or "clear" in body.lower()

    def test_the_empty_state_only_names_filters_she_actually_set(self, client):
        """§10 asks for the one filter to loosen — hers, not a menu of them.

        Seen on her real store: filtering by city and type alone still offered
        "loosen the German level", plus the note that unclear ads are hidden
        while a level filter is on. Neither was true of that search."""
        body = client.get("/?city=Passau&type=internship").text
        assert "No jobs match" in body
        assert "German" not in body.split("No jobs match", 1)[1].split("</div>", 1)[0]

    def test_a_store_with_no_jobs_says_how_to_start(self, settings):

        with TestClient(create_app(settings)) as fresh_client:
            body = fresh_client.get("/").text
            assert "No jobs yet" in body
            assert "jobfinder search" in body

    def test_unparseable_filter_values_are_ignored_not_500s(self, client):
        assert client.get("/?min_fit=zehn&max_german=fluent&sort=wild&page=x").status_code == 200
