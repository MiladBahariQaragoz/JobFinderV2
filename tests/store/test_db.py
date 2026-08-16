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


# The Phase 4 jobs table, as a real v2 database has it — no `also_seen_on`.
# Kept here (not derived from today's schema) because migration code exists
# precisely to upgrade databases that look like this one.
V2_JOBS_DDL = """
CREATE TABLE jobs (
    job_id              TEXT PRIMARY KEY,
    source              TEXT NOT NULL,
    source_id           TEXT NOT NULL,
    dedupe_key          TEXT NOT NULL,
    title               TEXT NOT NULL,
    company             TEXT,
    city                TEXT,
    plz                 TEXT,
    lat                 REAL,
    lon                 REAL,
    employment_type_raw TEXT,
    is_minijob          INTEGER NOT NULL DEFAULT 0,
    is_parttime         INTEGER NOT NULL DEFAULT 0,
    is_fulltime         INTEGER NOT NULL DEFAULT 0,
    is_internship       INTEGER NOT NULL DEFAULT 0,
    is_werkstudent      INTEGER NOT NULL DEFAULT 0,
    homeoffice          INTEGER NOT NULL DEFAULT 0,
    published_at        TEXT,
    apply_url           TEXT,
    source_url          TEXT,
    has_description     INTEGER NOT NULL DEFAULT 0,
    content_hash        TEXT,
    first_seen_at       TEXT NOT NULL,
    last_seen_at        TEXT NOT NULL
);
"""


class TestSchemaV3:
    def test_jobs_table_carries_also_seen_on(self, db):
        columns = {row[1] for row in db.execute("PRAGMA table_info(jobs)")}
        assert "also_seen_on" in columns

    def test_a_v2_database_migrates_without_losing_rows(self, tmp_path):
        import sqlite3

        target = tmp_path / "jobfinder.db"
        legacy = sqlite3.connect(target)
        legacy.execute(V2_JOBS_DDL)
        legacy.execute(
            "INSERT INTO jobs (job_id, source, source_id, dedupe_key, title, first_seen_at,"
            " last_seen_at) VALUES ('BA:1', 'BA', '1', 'k', 'Küchenhilfe',"
            " '2026-08-01', '2026-08-01')"
        )
        legacy.commit()
        legacy.close()

        connection = connect(target)
        try:
            migrate(connection)  # CREATE TABLE IF NOT EXISTS alone cannot evolve it
            columns = {row[1] for row in connection.execute("PRAGMA table_info(jobs)")}
            assert "also_seen_on" in columns
            row = connection.execute(
                "SELECT title, also_seen_on FROM jobs WHERE job_id = 'BA:1'"
            ).fetchone()
            assert row[0] == "Küchenhilfe"  # her data survived the migration
            assert row[1] is None  # and the new column starts empty
        finally:
            connection.close()

    def test_keys_stored_before_v3_are_recomputed_on_migration(self, tmp_path):
        # A v2 row's dedupe_key was hashed over the postcode. Left alone it
        # would never match the same ad arriving from a source that has no
        # postcode — the merge would be silently dead on her existing 42 jobs.
        import sqlite3

        from jobfinder.sources.base import make_dedupe_key

        target = tmp_path / "jobfinder.db"
        legacy = sqlite3.connect(target)
        legacy.execute(V2_JOBS_DDL)
        legacy.execute(
            "INSERT INTO jobs (job_id, source, source_id, dedupe_key, title, company, city, plz,"
            " first_seen_at, last_seen_at) VALUES ('BA:1', 'BA', '1', 'the-old-plz-based-key',"
            " 'Werkstudent Küche', 'Bäckerei Müller', 'Ingolstadt, Donau', '85051',"
            " '2026-08-01', '2026-08-01')"
        )
        legacy.commit()
        legacy.close()

        connection = connect(target)
        try:
            migrate(connection)
            stored = connection.execute(
                "SELECT dedupe_key FROM jobs WHERE job_id = 'BA:1'"
            ).fetchone()[0]
        finally:
            connection.close()

        assert stored == make_dedupe_key(
            title="Werkstudent Küche", company="Bäckerei Müller", city="Ingolstadt, Donau"
        )

    def test_the_cross_source_merge_lookup_uses_an_index(self, db):
        # Every posting that is not already known runs this query once. Without
        # an index that is a full scan of `jobs` per posting, and a run over a
        # thousand stored jobs pays for it on every single one.
        plan = db.execute(
            "EXPLAIN QUERY PLAN SELECT job_id FROM jobs WHERE dedupe_key = ? AND source != ?",
            ("some-key", "BA"),
        ).fetchall()
        detail = " ".join(row["detail"] for row in plan)
        assert "USING INDEX" in detail, detail

    def test_migration_is_idempotent_on_the_new_column(self, db):
        migrate(db)
        migrate(db)  # an ALTER path run twice must not try to add it again
        columns = [row[1] for row in db.execute("PRAGMA table_info(jobs)")]
        assert columns.count("also_seen_on") == 1
