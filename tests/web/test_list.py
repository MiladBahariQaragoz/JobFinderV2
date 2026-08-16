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
        assert "loosen" in body or "clear" in body  # the one thing to try next

    def test_a_store_with_no_jobs_says_how_to_start(self, settings):

        with TestClient(create_app(settings)) as fresh_client:
            body = fresh_client.get("/").text
            assert "No jobs yet" in body
            assert "jobfinder search" in body

    def test_unparseable_filter_values_are_ignored_not_500s(self, client):
        assert client.get("/?min_fit=zehn&max_german=fluent&sort=wild&page=x").status_code == 200
