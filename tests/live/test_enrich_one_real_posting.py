"""One real stored posting, explained end to end — opt-in, spends quota.

Run with: pytest -m live_llm

Everything else in the suite proves the wiring against a fake. This proves the
one thing a fake cannot: that a real free-tier provider, reading a real German
Bundesagentur ad through the real prompt, returns an answer that passes the
validator — and that when it names a German level, the phrase it quotes is
genuinely in the ad rather than invented.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jobfinder.config import Settings
from jobfinder.enrich.runner import run_enrichment
from jobfinder.llm.pool import build_pool
from jobfinder.llm.schema import enrichment_answer_validator, evidence_supports_the_level
from jobfinder.profile import load_profile
from jobfinder.roles import build_cv_digest
from jobfinder.store.db import connect, migrate
from jobfinder.store.enrichment import jobs_needing_enrichment, stored_enrichments

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Long enough that the ad can actually state a language requirement. A teaser
# would legitimately answer "unclear", which proves nothing about the evidence
# rule this test exists for.
MIN_AD_CHARACTERS = 800


@pytest.fixture
def real_store():
    """Her real database, read-only. Skips when there is nothing stored yet."""
    settings = Settings.load(PROJECT_ROOT)
    if not settings.db_path.exists():
        pytest.skip("no stored jobs yet — run `jobfinder search` first")
    connection = connect(settings.db_path)
    migrate(connection)
    yield settings, connection
    connection.close()


@pytest.mark.live_llm
def test_one_stored_bundesagentur_ad_is_explained_in_english(real_store, tmp_path):
    settings, connection = real_store

    candidates = [
        job
        for job in jobs_needing_enrichment(connection, "v1", force=True)
        if job["job_id"].startswith("BA") and len(job["description"]) >= MIN_AD_CHARACTERS
    ]
    if not candidates:
        pytest.skip(f"no stored BA ad of at least {MIN_AD_CHARACTERS} characters")
    job = candidates[0]

    # A scratch database holding just this job, so the live run cannot touch
    # her real store or re-spend answers it already has.
    scratch = connect(tmp_path / "one-job.db")
    migrate(scratch)
    columns = [row[1] for row in connection.execute("PRAGMA table_info(jobs)")]
    row = connection.execute(
        f"SELECT {', '.join(columns)} FROM jobs WHERE job_id = ?", (job["job_id"],)
    ).fetchone()
    scratch.execute(
        f"INSERT INTO jobs ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})",
        tuple(row),
    )
    scratch.execute(
        "INSERT INTO job_descriptions (job_id, description) VALUES (?, ?)",
        (job["job_id"], job["description"]),
    )
    scratch.commit()

    scratch_settings = Settings(project_root=tmp_path)
    pool = build_pool(settings, enrichment_answer_validator)

    result = run_enrichment(
        scratch,
        pool,
        scratch_settings,
        cv_digest=build_cv_digest(load_profile(settings.pool_path)),
        csv_path=scratch_settings.jobs_enriched_csv,
        workers=1,
    )

    assert result.enriched == 1, f"nothing came back: {result.errors}"

    answer = stored_enrichments(scratch, "v1")[0].answer
    scratch.close()

    ok, reason = enrichment_answer_validator(answer)
    assert ok, reason

    # The two promises §5 makes to her, on real text.
    assert answer["summary_en"].strip(), "she gets an empty summary"
    if answer["german_level"] != "unclear":
        evidence = answer["german_evidence"].strip()
        assert evidence, "a level with no evidence should never have passed the validator"
        # Compared the way the product compares it: real postings are full of
        # non-breaking spaces and hard wraps, and a model that re-spaces what
        # it copied has still copied it.
        assert evidence_supports_the_level(answer, job["description"]), (
            f"german_level {answer['german_level']!r} is justified by "
            f"{evidence!r}, which is not in the ad"
        )
