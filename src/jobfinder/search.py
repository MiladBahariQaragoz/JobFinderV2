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
from dataclasses import asdict, dataclass, field, replace
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

# The backstop on auto-continue: however many budgets a search would like to
# spend, it gets this many and then stops and says so.
DEFAULT_MAX_LEGS = 6


@dataclass(frozen=True)
class SourceCounts:
    """One source's line in the summary — §10's `Bundesagentur — 42 found, 7 new`."""

    found: int = 0
    new: int = 0
    duplicates: int = 0
    errors: tuple[str, ...] = ()


def _add_counts(earlier: SourceCounts | None, page: SourceCounts) -> SourceCounts:
    if earlier is None:
        return page
    return SourceCounts(
        found=earlier.found + page.found,
        new=earlier.new + page.new,
        duplicates=earlier.duplicates + page.duplicates,
        errors=earlier.errors + page.errors,
    )


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
    # A spent budget is the one interruption it is safe to continue from
    # automatically — her Ctrl-C and a dead host are not.
    budget_exhausted: bool = False
    legs: int = 1  # how many budgets the search needed
    # One entry per source that ran — the per-source summary lines (§10).
    per_source: dict = field(default_factory=dict)


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
    per_source: dict[str, SourceCounts] = {}
    state = "done"
    budget_exhausted = False

    try:
        for adapter in adapters:
            start_query_index, start_page = 0, 1
            if resume:
                cursor = _cursor(connection, adapter.source, query_hash)
                if cursor is not None:
                    start_query_index, start_page = cursor
                    resumed_any = True
            source_found = source_new = source_duplicates = 0
            source_errors: list[str] = []
            try:
                for page in adapter.search_pages(
                    spec, start_query_index=start_query_index, start_page=start_page
                ):
                    outcome_counts = _store_page(connection, adapter, page)
                    found += outcome_counts[0]
                    new += outcome_counts[1]
                    duplicates += outcome_counts[2]
                    source_found += outcome_counts[0]
                    source_new += outcome_counts[1]
                    source_duplicates += outcome_counts[2]
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
                budget_exhausted = isinstance(err, RequestBudgetExhausted)
                reason = str(err) if budget_exhausted else "stopped by user"
                message = f"{adapter.source}: {reason}"
                errors.append(message)
                source_errors.append(message)
                break
            except Exception as err:  # one source down must not lose the others
                state = "interrupted"
                message = f"{adapter.source}: {type(err).__name__}: {err}"
                errors.append(message)
                source_errors.append(message)
            finally:
                per_source[adapter.source] = _add_counts(
                    per_source.get(adapter.source),
                    SourceCounts(
                        found=source_found,
                        new=source_new,
                        duplicates=source_duplicates,
                        errors=tuple(source_errors),
                    ),
                )
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
        budget_exhausted=budget_exhausted,
        per_source=per_source,
    )


def run_search_until_done(
    connection: sqlite3.Connection,
    adapter_factory,
    spec: SearchSpec,
    *,
    resume: bool = False,
    csv_path: Path | None = None,
    max_legs: int = DEFAULT_MAX_LEGS,
    on_leg=None,
    **run_kwargs,
) -> SearchSummary:
    """Run legs until the search is finished, a fresh budget each time.

    `adapter_factory()` builds the adapters for one leg — a new client, so a
    new request budget. Only a spent budget continues automatically: her
    Ctrl-C, a dead host and a leg that stored nothing all end the loop, and
    `max_legs` bounds it whatever happens, so a bug cannot turn the budget
    into "no limit at all".
    """
    combined: SearchSummary | None = None
    for leg in range(1, max_legs + 1):
        summary = run_search(
            connection,
            adapter_factory(),
            spec,
            resume=resume or leg > 1,
            csv_path=csv_path,
            **run_kwargs,
        )
        combined = _merge_legs(combined, summary)
        if on_leg is not None:
            on_leg(leg, summary, combined)
        if not summary.budget_exhausted or summary.found == 0:
            break  # finished, stopped for another reason, or making no progress
    return combined  # type: ignore[return-value]


def _merge_legs(earlier: SearchSummary | None, leg: SearchSummary) -> SearchSummary:
    """One summary for the whole search — counts add up, the last state wins."""
    if earlier is None:
        return replace(leg, legs=1)
    per_source = dict(earlier.per_source)
    for source, counts in leg.per_source.items():
        per_source[source] = _add_counts(per_source.get(source), counts)
    return replace(
        leg,
        found=earlier.found + leg.found,
        new=earlier.new + leg.new,
        duplicates=earlier.duplicates + leg.duplicates,
        errors=earlier.errors + leg.errors,
        resumed=earlier.resumed or leg.resumed,
        legs=earlier.legs + 1,
        per_source=per_source,
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
