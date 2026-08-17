"""Storing one answer, and knowing which jobs still need one.

The skip rule is the whole point: her free-tier quota is the scarce resource,
so a job already explained at this prompt version, whose ad has not changed
since, must never be sent again. §5's other half is that a re-enrichment
appends — the answer she read yesterday is still there tomorrow.
"""

from __future__ import annotations

import json

import pytest

from jobfinder.sources.base import RawPosting
from jobfinder.store.db import connect, migrate
from jobfinder.store.enrichment import (
    already_enriched_count,
    jobs_needing_enrichment,
    pending_enrichment_count,
    save_enrichment,
    stored_enrichments,
)
from jobfinder.store.jobs import upsert_job

ANSWER = {
    "german_level": "B1",
    "german_evidence": "Gute Deutschkenntnisse",
    "summary_en": "A weekend job at a bakery counter.",
    "fit_score": 62,
}


@pytest.fixture
def db(tmp_path):
    connection = connect(tmp_path / "jobfinder.db")
    migrate(connection)
    yield connection
    connection.close()


def store_job(connection, job_id="BA:1", *, description="Wir suchen eine Aushilfe.", **overrides):
    values = dict(
        job_id=job_id,
        source="BA",
        source_id=job_id,
        title="Aushilfe Bäckerei (m/w/d)",
        company="Bäckerei Musterle",
        city="Ingolstadt",
        description=description,
    )
    values.update(overrides)
    upsert_job(connection, RawPosting(**values))
    return connection.execute(
        "SELECT content_hash FROM jobs WHERE job_id = ?", (job_id,)
    ).fetchone()[0]


def ids_needing(connection, prompt_version="v1", **kwargs):
    return [job["job_id"] for job in jobs_needing_enrichment(connection, prompt_version, **kwargs)]


class TestSchema:
    def test_the_enrichment_table_carries_the_content_hash_it_was_answered_from(self, db):
        columns = {row[1] for row in db.execute("PRAGMA table_info(enrichment)")}

        assert columns == {
            "job_id",
            "prompt_version",
            "answer",
            "enriched_at",
            "content_hash",
            "provider_used",
        }

    def test_a_database_created_before_v5_gains_the_column_on_migrate(self, tmp_path):
        # The ALTER path: `CREATE TABLE IF NOT EXISTS` cannot evolve a live table,
        # and her database already holds 674 jobs.
        old = connect(tmp_path / "old.db")
        old.executescript(
            "CREATE TABLE enrichment ("
            " job_id TEXT NOT NULL, prompt_version TEXT NOT NULL, answer TEXT NOT NULL,"
            " enriched_at TEXT NOT NULL DEFAULT (datetime('now')),"
            " PRIMARY KEY (job_id, prompt_version))"
        )
        old.commit()

        migrate(old)
        columns = {row[1] for row in old.execute("PRAGMA table_info(enrichment)")}
        old.close()

        assert {"content_hash", "provider_used"} <= columns


