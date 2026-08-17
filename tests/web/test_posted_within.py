"""The posting-date filter: "posted within a week", not "sorted by date".

She could already see how old an ad was on its page and sort the list by date,
but not ask the list to leave the old ones out — and an application to a dead
ad is a wasted afternoon. Her store starts in **2022**, so this is not a corner
case.

This is a different question from the 14-day greying, which says whether her
searches still *see* the ad listed, not when it was written.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from tests.web.conftest import store_job

from jobfinder.config import Settings
from jobfinder.store.db import connect, migrate
from jobfinder.web.app import create_app
from jobfinder.web.queries import JobFilters, list_jobs, parse_filters


def days_ago(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).date().isoformat()


def zulu_days_ago(days: int) -> str:
    """What Adzuna stores — a full timestamp, which is the shape a string
    comparison gets wrong."""
    return (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def dated(tmp_path) -> Settings:
    """One job per age, in both stored shapes."""
    settings = Settings(project_root=tmp_path)
    connection = connect(settings.db_path)
    try:
        migrate(connection)
        store_job(connection, job_id="BA:today", title="Heute", published_at=days_ago(0))
        store_job(connection, job_id="AZ:today", title="Heute ISO", published_at=zulu_days_ago(0))
        store_job(connection, job_id="BA:2days", title="Vorgestern", published_at=days_ago(2))
        store_job(connection, job_id="BA:5days", title="Letzte Woche", published_at=days_ago(5))
        store_job(connection, job_id="BA:20days", title="Letzter Monat", published_at=days_ago(20))
        store_job(connection, job_id="BA:400days", title="Vorjahr", published_at=days_ago(400))
        store_job(connection, job_id="BA:undated", title="Ohne Datum", published_at=None)
    finally:
        connection.close()
    return settings


def ids_within(settings: Settings, days: int | None) -> set[str]:
    connection = connect(settings.db_path)
    try:
        jobs, _total = list_jobs(connection, JobFilters(posted_within_days=days))
    finally:
        connection.close()
    return {job["job_id"] for job in jobs}


class TestTheBound:
    def test_posted_within_three_days_excludes_an_older_ad(self, dated):
        assert ids_within(dated, 3) == {"BA:today", "AZ:today", "BA:2days"}

    def test_posted_within_a_week_takes_everything_up_to_it(self, dated):
        assert ids_within(dated, 7) == {"BA:today", "AZ:today", "BA:2days", "BA:5days"}

    def test_posted_within_a_month_reaches_further_back(self, dated):
        assert "BA:20days" in ids_within(dated, 30)
        assert "BA:400days" not in ids_within(dated, 30)

    def test_an_iso_timestamp_from_today_is_included(self, dated):
        """The bug a string comparison would have shipped: today's Adzuna row
        stores `2026-08-17T09:12:00Z`, and `'2026-08-17' < that` is true, so a
        naive comparison drops the ad posted this morning."""
        assert "AZ:today" in ids_within(dated, 3)

    def test_no_bound_is_no_filter_at_all(self, dated):
        assert len(ids_within(dated, None)) == 7

    def test_a_job_with_no_date_is_excluded_when_a_bound_is_set(self, dated):
        """A bound she set is a promise. An ad with no date cannot keep it, so
        it is left out — the same rule the German-level bound already follows."""
        assert "BA:undated" not in ids_within(dated, 30)
        assert "BA:undated" in ids_within(dated, None)


class TestParsingIt:
    @pytest.mark.parametrize("raw,expected", [("3", 3), ("7", 7), ("30", 30)])
    def test_an_offered_bound_is_taken(self, raw, expected):
        assert parse_filters({"posted_within": raw}).posted_within_days == expected

    @pytest.mark.parametrize("raw", ["any", "", "0", "-5", "banana", "9999"])
    def test_anything_else_means_no_bound(self, raw):
        assert parse_filters({"posted_within": raw}).posted_within_days is None

    def test_a_missing_parameter_means_no_bound(self):
        assert parse_filters({}).posted_within_days is None


class TestOnThePage:
    @pytest.fixture
    def client(self, dated) -> TestClient:
        with TestClient(create_app(dated)) as test_client:
            yield test_client

    def test_the_list_narrows_to_the_bound(self, client):
        body = client.get("/?posted_within=3").text

        assert "Heute" in body
        assert "Vorjahr" not in body

    def test_the_filter_form_offers_the_four_choices(self, client):
        body = client.get("/").text

        assert 'name="posted_within"' in body
        for label in ("Any time", "Last 3 days", "Last week", "Last month"):
            assert label in body

    def test_the_bound_is_named_in_the_active_filters_line(self, client):
        body = client.get("/?posted_within=7&city=Nowhere").text

        assert "posted in the last week" in body

    def test_the_bound_survives_paging(self, dated):
        """Page two of a filtered list is still filtered, or the second screen
        quietly shows her the old ads she just asked to hide."""
        connection = connect(dated.db_path)
        try:
            for index in range(60):  # past PAGE_SIZE, all recent
                store_job(
                    connection,
                    job_id=f"BA:bulk{index}",
                    title=f"Aushilfe {index}",
                    published_at=days_ago(1),
                )
        finally:
            connection.close()

        with TestClient(create_app(dated)) as client:
            first = client.get("/?posted_within=3").text
            assert 'href="/?posted_within=3&amp;page=2"' in first

            second = client.get("/?posted_within=3&page=2").text

        assert "Vorjahr" not in second  # the 400-day-old ad stays out on page two

    def test_the_empty_state_offers_to_widen_the_date_bound(self, client):
        """§10: an empty list says what was asked and what to loosen. A date
        bound is the most likely thing to have emptied it, so it is named."""
        body = client.get("/?posted_within=3&city=Nowhere").text

        assert "No jobs match" in body
        assert "posted in the last 3 days" in body
        assert "Ask for older postings" in body

    def test_the_empty_state_says_undated_ads_are_hidden_by_the_bound(self, client):
        body = client.get("/?posted_within=3&city=Nowhere").text

        assert "does not say when it was posted" in body

    def test_a_stale_bound_in_a_link_still_renders_a_list(self, client):
        response = client.get("/?posted_within=fortnight")

        assert response.status_code == 200
        assert "Vorjahr" in response.text  # dropped, so nothing is filtered out

    def test_the_chosen_bound_comes_back_selected(self, client):
        body = client.get("/?posted_within=7").text

        assert '<option value="7" selected' in body
