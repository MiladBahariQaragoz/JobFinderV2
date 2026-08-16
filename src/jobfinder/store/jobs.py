"""`upsert_job` — the §5 re-run rule and the § Phase 5 cross-source merge.

New job: insert into `jobs` (+ `job_descriptions`, + a `status` row reading
'new'). Known job: move `last_seen_at`, touch nothing else. Same ad from
another site (`dedupe_key` match under a different `job_id`): merge into the
existing row — its identity, her status and any existing description stay;
what the row lacks is backfilled from the richer sighting; the alternate
source is recorded in `also_seen_on`.
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
    dedupe_key = make_dedupe_key(title=posting.title, company=posting.company, city=posting.city)
    known = connection.execute("SELECT 1 FROM jobs WHERE job_id = ?", (posting.job_id,)).fetchone()

    if known is not None:
        connection.execute(
            "UPDATE jobs SET last_seen_at = ? WHERE job_id = ?",
            (now, posting.job_id),
        )
        connection.commit()
        return "duplicate"

    # Only across sources. One site listing two openings with the same title,
    # company and town means two jobs she can apply to (live BA data: two Penny
    # Werkstudent ads in Neuburg under two reference numbers) — merging those
    # would quietly delete one of them.
    twin = connection.execute(
        "SELECT job_id, also_seen_on, has_description, apply_url FROM jobs"
        " WHERE dedupe_key = ? AND source != ?",
        (dedupe_key, posting.source),
    ).fetchone()
    if twin is not None:
        _merge_into(connection, twin, posting, now=now)
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


def _merge_into(
    connection: sqlite3.Connection, twin: sqlite3.Row, posting: RawPosting, *, now: str
) -> None:
    """The same ad from another site: record the alternate, keep what is richer.

    The existing row keeps its identity — `job_id`, `first_seen_at`, her
    status, and any description it already holds. Only fields it lacks are
    backfilled from the newcomer.
    """
    seen_on = twin["also_seen_on"] or ""
    alternates = [part for part in seen_on.split(",") if part]
    if posting.source not in alternates:
        alternates.append(posting.source)
    connection.execute(
        "UPDATE jobs SET also_seen_on = ?, last_seen_at = ? WHERE job_id = ?",
        (",".join(alternates), now, twin["job_id"]),
    )
    if posting.has_description and not twin["has_description"]:
        connection.execute(
            "UPDATE jobs SET has_description = 1, content_hash = ? WHERE job_id = ?",
            (posting.content_hash, twin["job_id"]),
        )
        connection.execute(
            "INSERT OR IGNORE INTO job_descriptions (job_id, description) VALUES (?, ?)",
            (twin["job_id"], posting.description),
        )
    if not twin["apply_url"] and posting.apply_url:
        connection.execute(
            "UPDATE jobs SET apply_url = ? WHERE job_id = ?",
            (posting.apply_url, twin["job_id"]),
        )
    connection.commit()
