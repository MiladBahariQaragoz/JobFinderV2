"""Schema v7: the comparable posting date, stored and backfilled.

Her database holds 859 jobs whose `published_at` came in three shapes. The
filter compares one column, so that column has to exist for the rows already
stored as well as the ones arriving — and both have to be filled by the same
function, or "posted this week" means one thing for an old row and another for
a new one.
"""

from __future__ import annotations

import sqlite3

import pytest

from jobfinder.sources.base import RawPosting
from jobfinder.store.db import SCHEMA_VERSION, connect, migrate
from jobfinder.store.jobs import upsert_job


@pytest.fixture
def db(tmp_path):
    connection = connect(tmp_path / "jobfinder.db")
    migrate(connection)
    yield connection
    connection.close()


def store(connection, job_id: str, published_at: str | None):
    upsert_job(
        connection,
        RawPosting(
            job_id=job_id,
            source=job_id.split(":")[0],
            source_id=job_id.split(":")[1],
            title=f"Aushilfe {job_id}",
            company="Bäckerei Musterle",
            city="Ingolstadt",
            published_at=published_at,
        ),
    )


def dates(connection) -> dict[str, str | None]:
    return {
        row["job_id"]: row["published_on"]
        for row in connection.execute("SELECT job_id, published_on FROM jobs")
    }


class TestStoringIt:
    def test_the_column_exists_at_the_current_schema_version(self, db):
        columns = {row[1] for row in db.execute("PRAGMA table_info(jobs)")}

        assert "published_on" in columns
        assert int(db.execute("PRAGMA user_version").fetchone()[0]) == SCHEMA_VERSION

    def test_upsert_stores_the_comparable_date_beside_the_raw_one(self, db):
        store(db, "AZ:1", "2026-06-20T12:20:44Z")

        row = db.execute("SELECT published_at, published_on FROM jobs").fetchone()
        assert row["published_at"] == "2026-06-20T12:20:44Z"  # unchanged
        assert row["published_on"] == "2026-06-20"

    def test_every_shape_her_sources_report_lands_comparable(self, db):
        store(db, "BA:1", "2026-07-01")
        store(db, "AZ:2", "2026-06-20T12:20:44Z")
        store(db, "AN:3", "2026-08-16T02:09:29+00:00")

        assert dates(db) == {
            "BA:1": "2026-07-01",
            "AZ:2": "2026-06-20",
            "AN:3": "2026-08-16",
        }

    def test_a_posting_with_no_date_stores_null_not_an_empty_string(self, db):
        store(db, "BA:1", None)

        assert dates(db) == {"BA:1": None}

    def test_a_re_found_job_keeps_its_comparable_date(self, db):
        store(db, "AZ:1", "2026-06-20T12:20:44Z")

        store(db, "AZ:1", "2026-06-20T12:20:44Z")  # the next search sees it again

        assert dates(db) == {"AZ:1": "2026-06-20"}


class TestBackfillingHerDatabase:
    def _v6_database(self, tmp_path, rows):
        """A database exactly as v6 left it: no `published_on` column at all."""
        path = tmp_path / "old.db"
        old = sqlite3.connect(path)
        old.executescript(
            "CREATE TABLE jobs ("
            " job_id TEXT PRIMARY KEY, source TEXT NOT NULL, source_id TEXT NOT NULL,"
            " dedupe_key TEXT NOT NULL, title TEXT NOT NULL, published_at TEXT,"
            " has_description INTEGER NOT NULL DEFAULT 0,"
            " first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL)"
        )
        old.executemany(
            "INSERT INTO jobs (job_id, source, source_id, dedupe_key, title, published_at,"
            " first_seen_at, last_seen_at) VALUES (?, 'BA', ?, ?, 'Aushilfe', ?, '2026-01-01',"
            " '2026-01-01')",
            [(job_id, job_id, job_id, published_at) for job_id, published_at in rows],
        )
        old.execute("PRAGMA user_version = 6")
        old.commit()
        old.close()
        return path

    def test_migrating_a_v6_database_backfills_every_row(self, tmp_path):
        path = self._v6_database(
            tmp_path,
            [
                ("BA:1", "2026-07-01"),
                ("AZ:2", "2026-06-20T12:20:44Z"),
                ("AN:3", "2026-08-16T02:09:29+00:00"),
                ("BA:4", None),
            ],
        )

        connection = connect(path)
        migrate(connection)
        try:
            assert dates(connection) == {
                "BA:1": "2026-07-01",
                "AZ:2": "2026-06-20",
                "AN:3": "2026-08-16",
                "BA:4": None,
            }
        finally:
            connection.close()

    def test_a_row_whose_date_is_junk_backfills_to_null_not_a_crash(self, tmp_path):
        path = self._v6_database(tmp_path, [("BA:1", "not a date"), ("BA:2", "2026-07-01")])

        connection = connect(path)
        migrate(connection)
        try:
            assert dates(connection) == {"BA:1": None, "BA:2": "2026-07-01"}
        finally:
            connection.close()

    def test_migrating_twice_changes_nothing(self, tmp_path):
        path = self._v6_database(tmp_path, [("AZ:1", "2026-06-20T12:20:44Z")])

        connection = connect(path)
        migrate(connection)
        migrate(connection)
        try:
            assert dates(connection) == {"AZ:1": "2026-06-20"}
        finally:
            connection.close()

    def test_the_backfill_does_not_touch_the_raw_column(self, tmp_path):
        path = self._v6_database(tmp_path, [("AZ:1", "2026-06-20T12:20:44Z")])

        connection = connect(path)
        migrate(connection)
        try:
            raw = connection.execute("SELECT published_at FROM jobs").fetchone()[0]
        finally:
            connection.close()

        assert raw == "2026-06-20T12:20:44Z"
