"""Per-source health, kept in `source_state` (§8 rule 7, Phase 6).

A source that has started refusing us is not worth asking again on every run
until someone notices — a blocked board would otherwise spend minutes of a
run timing out, every run. Three consecutive failures put it in cooldown with
a reason her summary can print in plain English, and one good page clears the
count, because a site that recovered should not stay punished.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

FAILURES_BEFORE_COOLDOWN = 3
COOLDOWN = timedelta(hours=24)

_STAMP = "%Y-%m-%d %H:%M:%S"


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(UTC)


def record_failure(
    connection: sqlite3.Connection,
    source: str,
    *,
    reason: str,
    now: datetime | None = None,
) -> int:
    """Count one failed run of a source; return its consecutive-failure count."""
    moment = _now(now)
    connection.execute(
        "INSERT INTO source_state (source, consecutive_failures) VALUES (?, 1)"
        " ON CONFLICT(source) DO UPDATE SET consecutive_failures = consecutive_failures + 1",
        (source,),
    )
    count = int(
        connection.execute(
            "SELECT consecutive_failures FROM source_state WHERE source = ?", (source,)
        ).fetchone()[0]
    )
    if count >= FAILURES_BEFORE_COOLDOWN:
        connection.execute(
            "UPDATE source_state SET cooldown_until = ?, last_error = ? WHERE source = ?",
            ((moment + COOLDOWN).strftime(_STAMP), reason, source),
        )
    else:
        connection.execute(
            "UPDATE source_state SET last_error = ? WHERE source = ?", (reason, source)
        )
    connection.commit()
    return count


def record_success(
    connection: sqlite3.Connection, source: str, *, now: datetime | None = None
) -> None:
    """A good page: the source is healthy again, whatever it did before."""
    connection.execute(
        "INSERT INTO source_state (source, consecutive_failures, last_success_at)"
        " VALUES (?, 0, ?)"
        " ON CONFLICT(source) DO UPDATE SET consecutive_failures = 0, cooldown_until = NULL,"
        " last_error = NULL, last_success_at = excluded.last_success_at",
        (source, _now(now).strftime(_STAMP)),
    )
    connection.commit()


def cooling_off(
    connection: sqlite3.Connection, source: str, *, now: datetime | None = None
) -> str | None:
    """Why this source is sitting this run out, or None if it should run."""
    row = connection.execute(
        "SELECT consecutive_failures, cooldown_until, last_error FROM source_state"
        " WHERE source = ?",
        (source,),
    ).fetchone()
    if row is None or not row["cooldown_until"]:
        return None
    if _now(now).strftime(_STAMP) >= row["cooldown_until"]:
        return None  # served its time; the next run may ask again
    return (
        f"paused until {row['cooldown_until']} after {row['consecutive_failures']} "
        f"failures in a row — last one: {row['last_error']}"
    )
