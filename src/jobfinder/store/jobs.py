"""`upsert_job` — the §5 re-run rule as one function.

New job: insert into `jobs` (+ `job_descriptions`, + a `status` row reading
'new'). Known job: move `last_seen_at`, touch nothing else — not the title,
not the description, never her status.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import Literal

from jobfinder.sources.base import RawPosting, make_dedupe_key

UpsertOutcome = Literal["new", "duplicate"]


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


def upsert_job(
    connection: sqlite3.Connection, posting: RawPosting, *, now: str | None = None
) -> UpsertOutcome:
    """Store a posting under its `job_id`; second sight moves only `last_seen_at`."""
    now = now or _utc_now()
    dedupe_key = make_dedupe_key(title=posting.title, company=posting.company, plz=posting.plz)
    known = connection.execute("SELECT 1 FROM jobs WHERE job_id = ?", (posting.job_id,)).fetchone()

    if known is not None:
        connection.execute(
            "UPDATE jobs SET last_seen_at = ? WHERE job_id = ?",
            (now, posting.job_id),
        )
        connection.commit()
        return "duplicate"

    connection.execute(
        "INSERT INTO jobs ("
        " job_id, source, source_id, dedupe_key, title, company, city, plz, lat, lon,"
        " employment_type_raw, is_minijob, is_parttime, is_fulltime, is_internship,"
        " is_werkstudent, homeoffice, published_at, apply_url, source_url,"
        " has_description, content_hash, first_seen_at, last_seen_at"
        ") VALUES ("
        " ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?"
        ")",
        (
            posting.job_id,
            posting.source,
            posting.source_id,
            dedupe_key,
            posting.title,
            posting.company,
            posting.city,
            posting.plz,
            posting.lat,
            posting.lon,
            posting.employment_type_raw,
            int(posting.is_minijob),
            int(posting.is_parttime),
            int(posting.is_fulltime),
            int(posting.is_internship),
            int(posting.is_werkstudent),
            int(posting.homeoffice),
            posting.published_at,
            posting.apply_url,
            posting.source_url,
            int(posting.has_description),
            posting.content_hash,
            now,
            now,
        ),
    )
    if posting.has_description:
        connection.execute(
            "INSERT INTO job_descriptions (job_id, description) VALUES (?, ?)",
            (posting.job_id, posting.description),
        )
    connection.execute("INSERT INTO status (job_id) VALUES (?)", (posting.job_id,))
    connection.commit()
    return "new"
