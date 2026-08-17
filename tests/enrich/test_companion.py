"""Enrichment as a second worker, while the search is still storing jobs (§9).

A search waits on job-site hosts; enrichment waits on LLM providers. They never
contend for the same host, and the store is the handover: a job committed to
SQLite is a job that can be explained. Running them one after the other would
add their wall times together for nothing.
"""

from __future__ import annotations

import csv

import pytest
from llmpool import PoolExhausted
from tests.fakes import FakePool

from jobfinder.config import Settings
from jobfinder.enrich.companion import EnrichmentCompanion
from jobfinder.sources.base import RawPosting
from jobfinder.store.db import connect, migrate
from jobfinder.store.jobs import upsert_job

DIGEST = "# Skills\n- Programming Languages: Python, MATLAB"


def answer(**overrides) -> dict:
    values = {
        "category": "retail",
        "seniority": "entry",
        "skills_required": ["customer service"],
        "skills_nice": [],
        "german_level": "B1",
        "german_evidence": "Gute Deutschkenntnisse in Wort und Schrift",
        "english_sufficient": False,
        "employment_type_norm": "minijob",
        "duties_en": ["Serve customers at the counter"],
        "requirements_en": ["Reliable"],
        "summary_en": "A weekend job at a bakery counter in Ingolstadt.",
        "fit_score": 62,
        "fit_reasons": ["Her retail experience matches"],
        "missing_for_fit": ["Stronger spoken German"],
        "red_flags": [],
        "application_method": "email",
        "contact_email": "jobs@example.de",
        "contact_phone": "",
        "deadline": "",
    }
    values.update(overrides)
    return values


@pytest.fixture
def db_path(tmp_path):
    connection = connect(tmp_path / "jobfinder.db")
    migrate(connection)
    connection.close()
    return tmp_path / "jobfinder.db"


@pytest.fixture
def settings(tmp_path):
    return Settings(project_root=tmp_path)


def store_job(db_path, index: int) -> None:
    """What the search does: migrate, then one job, committed, on its own connection."""
    connection = connect(db_path)
    migrate(connection)
    upsert_job(
        connection,
        RawPosting(
            job_id=f"BA:{index:03d}",
            source="BA",
            source_id=f"{index:03d}",
            title=f"Aushilfe Bäckerei {index} (m/w/d)",
            company="Bäckerei Musterle",
            city="Ingolstadt",
            description=(
                f"Wir suchen eine Aushilfe für Filiale {index}. "
                "Gute Deutschkenntnisse in Wort und Schrift sind erforderlich."
            ),
        ),
    )
    connection.close()


def companion(db_path, pool, settings, **kwargs):
    kwargs.setdefault("cv_digest", DIGEST)
    kwargs.setdefault("csv_path", settings.jobs_enriched_csv)
    kwargs.setdefault("workers", 1)
    kwargs.setdefault("poll_seconds", 0.01)  # the test must not wait two seconds
    return EnrichmentCompanion(db_path, pool, settings, **kwargs)


def enriched_ids(db_path) -> list[str]:
    connection = connect(db_path)
    rows = connection.execute("SELECT job_id FROM enrichment ORDER BY job_id").fetchall()
    connection.close()
    return [row[0] for row in rows]


def csv_rows(path):
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig", newline="") as handle:
        return list(csv.reader(handle))


def test_enrichment_started_during_a_search_enriches_what_the_search_stored(db_path, settings):
    """The store is the queue: the worker starts on an empty database and picks
    up each job the search commits, without any handover between the two."""
    worker = companion(db_path, FakePool([answer()] * 4), settings)
    worker.start()

    for index in range(4):  # the "search", storing as it goes
        store_job(db_path, index)

    result = worker.finish()

    assert result.enriched == 4
    assert enriched_ids(db_path) == ["BA:000", "BA:001", "BA:002", "BA:003"]


def test_a_worker_that_finds_nothing_waits_instead_of_finishing(db_path, settings):
    # It must not decide the search is over just because the first poll was empty.
    worker = companion(db_path, FakePool([answer()]), settings)
    worker.start()
    store_job(db_path, 0)

    assert worker.finish().enriched == 1


