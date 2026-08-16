"""The enrichment batch — resumable by construction.

§9's rule is the design: each answer is in SQLite and in the CSV before the
next job is sent. Everything here is a way of asking "what survives a kill?"
— because on her laptop, on a free tier, the run *will* be interrupted.
"""

from __future__ import annotations

import csv

import pytest
from llmpool import PoolExhausted
from tests.fakes import FakePool

from jobfinder.config import Settings
from jobfinder.enrich.runner import run_enrichment
from jobfinder.sources.base import RawPosting
from jobfinder.store.db import connect, migrate
from jobfinder.store.enrichment import save_enrichment
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
def db(tmp_path):
    connection = connect(tmp_path / "jobfinder.db")
    migrate(connection)
    yield connection
    connection.close()


@pytest.fixture
def settings(tmp_path):
    return Settings(project_root=tmp_path)


def store_jobs(connection, count: int, *, text: str | None = None) -> list[str]:
    """`count` distinct jobs, each with its own ad text (so each needs its own call)."""
    ids = []
    for index in range(count):
        job_id = f"BA:{index:03d}"
        upsert_job(
            connection,
            RawPosting(
                job_id=job_id,
                source="BA",
                source_id=job_id,
                title=f"Aushilfe Bäckerei {index} (m/w/d)",
                company="Bäckerei Musterle",
                city="Ingolstadt",
                description=text or f"Wir suchen eine Aushilfe für Filiale {index}.",
            ),
        )
        ids.append(job_id)
    return ids


def enrich(connection, pool, settings, **kwargs):
    kwargs.setdefault("cv_digest", DIGEST)
    kwargs.setdefault("workers", 1)  # deterministic order, so counts are checkable
    kwargs.setdefault("csv_path", settings.jobs_enriched_csv)
    return run_enrichment(connection, pool, settings, **kwargs)


def enriched_ids(connection) -> list[str]:
    rows = connection.execute("SELECT job_id FROM enrichment ORDER BY job_id").fetchall()
    return [row[0] for row in rows]


def csv_rows(path):
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig", newline="") as handle:
        return list(csv.reader(handle))


class TestOneJob:
    def test_a_stored_job_comes_back_explained_in_english(self, db, settings):
        store_jobs(db, 1)
        pool = FakePool([answer()])

        result = enrich(db, pool, settings)

        assert result.enriched == 1
        stored = db.execute("SELECT answer FROM enrichment").fetchone()[0]
        assert "A weekend job at a bakery counter" in stored

    def test_the_prompt_carries_the_ad_text_the_job_facts_and_her_digest(self, db, settings):
        store_jobs(db, 1)
        pool = FakePool([answer()])

        enrich(db, pool, settings)

        prompt = pool.calls[0]
        assert "Wir suchen eine Aushilfe für Filiale 0." in prompt
        assert "Bäckerei Musterle" in prompt
        assert "Python, MATLAB" in prompt

    def test_the_answer_is_stored_against_the_ad_text_it_was_read_from(self, db, settings):
        store_jobs(db, 1)

        enrich(db, FakePool([answer()]), settings)

        row = db.execute(
            "SELECT e.content_hash, j.content_hash FROM enrichment e"
            " JOIN jobs j ON j.job_id = e.job_id"
        ).fetchone()
        assert row[0] == row[1]


class TestPersistingAsItGoes:
    def test_batch_persists_each_result_as_it_lands(self, db, settings):
        # Ten jobs, a pool that dies after three. §9: the three are hers.
        store_jobs(db, 10)
        pool = FakePool([answer(), answer(), answer(), PoolExhausted("daily cap")])

        result = enrich(db, pool, settings)

        assert result.enriched == 3
        assert len(enriched_ids(db)) == 3
        assert len(csv_rows(settings.jobs_enriched_csv)) == 4  # header + three

    def test_the_csv_line_lands_with_the_answer_not_at_the_end_of_the_run(self, db, settings):
        store_jobs(db, 3)
        seen: list[int] = []

        def count_csv_lines(*_args, **_kwargs):
            seen.append(len(csv_rows(settings.jobs_enriched_csv)))

        enrich(
            db,
            FakePool([answer(), answer(), answer()]),
            settings,
            on_progress=count_csv_lines,
        )

        # Header plus one row per answer already on disk, each time.
        assert seen == [2, 3, 4]

    def test_an_interrupted_run_leaves_a_csv_she_can_open(self, db, settings):
        store_jobs(db, 5)
        pool = FakePool([answer(), PoolExhausted("no capacity")])

        enrich(db, pool, settings)

        rows = csv_rows(settings.jobs_enriched_csv)
        assert rows[0][0] == "job_id"
        assert rows[1][rows[0].index("summary_en")].startswith("A weekend job")


class TestFailuresDoNotEndTheRun:
    def test_one_failing_item_does_not_end_the_batch(self, db, settings):
        store_jobs(db, 3)
        pool = FakePool([answer(), RuntimeError("provider blew up"), answer()])

        result = enrich(db, pool, settings)

        assert result.enriched == 2
        assert result.failed == 1
        assert enriched_ids(db) == ["BA:000", "BA:002"]

    def test_a_junk_answer_is_refused_and_leaves_that_job_unenriched(self, db, settings):
        store_jobs(db, 2)
        # A level with no evidence — §5 forbids storing it.
        junk = answer(german_level="B2", german_evidence="")
        pool = FakePool([junk, answer()])

        result = enrich(db, pool, settings)

        assert enriched_ids(db) == ["BA:001"]
        assert result.failed == 1
        assert any("german_evidence" in error for error in result.errors)

    def test_a_failed_job_is_offered_again_on_the_next_run(self, db, settings):
        store_jobs(db, 1)
        enrich(db, FakePool([RuntimeError("blew up")]), settings)

        result = enrich(db, FakePool([answer()]), settings)

        assert result.enriched == 1


