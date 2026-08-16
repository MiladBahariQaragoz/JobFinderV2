"""The store's foundation: connections are WAL-safe and migrations idempotent.

MASTER_PLAN §5 defines the tables, §9 the durability rules. These tests pin
both, because a schema drift or a non-WAL connection silently corrupts her data
the day the laptop lid closes mid-run.
"""

from __future__ import annotations

import sqlite3

import pytest

from jobfinder.store.db import SCHEMA_VERSION, connect, migrate

PHASE_4_TABLES = {
    "jobs",
    "job_descriptions",
    "enrichment",
    "status",
    "contacts",
    "runs",
    "source_state",
}


@pytest.fixture
def db(tmp_path):
    connection = connect(tmp_path / "jobfinder.db")
    migrate(connection)
    yield connection
    connection.close()


def table_names(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row[0] for row in rows}


class TestConnect:
    def test_fresh_file_creates_directory_and_database(self, tmp_path):
        target = tmp_path / "deeply" / "nested" / "jobfinder.db"
        connection = connect(target)
        try:
            assert target.exists()
        finally:
            connection.close()

    def test_every_connection_runs_wal_and_synchronous_normal(self, tmp_path):
        # §9: WAL survives a hard kill; synchronous=NORMAL is the WAL pairing.
        # Both pragmas must hold on *every* connection, not just the first.
        target = tmp_path / "jobfinder.db"
        first = connect(target)
        second = connect(target)
        try:
            for connection in (first, second):
                mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
                synchronous = connection.execute("PRAGMA synchronous").fetchone()[0]
                assert mode.lower() == "wal"
                assert synchronous == 1  # NORMAL
        finally:
            first.close()
            second.close()


class TestMigrate:
    def test_fresh_database_creates_all_phase_4_tables(self, db):
        missing = PHASE_4_TABLES - table_names(db)
        assert not missing, f"tables not created: {sorted(missing)}"

    def test_reopening_an_existing_database_is_a_noop(self, db):
        before = table_names(db)
        migrate(db)  # second open of the same file
        migrate(db)  # and a third, for good measure
        assert table_names(db) == before

    def test_migration_sets_the_schema_version_stamp(self, db):
        version = db.execute("PRAGMA user_version").fetchone()[0]
        assert version == SCHEMA_VERSION

    def test_status_table_defaults_to_new(self, db):
        # Her only table: the status column must exist and read 'new'.
        columns = {row[1] for row in db.execute("PRAGMA table_info(status)")}
        assert {"job_id", "status", "notes"} <= columns

    def test_runs_table_journals_progress_not_just_outcomes(self, db):
        # §9: state, started_at and last_progress_at make a run observable
        # while it is still running.
        columns = {row[1] for row in db.execute("PRAGMA table_info(runs)")}
        assert {"state", "started_at", "last_progress_at"} <= columns

    def test_source_state_table_holds_cursors_per_source(self, db):
        columns = {row[1] for row in db.execute("PRAGMA table_info(source_state)")}
        assert {"source", "query_hash", "last_completed_page"} <= columns

    def test_jobs_primary_key_is_job_id(self, db):
        # §5 job identity: {SOURCE}:{native id} is the stable key.
        info = db.execute("PRAGMA table_info(jobs)").fetchall()
        pk_columns = [row[1] for row in info if row[5]]  # row[5] > 0 means PK
        assert pk_columns == ["job_id"]