def test_the_worker_stops_once_the_search_is_done_and_the_store_is_empty(db_path, settings):
    worker = companion(db_path, FakePool([]), settings)
    worker.start()

    result = worker.finish()

    assert result.enriched == 0
    assert result.total == 0


def test_each_answer_is_on_disk_before_the_worker_is_joined(db_path, settings):
    worker = companion(db_path, FakePool([answer()] * 2), settings)
    worker.start()
    for index in range(2):
        store_job(db_path, index)
    worker.finish()

    assert len(csv_rows(settings.jobs_enriched_csv)) == 3  # header + two


def test_a_spent_quota_stops_the_worker_and_is_reported(db_path, settings):
    worker = companion(db_path, FakePool([answer(), PoolExhausted("daily cap")]), settings)
    worker.start()
    for index in range(4):
        store_job(db_path, index)

    result = worker.finish()

    assert result.quota_spent is True
    assert result.enriched == 1


def test_the_worker_never_shares_the_searchs_connection(db_path, settings):
    # §8 rule 2: one connection per thread. A shared one raises on Windows the
    # moment the worker touches it, and silently corrupts nothing — it just
    # kills the run.
    search_connection = connect(db_path)
    worker = companion(db_path, FakePool([answer()]), settings)
    worker.start()
    store_job(db_path, 0)
    result = worker.finish()
    search_connection.close()

    assert result.enriched == 1


def test_a_failing_job_does_not_kill_the_worker(db_path, settings):
    worker = companion(db_path, FakePool([RuntimeError("blew up"), answer()]), settings)
    worker.start()
    store_job(db_path, 0)
    store_job(db_path, 1)

    result = worker.finish()

    assert result.enriched == 1
    assert result.failed == 1


def test_the_run_total_covers_every_batch_not_just_the_last(db_path, settings):
    worker = companion(db_path, FakePool([answer()] * 3), settings)
    worker.start()
    for index in range(3):
        store_job(db_path, index)

    result = worker.finish()

    assert result.enriched == 3
    assert result.total == 3


def test_the_worker_honours_the_llm_budget_across_batches(db_path, settings):
    budgeted = Settings(project_root=settings.project_root, llm_budget=2)
    pool = FakePool([answer()] * 5)
    worker = companion(db_path, pool, budgeted, csv_path=budgeted.jobs_enriched_csv)
    worker.start()
    for index in range(5):
        store_job(db_path, index)

    result = worker.finish()

    assert result.enriched == 2
    assert len(pool.calls) == 2


def test_progress_is_narrated_with_the_jobs_it_explains(db_path, settings):
    seen: list[str] = []
    worker = companion(
        db_path,
        FakePool([answer()] * 2),
        settings,
        on_progress=lambda done, total, job: seen.append(job["title"]),
    )
    worker.start()
    for index in range(2):
        store_job(db_path, index)
    worker.finish()

    assert seen == ["Aushilfe Bäckerei 0 (m/w/d)", "Aushilfe Bäckerei 1 (m/w/d)"]


def test_the_worker_survives_a_database_that_has_no_schema_yet(tmp_path, settings):
    """On a first-ever run the companion starts before the search has migrated.

    Without its own `migrate` the very first poll raises "no such table: jobs",
    the worker gives up, and the whole run silently enriches nothing.
    """
    fresh = tmp_path / "brand-new.db"
    worker = companion(fresh, FakePool([answer()]), settings)
    worker.start()
    store_job(fresh, 0)

    result = worker.finish()

    assert result.enriched == 1
    assert result.errors == []


