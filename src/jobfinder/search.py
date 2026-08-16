"""The search runner — §9's "nothing lives only in memory" for search runs.

Every posting is upserted the moment the runner sees it, every completed page
moves the source cursor, and every outcome (done, interrupted, budget spent,
one source down) is journaled in `runs` as it happens. A resumed run re-enters
at the stored cursor instead of repeating work.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from jobfinder.sources.http import RequestBudgetExhausted
from jobfinder.store.export import export_jobs_init
from jobfinder.store.jobs import upsert_job

if TYPE_CHECKING:
    from jobfinder.search_spec import SearchSpec

# A run row older than this without progress is not running anymore, whatever
# its state column claims (§9 stale-run detection). Generous: the laptop may
# have slept mid-run.
DEFAULT_STALE_AFTER = timedelta(minutes=10)


@dataclass(frozen=True)
class SearchSummary:
    """What one run did — the numbers her summary lines are built from."""

    run_id: int
    state: str  # done | interrupted
    found: int
    new: int
    duplicates: int
    errors: list[str]
    resumed: bool


def run_search(
    connection: sqlite3.Connection,
    adapters,
    spec: SearchSpec,
    *,
    resume: bool = False,
    csv_path: Path | None = None,
    stale_after: timedelta = DEFAULT_STALE_AFTER,
    now: datetime | None = None,
    on_page=None,
) -> SearchSummary:
    """Run every adapter's search, persisting as we go. Never raises adapter errors.

    `on_page(page, found, new, duplicates)` fires after each stored page — the
    UI's chance to narrate progress (§10) from real counts.
    """
    now = now or datetime.now(UTC)
    _close_stale_runs(connection, now, stale_after)

    query_hash = _spec_fingerprint(spec)
    run_id = _start_run(connection, spec, [adapter.source for adapter in adapters])
    resumed_any = False

    found = new = duplicates = 0
    errors: list[str] = []
    state = "done"

    try:
        for adapter in adapters:
            start_query_index, start_page = 0, 1
            if resume:
                cursor = _cursor(connection, adapter.source, query_hash)
                if cursor is not None:
                    start_query_index, start_page = cursor
                    resumed_any = True
            try:
                for page in adapter.search_pages(
                    spec, start_query_index=start_query_index, start_page=start_page
                ):
                    outcome_counts = _store_page(connection, adapter, page)
                    found += outcome_counts[0]
                    new += outcome_counts[1]
                    duplicates += outcome_counts[2]
                    _save_cursor(
                        connection, adapter.source, query_hash, page.query_index, page.page
                    )
                    _progress(
                        connection, run_id, found=found, new=new, duplicates=duplicates, now=now
                    )
                    if on_page is not None:
                        on_page(page, found, new, duplicates)
            except (KeyboardInterrupt, RequestBudgetExhausted) as err:
                # Her stop or the politeness limit: halt the whole run here.
                state = "interrupted"
                reason = "stopped by user" if isinstance(err, KeyboardInterrupt) else str(err)
                errors.append(f"{adapter.source}: {reason}")
                break
            except Exception as err:  # one source down must not lose the others
                state = "interrupted"
                errors.append(f"{adapter.source}: {type(err).__name__}: {err}")
    finally:
        _finish_run(connection, run_id, state, found, new, duplicates, errors, now=now)
        if csv_path is not None:
            export_jobs_init(connection, csv_path)  # what landed is readable now

    return SearchSummary(
        run_id=run_id,
        state=state,
        found=found,
        new=new,
        duplicates=duplicates,
        errors=errors,
        resumed=resumed_any,
    )


def _store_page(connection: sqlite3.Connection, adapter, page) -> tuple[int, int, int]:
    """Upsert one page's postings — each in its own committed transaction."""
    found = new = duplicates = 0
    fetch_detail = getattr(adapter, "fetch_detail", None)
    for posting in page.postings:
        if posting.description is None and fetch_detail is not None:
            posting = fetch_detail(posting)
        outcome = upsert_job(connection, posting)
        found += 1
        if outcome == "new":
            new += 1
        else:
            duplicates += 1
    return found, new, duplicates


