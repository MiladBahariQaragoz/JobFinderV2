"""Reading and writing the run journal from outside a search.

The search runner journals its own runs as it goes (see `search.py`); this
module is the door everyone *else* uses — the enrichment companion writing
its line, and the web app reading progress, interrupted runs and their
per-source counts. Progress read from the database (§10) starts here.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta

# The same heartbeat the search runner uses: a `running` row whose progress
# stamp is older than this is displayed as interrupted, whatever its state
# column says — the app must never claim to be doing something it is not.
STALE_AFTER = timedelta(minutes=10)


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


def start_enrichment_run(connection: sqlite3.Connection, *, spec: str = "") -> int:
    """Insert a `running` row for an enrichment run; returns its id."""
    cursor = connection.execute(
        "INSERT INTO runs (kind, spec, state, started_at, last_progress_at)"
        " VALUES ('enrich', ?, 'running', ?, ?)",
        (spec, _utc_now(), _utc_now()),
    )
    connection.commit()
    return int(cursor.lastrowid)


def note_enriched(connection: sqlite3.Connection, run_id: int, enriched_count: int) -> None:
    """One answer landed — move the count and the heartbeat."""
    connection.execute(
        "UPDATE runs SET enriched_count = ?, last_progress_at = ? WHERE id = ?",
        (enriched_count, _utc_now(), run_id),
    )
    connection.commit()


def finish_run(
    connection: sqlite3.Connection,
    run_id: int,
    state: str,
    *,
    errors: list[str] | None = None,
) -> None:
    """End a run row: `done` or `interrupted`, with whatever it recorded."""
    connection.execute(
        "UPDATE runs SET state = ?, finished_at = ?, errors = ? WHERE id = ?",
        (state, _utc_now(), json.dumps(errors or [], ensure_ascii=False), run_id),
    )
    connection.commit()


def latest_run(connection: sqlite3.Connection, kind: str | None = None) -> sqlite3.Row | None:
    """The newest run row, optionally of one kind."""
    if kind is None:
        return connection.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    return connection.execute(
        "SELECT * FROM runs WHERE kind = ? ORDER BY id DESC LIMIT 1", (kind,)
    ).fetchone()


def run_sources(connection: sqlite3.Connection, run_id: int) -> list[sqlite3.Row]:
    """The per-source lines of one search run, in plain search order."""
    return connection.execute(
        "SELECT rs.* FROM run_sources rs WHERE rs.run_id = ?", (run_id,)
    ).fetchall()


def display_state(row: sqlite3.Row, *, now: datetime | None = None) -> str:
    """A run's state as it should be shown: a silent `running` row is not running.

    A process that died between pages leaves `state = 'running'` behind. The
    search runner closes such rows on its next start; a reader that arrives
    first shows the truth instead — interrupted, counts kept.
    """
    if row["state"] != "running":
        return row["state"]
    now = now or datetime.now(UTC)
    last = row["last_progress_at"] or row["started_at"]
    try:
        seen = datetime.strptime(last, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    except ValueError:
        return "interrupted"
    return "running" if now - seen < STALE_AFTER else "interrupted"


def interrupted_run(connection: sqlite3.Connection) -> sqlite3.Row | None:
    """The newest search run worth offering Resume for, or None.

    A run is worth resuming when it is (or displays as) interrupted and it
    found anything — a run that stored nothing has nothing to continue from,
    and offering a button for it is noise.
    """
    rows = connection.execute(
        "SELECT * FROM runs WHERE kind = 'search' ORDER BY id DESC LIMIT 20"
    ).fetchall()
    for row in rows:
        if display_state(row) == "interrupted" and row["found_count"] > 0:
            return row
        if display_state(row) == "running":
            return None  # a live run is already going; no banner over it
        if row["state"] == "done":
            return None  # the newest finished search closed the chapter
    return None