class TestSaveEnrichment:
    def test_an_answer_is_stored_as_json_under_its_job_and_prompt_version(self, db):
        content_hash = store_job(db)

        save_enrichment(db, "BA:1", "v1", content_hash, ANSWER)

        row = db.execute("SELECT * FROM enrichment WHERE job_id = 'BA:1'").fetchone()
        assert json.loads(row["answer"]) == ANSWER
        assert row["prompt_version"] == "v1"
        assert row["content_hash"] == content_hash

    def test_an_answer_survives_umlauts_and_the_evidence_it_quotes(self, db):
        content_hash = store_job(db)
        answer = dict(ANSWER, german_evidence="Sehr gute Deutschkenntnisse für Kundengespräche")

        save_enrichment(db, "BA:1", "v1", content_hash, answer)

        stored = stored_enrichments(db, "v1")[0]
        assert stored.answer["german_evidence"] == "Sehr gute Deutschkenntnisse für Kundengespräche"

    def test_the_provider_that_answered_is_kept_beside_its_answer(self, db):
        content_hash = store_job(db)

        save_enrichment(db, "BA:1", "v1", content_hash, ANSWER, provider_used="groq")

        assert stored_enrichments(db, "v1")[0].provider_used == "groq"

    def test_an_unattributed_answer_stores_an_empty_provider_not_null(self, db):
        # llmpool does not report which provider answered a given call, so the
        # runner often cannot say. Empty is the honest value; NULL would reach
        # her CSV as the word "None".
        content_hash = store_job(db)

        save_enrichment(db, "BA:1", "v1", content_hash, ANSWER)

        assert stored_enrichments(db, "v1")[0].provider_used == ""

    def test_saving_commits_so_a_kill_the_next_instant_keeps_the_answer(self, db, tmp_path):
        content_hash = store_job(db)
        save_enrichment(db, "BA:1", "v1", content_hash, ANSWER)

        other = connect(tmp_path / "jobfinder.db")  # a second connection sees committed rows only
        count = other.execute("SELECT COUNT(*) FROM enrichment").fetchone()[0]
        other.close()

        assert count == 1

    def test_re_enriching_at_the_same_version_replaces_that_row(self, db):
        content_hash = store_job(db)
        save_enrichment(db, "BA:1", "v1", content_hash, ANSWER)

        save_enrichment(db, "BA:1", "v1", content_hash, dict(ANSWER, fit_score=90))

        rows = db.execute("SELECT answer FROM enrichment WHERE prompt_version = 'v1'").fetchall()
        assert len(rows) == 1
        assert json.loads(rows[0][0])["fit_score"] == 90


class TestWhatStillNeedsEnriching:
    def test_a_job_with_a_description_and_no_answer_is_sent(self, db):
        store_job(db)

        assert ids_needing(db) == ["BA:1"]

    def test_the_ad_text_comes_with_the_job_so_the_prompt_can_be_built(self, db):
        store_job(db, description="Wir suchen eine Aushilfe für die Theke.")

        job = jobs_needing_enrichment(db, "v1")[0]

        assert job["description"] == "Wir suchen eine Aushilfe für die Theke."
        assert job["title"] == "Aushilfe Bäckerei (m/w/d)"

    def test_already_enriched_job_is_not_sent_again(self, db):
        content_hash = store_job(db)
        save_enrichment(db, "BA:1", "v1", content_hash, ANSWER)

        assert ids_needing(db) == []

    def test_a_job_with_no_description_is_never_sent(self, db):
        store_job(db, job_id="BA:2", description=None)

        assert ids_needing(db) == []

    def test_changed_description_triggers_re_enrichment(self, db):
        content_hash = store_job(db)
        save_enrichment(db, "BA:1", "v1", content_hash, ANSWER)
        db.execute("UPDATE jobs SET content_hash = 'rewritten' WHERE job_id = 'BA:1'")
        db.commit()

        assert ids_needing(db) == ["BA:1"]

    def test_new_prompt_version_triggers_re_enrichment_and_keeps_the_old_row(self, db):
        content_hash = store_job(db)
        save_enrichment(db, "BA:1", "v1", content_hash, ANSWER)

        assert ids_needing(db, "v2") == ["BA:1"]

        save_enrichment(db, "BA:1", "v2", content_hash, dict(ANSWER, fit_score=71))
        versions = db.execute(
            "SELECT prompt_version FROM enrichment WHERE job_id = 'BA:1' ORDER BY prompt_version"
        ).fetchall()

        assert [row[0] for row in versions] == ["v1", "v2"]

    def test_a_limit_bounds_how_many_come_back(self, db):
        for index in range(5):
            store_job(db, job_id=f"BA:{index}", title=f"Aushilfe {index}")

        assert len(ids_needing(db, limit=2)) == 2

    def test_force_sends_even_a_job_already_enriched_at_this_version(self, db):
        content_hash = store_job(db)
        save_enrichment(db, "BA:1", "v1", content_hash, ANSWER)

        assert ids_needing(db, force=True) == ["BA:1"]

    def test_the_oldest_seen_jobs_are_offered_first(self, db):
        store_job(db, job_id="BA:new", title="Aushilfe neu")
        store_job(db, job_id="BA:old", title="Aushilfe alt")
        db.execute("UPDATE jobs SET first_seen_at = '2026-01-01 00:00:00' WHERE job_id = 'BA:old'")
        db.commit()

        assert ids_needing(db)[0] == "BA:old"