# -- run journal ---------------------------------------------------------------


def _start_run(connection: sqlite3.Connection, spec: SearchSpec, sources: list[str]) -> int:
    payload = {
        "mode": spec.mode,
        "employment_types": list(spec.employment_types),
        "cities": [city.name for city in spec.cities],
        "keywords": list(spec.keywords),
    }
    cursor = connection.execute(
        "INSERT INTO runs (kind, spec, sources, state, started_at, last_progress_at)"
        " VALUES ('search', ?, ?, 'running', ?, ?)",
        (
            json.dumps(payload, ensure_ascii=False),
            ",".join(sources),
            _stamp(datetime.now(UTC)),
            _stamp(datetime.now(UTC)),
        ),
    )
    connection.commit()
    return int(cursor.lastrowid)


def _progress(
    connection: sqlite3.Connection,
    run_id: int,
    *,
    found: int,
    new: int,
    duplicates: int,
    now: datetime,
) -> None:
    connection.execute(
        "UPDATE runs SET last_progress_at = ?, found_count = ?, new_count = ?, duplicate_count = ?"
        " WHERE id = ?",
        (_stamp(now), found, new, duplicates, run_id),
    )
    connection.commit()


def _finish_run(
    connection: sqlite3.Connection,
    run_id: int,
    state: str,
    found: int,
    new: int,
    duplicates: int,
    errors: list[str],
    *,
    now: datetime,
) -> None:
    connection.execute(
        "UPDATE runs SET state = ?, finished_at = ?, found_count = ?, new_count = ?,"
        " duplicate_count = ?, errors = ? WHERE id = ?",
        (
            state,
            _stamp(now),
            found,
            new,
            duplicates,
            json.dumps(errors, ensure_ascii=False),
            run_id,
        ),
    )
    connection.commit()


def _close_stale_runs(
    connection: sqlite3.Connection, now: datetime, stale_after: timedelta
) -> None:
    """A `running` row older than the heartbeat is a crashed run — say so."""
    cutoff = _stamp(now - stale_after)
    connection.execute(
        "UPDATE runs SET state = 'interrupted', finished_at = ?"
        " WHERE state = 'running' AND (last_progress_at IS NULL OR last_progress_at < ?)",
        (_stamp(now), cutoff),
    )
    connection.commit()


# -- per-source cursor ---------------------------------------------------------


def _save_cursor(
    connection: sqlite3.Connection,
    source: str,
    query_hash: str,
    query_index: int,
    page: int,
) -> None:
    connection.execute(
        "INSERT INTO source_state (source, query_hash, last_query_index, last_completed_page,"
        " last_success_at) VALUES (?, ?, ?, ?, ?)"
        " ON CONFLICT(source) DO UPDATE SET query_hash = excluded.query_hash,"
        " last_query_index = excluded.last_query_index,"
        " last_completed_page = excluded.last_completed_page,"
        " last_success_at = excluded.last_success_at",
        (source, query_hash, query_index, page, _stamp(datetime.now(UTC))),
    )
    connection.commit()


def _cursor(connection: sqlite3.Connection, source: str, query_hash: str) -> tuple[int, int] | None:
    """The re-entry point — but only when the stored cursor is for this spec."""
    row = connection.execute(
        "SELECT last_query_index, last_completed_page FROM source_state"
        " WHERE source = ? AND query_hash = ?",
        (source, query_hash),
    ).fetchone()
    if row is None or row[1] == 0:
        return None
    return int(row[0]), int(row[1]) + 1  # continue after the last completed page


def _spec_fingerprint(spec: SearchSpec) -> str:
    canonical = json.dumps(asdict(spec), sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(canonical.encode()).hexdigest()


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M:%S")