class TestRunJournal:
    """The companion writes its own line in the `runs` journal (§9, §10).

    The web app's progress panel reads the database, so an enrichment that
    runs behind a search has to be visible there too — while it runs, not
    only once it has finished.
    """

    def run_rows(self, db_path):
        connection = connect(db_path)
        try:
            return connection.execute(
                "SELECT * FROM runs WHERE kind = 'enrich' ORDER BY id"
            ).fetchall()
        finally:
            connection.close()

    def wait_for_row(self, db_path, *, state: str, timeout: float = 5.0):
        import time

        deadline = time.time() + timeout
        while time.time() < deadline:
            rows = self.run_rows(db_path)
            if rows and rows[-1]["state"] == state:
                return rows[-1]
            time.sleep(0.01)
        raise AssertionError(f"no enrich run row reached state {state!r}")

    def test_companion_journals_its_progress_and_finishes_done(self, db_path, settings):
        for index in range(3):
            store_job(db_path, index)
        worker = companion(db_path, FakePool([answer()] * 3), settings)
        worker.start()

        running = self.wait_for_row(db_path, state="running")
        result = worker.finish()

        (row,) = self.run_rows(db_path)
        assert running["started_at"]
        assert row["state"] == "done"
        assert row["enriched_count"] == result.enriched == 3
        assert row["finished_at"]

    def test_enriched_count_moves_as_answers_land(self, db_path, settings):
        import threading
        import time

        gate = threading.Event()

        class GatedPool(FakePool):
            def __init__(self, answers):
                super().__init__(answers)
                self.parked: list[str] = []  # recorded before the gate, not after

            def complete_json(self, prompt):
                self.parked.append(prompt)
                gate.wait(timeout=5)
                return super().complete_json(prompt)

        store_job(db_path, 0)
        store_job(db_path, 1)
        pool = GatedPool([answer()] * 2)
        worker = companion(db_path, pool, settings, workers=2)
        worker.start()

        # Both answers are in flight behind the gate: the row exists, counts 0.
        deadline = time.time() + 5
        while time.time() < deadline and len(pool.parked) < 2:
            time.sleep(0.01)
        assert len(pool.parked) == 2  # both workers are parked at the gate
        assert self.run_rows(db_path)[-1]["enriched_count"] == 0

        gate.set()
        worker.finish()

        assert self.run_rows(db_path)[-1]["enriched_count"] == 2

    def test_cancel_stops_the_worker_and_ends_the_run_interrupted(self, db_path, settings):
        for index in range(2):
            store_job(db_path, index)
        worker = companion(db_path, FakePool([answer()] * 2), settings)
        worker.start()
        worker.cancel()

        result = worker.finish()

        (row,) = self.run_rows(db_path)
        assert row["state"] == "interrupted"
        assert row["enriched_count"] == result.enriched  # whatever landed, kept
        assert row["finished_at"]


def test_companion_stops_after_the_limit_is_reached(db_path, settings):
    """A bound on the whole pass, not on one batch.

    The companion was built to keep up with an arriving search, so it drains
    until nothing is left. Pressed from the browser it would spend her entire
    free tier in one go, and the free-tier rule says a run announces its cost
    first — a cost it can only promise if it can be held to it.
    """
    for index in range(6):
        store_job(db_path, index)
    worker = companion(db_path, FakePool([answer()] * 6), settings, limit=2)

    worker.start()
    result = worker.finish()

    assert result.sent == 2
    assert enriched_ids(db_path) == ["BA:000", "BA:001"]


def test_companion_without_a_limit_keeps_the_old_behaviour(db_path, settings):
    for index in range(6):
        store_job(db_path, index)
    worker = companion(db_path, FakePool([answer()] * 6), settings)

    worker.start()

    assert worker.finish().sent == 6


def test_a_limit_larger_than_the_queue_enriches_the_queue_and_stops(db_path, settings):
    for index in range(2):
        store_job(db_path, index)
    worker = companion(db_path, FakePool([answer()] * 2), settings, limit=50)

    worker.start()
    result = worker.finish()

    assert result.sent == 2
    assert result.remaining == 0


def test_a_limited_pass_reports_what_is_still_waiting(db_path, settings):
    """The number the Enrich page shows after a bounded pass — she has to be
    able to see that pressing it again has something left to do."""
    for index in range(5):
        store_job(db_path, index)
    worker = companion(db_path, FakePool([answer()] * 5), settings, limit=2)

    worker.start()

    assert worker.finish().remaining == 3
