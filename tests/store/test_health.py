"""Per-source health: three strikes and a source sits out (§8 rule 7).

A scraper that has started refusing us does not get asked again every run
until someone notices. It gets counted, and after three consecutive failures
it is put in cooldown with a reason her summary can print. One good page
clears the count — a site that recovered should not stay punished.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from jobfinder.store.db import connect, migrate
from jobfinder.store.health import (
    COOLDOWN,
    FAILURES_BEFORE_COOLDOWN,
    cooling_off,
    record_failure,
    record_success,
)

NOW = datetime(2026, 8, 16, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def db(tmp_path):
    connection = connect(tmp_path / "jobfinder.db")
    migrate(connection)
    yield connection
    connection.close()


class TestCounting:
    def test_a_failure_is_counted_against_its_own_source(self, db):
        record_failure(db, "SS", reason="timed out", now=NOW)
        record_failure(db, "SS", reason="timed out", now=NOW)
        record_failure(db, "KA", reason="timed out", now=NOW)

        assert (
            db.execute(
                "SELECT consecutive_failures FROM source_state WHERE source = 'SS'"
            ).fetchone()[0]
            == 2
        )
        assert (
            db.execute(
                "SELECT consecutive_failures FROM source_state WHERE source = 'KA'"
            ).fetchone()[0]
            == 1
        )

    def test_a_success_resets_the_count(self, db):
        record_failure(db, "SS", reason="timed out", now=NOW)
        record_failure(db, "SS", reason="timed out", now=NOW)
        record_success(db, "SS", now=NOW)

        assert (
            db.execute(
                "SELECT consecutive_failures FROM source_state WHERE source = 'SS'"
            ).fetchone()[0]
            == 0
        )

    def test_a_success_lifts_a_cooldown_too(self, db):
        for _ in range(FAILURES_BEFORE_COOLDOWN):
            record_failure(db, "SS", reason="timed out", now=NOW)
        record_success(db, "SS", now=NOW)

        assert cooling_off(db, "SS", now=NOW) is None


class TestCooldown:
    def test_three_consecutive_failures_disable_the_source(self, db):
        for _ in range(FAILURES_BEFORE_COOLDOWN):
            record_failure(db, "SS", reason="www.stepstone.de kept refusing requests", now=NOW)

        reason = cooling_off(db, "SS", now=NOW)
        assert reason is not None
        assert "3" in reason  # how many times it failed
        assert "refusing" in reason  # and what it said the last time

    def test_two_failures_are_not_enough(self, db):
        record_failure(db, "SS", reason="timed out", now=NOW)
        record_failure(db, "SS", reason="timed out", now=NOW)
        assert cooling_off(db, "SS", now=NOW) is None

    def test_the_cooldown_lets_go_once_it_expires(self, db):
        for _ in range(FAILURES_BEFORE_COOLDOWN):
            record_failure(db, "SS", reason="timed out", now=NOW)

        assert cooling_off(db, "SS", now=NOW + COOLDOWN - timedelta(minutes=1)) is not None
        assert cooling_off(db, "SS", now=NOW + COOLDOWN + timedelta(minutes=1)) is None

    def test_a_source_nobody_has_had_trouble_with_is_not_cooling_off(self, db):
        assert cooling_off(db, "BA", now=NOW) is None