class TestQuota:
    def test_pool_exhausted_stops_cleanly_with_a_resumable_message(self, db, settings):
        store_jobs(db, 6)
        pool = FakePool([answer(), PoolExhausted("free tier spent for today")])

        result = enrich(db, pool, settings)

        assert result.quota_spent is True
        assert result.enriched == 1
        assert result.remaining == 5

    def test_a_spent_quota_stops_the_run_rather_than_retrying_every_job(self, db, settings):
        store_jobs(db, 20)
        pool = FakePool([PoolExhausted("spent")] * 20)

        enrich(db, pool, settings, workers=2)

        # It gives up inside the first batch instead of asking twenty times.
        assert len(pool.calls) < 20

    def test_enrich_limit_respects_the_llm_budget(self, db, settings):
        store_jobs(db, 10)
        budgeted = Settings(project_root=settings.project_root, llm_budget=4)

        result = enrich(db, FakePool([answer()] * 10), budgeted)

        assert result.enriched == 4
        assert len(enriched_ids(db)) == 4

    def test_a_limit_smaller_than_the_budget_wins(self, db, settings):
        store_jobs(db, 10)

        result = enrich(db, FakePool([answer()] * 10), settings, limit=2)

        assert result.enriched == 2


class TestNotSpendingWhatIsAlreadySpent:
    def test_a_second_run_enriches_nothing_and_makes_zero_calls(self, db, settings):
        store_jobs(db, 3)
        enrich(db, FakePool([answer()] * 3), settings)

        pool = FakePool([])
        result = enrich(db, pool, settings)

        assert pool.calls == []
        assert result.total == 0
        assert result.enriched == 0

    def test_two_identical_postings_cost_one_call(self, db, settings):
        # Same ad, same shop, listed twice: 60 of her 674 stored postings are
        # identical to another one down to the title and company, and an
        # identical prompt has an identical answer.
        for job_id in ("BA:twin-a", "BA:twin-b"):
            upsert_job(
                db,
                RawPosting(
                    job_id=job_id,
                    source="BA",
                    source_id=job_id,
                    title="Aushilfe Bäckerei (m/w/d)",
                    company="Bäckerei Musterle",
                    city="Ingolstadt",
                    description="Wir suchen eine Aushilfe für unsere Theke in Ingolstadt.",
                ),
            )
        pool = FakePool([answer()])

        result = enrich(db, pool, settings)

        assert result.enriched == 2
        assert len(pool.calls) == 1

    def test_the_same_ad_from_a_different_company_is_asked_again(self, db, settings):
        # The cache is keyed on the whole prompt, not the ad text: answering
        # one shop's posting with another shop's answer would put the wrong
        # company in her summary.
        text = "Wir suchen eine Aushilfe für unsere Theke."
        for job_id, company in (("BA:one", "Bäckerei Eins"), ("BA:two", "Bäckerei Zwei")):
            upsert_job(
                db,
                RawPosting(
                    job_id=job_id,
                    source="BA",
                    source_id=job_id,
                    title="Aushilfe (m/w/d)",
                    company=company,
                    city="Ingolstadt",
                    description=text,
                ),
            )
        pool = FakePool([answer(), answer()])

        enrich(db, pool, settings)

        assert len(pool.calls) == 2

    def test_force_re_enriches_a_job_already_explained(self, db, settings):
        # --force means "ask again", so it has to reach past the answer cache
        # as well as past the stored row — otherwise it re-saves yesterday's.
        store_jobs(db, 1)
        enrich(db, FakePool([answer()]), settings)

        result = enrich(db, FakePool([answer(fit_score=90)]), settings, force=True)

        assert result.enriched == 1
        assert '"fit_score": 90' in db.execute("SELECT answer FROM enrichment").fetchone()[0]

    def test_a_job_with_no_ad_text_is_never_sent(self, db, settings):
        upsert_job(
            db,
            RawPosting(
                job_id="BA:empty",
                source="BA",
                source_id="empty",
                title="Aushilfe",
                company="Musterle",
                city="Ingolstadt",
                description=None,
            ),
        )
        pool = FakePool([])

        result = enrich(db, pool, settings)

        assert result.total == 0
        assert pool.calls == []


class TestNarration:
    def test_progress_reports_real_counts_read_from_the_store(self, db, settings):
        store_jobs(db, 4)
        save_enrichment(db, "BA:000", "v1", "stale", answer())  # one already done, at a stale hash
        reported: list[tuple[int, int]] = []

        enrich(
            db,
            FakePool([answer()] * 4),
            settings,
            on_progress=lambda done, total, job: reported.append((done, total)),
        )

        assert reported == [(1, 4), (2, 4), (3, 4), (4, 4)]

    def test_the_result_says_how_many_are_still_unexplained(self, db, settings):
        store_jobs(db, 7)

        result = enrich(db, FakePool([answer()] * 3), settings, limit=3)

        assert result.enriched == 3
        assert result.remaining == 4
