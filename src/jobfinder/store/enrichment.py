"""Save one answer; know which jobs still need one.

Her free-tier quota is the scarce resource, so the skip rule is the point of
this module: a job already explained at this prompt version, whose ad text has
not changed since, is never sent again. That second half is why the row carries
the `content_hash` it was answered from.

A new prompt version appends rather than overwrites (§5) — the answer she read
yesterday is still there tomorrow, under its old version.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class StoredEnrichment:
    """One saved answer, in the shape the CSV export needs."""

    job_id: str
    enriched_at: str
    provider_used: str
    answer: dict[str, Any]


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


def save_enrichment(
    connection: sqlite3.Connection,
    job_id: str,
    prompt_version: str,
    content_hash: str | None,
    answer: dict[str, Any],
    *,
    provider_used: str = "",
    now: str | None = None,
) -> str:
    """Store one answer and commit, so a kill the next instant costs nothing.

    Returns the `enriched_at` stamp written, which is what the CSV line the
    caller appends has to carry.
    """
    enriched_at = now or _utc_now()
    connection.execute(
        "INSERT OR REPLACE INTO enrichment"
        " (job_id, prompt_version, answer, enriched_at, content_hash, provider_used)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (
            job_id,
            prompt_version,
            json.dumps(answer, ensure_ascii=False),
            enriched_at,
            content_hash,
            provider_used or "",
        ),
    )
    connection.commit()
    return enriched_at


# Everything the prompt needs, in one query — a second round trip per job would
# double the database traffic of a run that is already sharing the file with a
# search (§8 rule 2).
_JOB_COLUMNS = (
    "j.job_id, j.title, j.company, j.city, j.employment_type_raw, j.is_minijob,"
    " j.is_werkstudent, j.is_parttime, j.is_fulltime, j.is_internship, j.homeoffice,"
    " j.apply_url, j.source_url, j.content_hash, d.description"
)

# "No answer at this version, or one read from a different version of the ad."
# LEFT JOIN + IS NULL rather than NOT IN: the same statement then serves the
# `--force` case by dropping the WHERE clause.
_NEEDS_ENRICHMENT = f"""
SELECT {_JOB_COLUMNS}
FROM jobs j
JOIN job_descriptions d ON d.job_id = j.job_id
LEFT JOIN enrichment e ON e.job_id = j.job_id AND e.prompt_version = ?
WHERE d.description IS NOT NULL AND TRIM(d.description) != ''
  AND (e.job_id IS NULL OR e.content_hash IS NOT j.content_hash)
ORDER BY j.first_seen_at, j.job_id
"""

_ALL_WITH_DESCRIPTION = f"""
SELECT {_JOB_COLUMNS}
FROM jobs j
JOIN job_descriptions d ON d.job_id = j.job_id
WHERE d.description IS NOT NULL AND TRIM(d.description) != ''
ORDER BY j.first_seen_at, j.job_id
"""


def jobs_needing_enrichment(
    connection: sqlite3.Connection,
    prompt_version: str,
    *,
    limit: int | None = None,
    force: bool = False,
) -> list[sqlite3.Row]:
    """Jobs to send, oldest sighting first — she waited longest for those.

    A job with no ad text is never sent: there is nothing to explain, and the
    model would invent the answer.
    """
    if force:
        sql, parameters = _ALL_WITH_DESCRIPTION, ()
    else:
        sql, parameters = _NEEDS_ENRICHMENT, (prompt_version,)
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    return connection.execute(sql, parameters).fetchall()


def already_enriched_count(connection: sqlite3.Connection, prompt_version: str) -> int:
    """How many jobs are already explained at this version — §10's progress line."""
    return int(
        connection.execute(
            "SELECT COUNT(*) FROM enrichment WHERE prompt_version = ?", (prompt_version,)
        ).fetchone()[0]
    )


def stored_enrichments(
    connection: sqlite3.Connection, prompt_version: str
) -> list[StoredEnrichment]:
    """Every saved answer at this version, job by job, for the full re-export.

    A row whose JSON will not parse is skipped rather than raised: one corrupt
    answer must not cost her the other six hundred.
    """
    rows = connection.execute(
        "SELECT job_id, enriched_at, provider_used, answer FROM enrichment"
        " WHERE prompt_version = ? ORDER BY job_id",
        (prompt_version,),
    ).fetchall()

    stored: list[StoredEnrichment] = []
    for row in rows:
        try:
            answer = json.loads(row["answer"])
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(answer, dict):
            continue
        stored.append(
            StoredEnrichment(
                job_id=row["job_id"],
                enriched_at=row["enriched_at"],
                provider_used=row["provider_used"] or "",
                answer=answer,
            )
        )
    return stored
