"""Her decisions — the one table she writes to.

Five statuses, one date she cares about (`applied_on`), and notes. The date is
set the first time a job is marked applied and is never rewritten afterwards:
marking the same job "rejected" a week later must not move the day she
actually sent the application.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

VALID_STATUSES = ("new", "interested", "applied", "rejected", "deleted")


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


def _require_known_job(connection: sqlite3.Connection, job_id: str) -> None:
    row = connection.execute("SELECT 1 FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
    if row is None:
        raise ValueError(f"Unknown job '{job_id}' — it is not in the store.")


def set_status(
    connection: sqlite3.Connection, job_id: str, status: str, *, now: str | None = None
) -> None:
    """Set one job's status, stamping `applied_on` on the first 'applied'."""
    if status not in VALID_STATUSES:
        raise ValueError(
            f"'{status}' is not a status. Valid statuses are: {', '.join(VALID_STATUSES)}."
        )
    _require_known_job(connection, job_id)

    existing = connection.execute(
        "SELECT applied_on FROM status WHERE job_id = ?", (job_id,)
    ).fetchone()
    applied_on = existing["applied_on"] if existing is not None else None
    if status == "applied" and not applied_on:
        # First time applied — this is the date the job page shows back to her.
        applied_on = now or _utc_now()

    connection.execute(
        "INSERT INTO status (job_id, status, notes, updated_at, applied_on)"
        " VALUES (?, ?, ?, ?, ?)"
        " ON CONFLICT(job_id) DO UPDATE SET"
        " status = excluded.status,"
        " updated_at = excluded.updated_at,"
        " applied_on = excluded.applied_on",
        (job_id, status, None, now or _utc_now(), applied_on),
    )
    connection.commit()


def set_notes(connection: sqlite3.Connection, job_id: str, notes: str) -> None:
    """Save her note on one job; an empty string clears it."""
    _require_known_job(connection, job_id)
    connection.execute(
        "INSERT INTO status (job_id, notes, updated_at) VALUES (?, ?, ?)"
        " ON CONFLICT(job_id) DO UPDATE SET notes = excluded.notes,"
        " updated_at = excluded.updated_at",
        (job_id, notes, _utc_now()),
    )
    connection.commit()


def get_status(connection: sqlite3.Connection, job_id: str) -> sqlite3.Row | None:
    """Her row for one job, or None when she has never touched it."""
    return connection.execute("SELECT * FROM status WHERE job_id = ?", (job_id,)).fetchone()