class TestCounts:
    def test_the_count_is_what_the_progress_line_reads_from(self, db):
        content_hash = store_job(db)
        store_job(db, job_id="BA:2", title="Aushilfe zwei")
        save_enrichment(db, "BA:1", "v1", content_hash, ANSWER)

        assert already_enriched_count(db, "v1") == 1

    def test_stored_answers_come_back_job_by_job_for_the_export(self, db):
        content_hash = store_job(db)
        save_enrichment(db, "BA:1", "v1", content_hash, ANSWER, now="2026-08-16 09:30:00")

        stored = stored_enrichments(db, "v1")

        assert [row.job_id for row in stored] == ["BA:1"]
        assert stored[0].answer["summary_en"] == "A weekend job at a bakery counter."
        assert stored[0].enriched_at == "2026-08-16 09:30:00"

    def test_the_export_reads_one_version_and_ignores_the_others(self, db):
        content_hash = store_job(db)
        save_enrichment(db, "BA:1", "v1", content_hash, ANSWER)
        save_enrichment(db, "BA:1", "v2", content_hash, dict(ANSWER, fit_score=90))

        assert [row.answer["fit_score"] for row in stored_enrichments(db, "v2")] == [90]

    def test_an_unparsable_stored_answer_is_skipped_rather_than_crashing_the_export(self, db):
        content_hash = store_job(db)
        store_job(db, job_id="BA:2", title="Aushilfe zwei")
        save_enrichment(db, "BA:2", "v1", content_hash, ANSWER)
        db.execute(
            "INSERT INTO enrichment (job_id, prompt_version, answer) VALUES (?, ?, ?)",
            ("BA:1", "v1", "not json"),
        )
        db.commit()

        assert [row.job_id for row in stored_enrichments(db, "v1")] == ["BA:2"]


class TestPendingCount:
    """What an Enrich button has to say before it spends anything.

    The web app polls this once a second while a pass runs, so it must be a
    count in SQL — fetching 839 rows to call `len()` on them is the shape this
    replaces.
    """

    def test_pending_enrichment_count_counts_only_jobs_with_an_ad_text(self, db):
        store_job(db)
        store_job(db, job_id="BA:2", title="Aushilfe zwei", description="")

        assert pending_enrichment_count(db, "v1") == 1

    def test_pending_enrichment_count_ignores_jobs_already_answered_at_this_version(self, db):
        content_hash = store_job(db)
        store_job(db, job_id="BA:2", title="Aushilfe zwei")
        save_enrichment(db, "BA:1", "v1", content_hash, ANSWER)

        assert pending_enrichment_count(db, "v1") == 1
        assert pending_enrichment_count(db, "v2") == 2

    def test_pending_enrichment_count_is_zero_on_an_empty_store(self, db):
        assert pending_enrichment_count(db, "v1") == 0

    def test_pending_enrichment_count_agrees_with_the_queue_it_summarises(self, db):
        content_hash = store_job(db)
        store_job(db, job_id="BA:2", title="Aushilfe zwei")
        store_job(db, job_id="BA:3", title="Aushilfe drei", description="")
        save_enrichment(db, "BA:1", "v1", content_hash, ANSWER)

        assert pending_enrichment_count(db, "v1") == len(jobs_needing_enrichment(db, "v1"))
