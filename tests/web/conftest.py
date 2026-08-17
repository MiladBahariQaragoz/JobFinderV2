"""Shared fixtures for the web tests: a seeded store behind a real Settings."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from jobfinder.config import Settings
from jobfinder.sources.base import RawPosting
from jobfinder.store.db import connect, migrate
from jobfinder.store.enrichment import save_enrichment
from jobfinder.web.app import create_app

# The enrichment answers land at the version the app reads — the same one the
# prompt file carries, so the LEFT JOIN in the list query finds them.
PROMPT_VERSION = "v1"


def enrichment_answer(**overrides) -> dict:
    """A valid answer, minimal but shaped like the real thing (§5)."""
    values = {
        "category": "retail",
        "seniority": "entry",
        "skills_required": ["customer service"],
        "skills_nice": [],
        "german_level": "B1",
        "german_evidence": "Gute Deutschkenntnisse",
        "english_sufficient": False,
        "employment_type_norm": "minijob",
        "hours_per_week": 15,
        "duties_en": ["Serve customers"],
        "requirements_en": ["Reliable"],
        "summary_en": "A counter job at a bakery.",
        "fit_score": 60,
        "fit_reasons": ["Her retail experience matches"],
        "missing_for_fit": [],
        "red_flags": [],
        "application_method": "email",
        "contact_email": "jobs@example.de",
        "contact_phone": "",
        "deadline": "",
    }
    values.update(overrides)
    return values


def store_job(
    connection,
    *,
    job_id: str = "BA:1",
    title: str = "Aushilfe Verkauf",
    company: str = "Bäckerei Müller & Söhne",
    city: str = "Ingolstadt",
    source: str = "BA",
    lat: float | None = 48.7665,
    lon: float | None = 11.4258,
    minijob: bool = False,
    werkstudent: bool = False,
    parttime: bool = False,
    fulltime: bool = False,
    description: str | None = "Wir suchen eine Aushilfe. Gute Deutschkenntnisse erforderlich.",
    published_at: str | None = None,
    answer: dict | None = None,
    status: str | None = None,
    last_seen_days_ago: int = 0,
    source_url: str | None = None,
    apply_url: str | None = None,
) -> str:
    """One job in the store, the way the search and enrichment would leave it."""
    from datetime import UTC, datetime, timedelta

    from jobfinder.store.jobs import upsert_job
    from jobfinder.store.status import set_status

    source_id = job_id.split(":", 1)[1]
    # Every real posting carries a link back to its ad — measured 859/859 on
    # her store — so the fixture does too, or the apply path tests nothing.
    if source_url is None:
        source_url = f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{source_id}"

    upsert_job(
        connection,
        RawPosting(
            job_id=job_id,
            source=source,
            source_id=source_id,
            source_url=source_url,
            apply_url=apply_url,
            title=title,
            company=company,
            city=city,
            lat=lat,
            lon=lon,
            is_minijob=minijob,
            is_werkstudent=werkstudent,
            is_parttime=parttime,
            is_fulltime=fulltime,
            published_at=published_at,
            description=description,
        ),
    )
    if answer is not None:
        save_enrichment(connection, job_id, PROMPT_VERSION, "hash", answer)
    if status is not None:
        set_status(connection, job_id, status)
    if last_seen_days_ago:
        seen = (datetime.now(UTC) - timedelta(days=last_seen_days_ago)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        connection.execute("UPDATE jobs SET last_seen_at = ? WHERE job_id = ?", (seen, job_id))
        connection.commit()
    return job_id


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(project_root=tmp_path)


@pytest.fixture
def seeded(settings) -> Settings:
    """A store with a spread of jobs: two cities, two types, three German
    levels, one deleted, one stale — enough to make every filter bite."""
    connection = connect(settings.db_path)
    try:
        migrate(connection)
        store_job(
            connection,
            job_id="BA:1",
            title="Aushilfe Verkauf Minijob",
            city="Ingolstadt",
            minijob=True,
            answer=enrichment_answer(german_level="B1", fit_score=60),
        )
        store_job(
            connection,
            job_id="BA:2",
            title="Werkstudent Datenanalyse",
            city="München",
            werkstudent=True,
            answer=enrichment_answer(german_level="C1", fit_score=85),
        )
        store_job(
            connection,
            job_id="BA:3",
            title="Küchenhilfe",
            city="Ingolstadt",
            minijob=True,
            answer=enrichment_answer(german_level="unclear", german_evidence="", fit_score=40),
        )
        store_job(
            connection,
            job_id="AN:4",
            title="Retail Assistant",
            city="München",
            source="AN",
            parttime=True,
            answer=enrichment_answer(german_level="A2", fit_score=95),
        )
        store_job(
            connection,
            job_id="BA:5",
            title="Gelöscht hier",
            city="Ingolstadt",
            status="deleted",
        )
    finally:
        connection.close()
    return settings


@pytest.fixture
def client(seeded) -> TestClient:
    with TestClient(create_app(seeded)) as test_client:
        yield test_client
