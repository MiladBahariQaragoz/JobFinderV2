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
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from jobfinder.sources.http import RequestBudgetExhausted
from jobfinder.store.db import connect
from jobfinder.store.export import export_jobs_init
from jobfinder.store.health import cooling_off, record_failure, record_success
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


@dataclass
class _RunState:
    """What the sources are jointly building, guarded by one lock."""

    run_id: int
    query_hash: str
    now: datetime  # when the run started — fixed, and only ever the start
    resume: bool
    # Every journal write asks the clock again. Freezing one stamp for the
    # whole run made `last_progress_at` stand still, which tells §9's stale
    # rule that a healthy long search has been abandoned.
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    on_page: object = None
    found: int = 0
    new: int = 0
    duplicates: int = 0
    errors: list[str] = field(default_factory=list)
    per_source: dict = field(default_factory=dict)
    resumed_any: bool = False
    state: str = "done"
    budget_exhausted: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)
    # Set by her Ctrl-C or a spent budget: the other sources stop between pages.
    # An event handed in from outside (§10's Cancel button) is the same flag —
    # whoever sets it, the run stops between pages and keeps what it stored.
    stop: threading.Event = field(default_factory=threading.Event)


def _run_one_source(connection: sqlite3.Connection, adapter, spec: SearchSpec, run: _RunState):
    """One adapter's whole search, against one connection. Never raises."""
    # §8 rule 7: a source that failed three runs running sits this one out
    # rather than spending it on timeouts.
    if (paused := cooling_off(connection, adapter.source, now=run.now)) is not None:
        with run.lock:
            run.per_source[adapter.source] = _add_counts(
                run.per_source.get(adapter.source), SourceCounts(errors=(paused,))
            )
            run.errors.append(f"{adapter.source}: {paused}")
        return

    start_query_index, start_page = 0, 1
    if run.resume:
        cursor = _cursor(connection, adapter.source, run.query_hash)
        if cursor is not None:
            start_query_index, start_page = cursor
            with run.lock:
                run.resumed_any = True

    source_found = source_new = source_duplicates = 0
    source_errors: list[str] = []
    try:
        for page in adapter.search_pages(
            spec, start_query_index=start_query_index, start_page=start_page
        ):
            if run.stop.is_set():
                break  # another source hit her Ctrl-C or spent the budget
            counts = _store_page(connection, adapter, page)
            source_found += counts[0]
            source_new += counts[1]
            source_duplicates += counts[2]
            _save_cursor(connection, adapter.source, run.query_hash, page.query_index, page.page)
            record_success(connection, adapter.source, now=run.now)  # it answers
            _upsert_source_progress(
                connection,
                run.run_id,
                adapter.source,
                found=source_found,
                new=source_new,
                duplicates=source_duplicates,
                state="running",
                now=run.clock(),
            )
            with run.lock:
                run.found += counts[0]
                run.new += counts[1]
                run.duplicates += counts[2]
                totals = SourceCounts(found=run.found, new=run.new, duplicates=run.duplicates)
                _progress(
                    connection,
                    run.run_id,
                    found=run.found,
                    new=run.new,
                    duplicates=run.duplicates,
                    now=run.clock(),
                )
                if run.on_page is not None:
                    run.on_page(page, SourceCounts(*counts), totals)
    except (KeyboardInterrupt, RequestBudgetExhausted) as err:
        # Her stop or the politeness limit: halt the whole run, every source.
        budget = isinstance(err, RequestBudgetExhausted)
        message = f"{adapter.source}: {str(err) if budget else 'stopped by user'}"
        source_errors.append(message)
        with run.lock:
            run.state = "interrupted"
            run.budget_exhausted = run.budget_exhausted or budget
            run.errors.append(message)
        run.stop.set()
    except Exception as err:  # one source down must not lose the others
        message = f"{adapter.source}: {type(err).__name__}: {err}"
        source_errors.append(message)
        record_failure(connection, adapter.source, reason=str(err), now=run.now)
        with run.lock:
            run.state = "interrupted"
            run.errors.append(message)
    finally:
        with run.lock:
            run.per_source[adapter.source] = _add_counts(
                run.per_source.get(adapter.source),
                SourceCounts(
                    found=source_found,
                    new=source_new,
                    duplicates=source_duplicates,
                    errors=tuple(source_errors),
                ),
            )
        _upsert_source_progress(
            connection,
            run.run_id,
            adapter.source,
            found=source_found,
            new=source_new,
            duplicates=source_duplicates,
            state="failed" if source_errors else "done",
            now=run.clock(),
        )


def run_search(
    connection: sqlite3.Connection,
    adapters,
    spec: SearchSpec,
    *,
    resume: bool = False,
    csv_path: Path | None = None,
    stale_after: timedelta = DEFAULT_STALE_AFTER,
    now: datetime | None = None,
    clock: Callable[[], datetime] | None = None,
    on_page=None,
    db_path: Path | None = None,
    stop_event: threading.Event | None = None,
) -> SearchSummary:
    """Run every adapter's search, persisting as we go. Never raises adapter errors.

    `on_page(page, counts, totals)` fires after each stored page with that
    page's own `SourceCounts` and the run's running ones — the UI's chance to
    narrate progress (§10) from real counts.

    `stop_event` is §10's Cancel button: an event the UI thread sets while the
    sources are still fetching. The run stops between pages, keeps everything
    stored, and ends `interrupted` so the resume banner appears. An event set
    after the sources have finished changes nothing.

    Given `db_path`, the sources run **at the same time**, one thread and one
    connection each (§8 rule 2): the throttle is shared per host, so no host is
    fetched twice at once, and four scrapers on four hosts cost the slowest one
    rather than the sum. Without it they run in order on the caller's
    connection, which is what a single source or a test wants.
    """
    tick = clock or (lambda: datetime.now(UTC))
    now = now or tick()
    _close_stale_runs(connection, now, stale_after)

    adapters = list(adapters)
    run = _RunState(
        run_id=_start_run(connection, spec, [adapter.source for adapter in adapters], now=now),
        query_hash=_spec_fingerprint(spec),
        now=now,
        clock=tick,
        resume=resume,
        on_page=on_page,
        stop=stop_event or threading.Event(),
    )

    try:
        if db_path is not None and len(adapters) > 1:
            _run_in_parallel(adapters, spec, run, db_path)
        else:
            for adapter in adapters:
                _run_one_source(connection, adapter, spec, run)
                if run.stop.is_set():
                    break
        # A stop set from outside the run (the Cancel button) is the one
        # interruption that arrives without touching `run.state` — the runner
        # was busy between pages when it happened. It must not quietly end as
        # 'done', or the resume banner never appears.
        if run.stop.is_set() and run.state == "done":
            run.state = "interrupted"
    finally:
        _finish_run(
            connection,
            run.run_id,
            run.state,
            run.found,
            run.new,
            run.duplicates,
            run.errors,
            now=run.clock(),
        )
        if csv_path is not None:
            export_jobs_init(connection, csv_path)  # what landed is readable now

    return SearchSummary(
        run_id=run.run_id,
        state=run.state,
        found=run.found,
        new=run.new,
        duplicates=run.duplicates,
        errors=run.errors,
        resumed=run.resumed_any,
        budget_exhausted=run.budget_exhausted,
        per_source=run.per_source,
    )


def _run_in_parallel(adapters, spec: SearchSpec, run: _RunState, db_path: Path) -> None:
    """One worker per source, each with its own connection — never a shared one."""
    from concurrent.futures import ThreadPoolExecutor

    def work(adapter):
        worker_connection = connect(db_path)  # §8 rule 2: one per thread
        try:
            _run_one_source(worker_connection, adapter, spec, run)
        finally:
            worker_connection.close()

    with ThreadPoolExecutor(max_workers=len(adapters)) as pool:
        for future in [pool.submit(work, adapter) for adapter in adapters]:
            future.result()  # re-raises anything _run_one_source failed to catch


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


def _is_known(connection: sqlite3.Connection, job_id: str) -> bool:
    row = connection.execute("SELECT 1 FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
    return row is not None


def _store_page(connection: sqlite3.Connection, adapter, page) -> tuple[int, int, int]:
    """Upsert one page's postings — each in its own committed transaction."""
    found = new = duplicates = 0
    fetch_detail = getattr(adapter, "fetch_detail", None)
    for posting in page.postings:
        # A detail fetch is a request at §8 pacing and the dominant cost of a
        # run. For a job already stored the answer is thrown away anyway: the
        # re-run rule moves `last_seen_at` and touches nothing else.
        if (
            posting.description is None
            and fetch_detail is not None
            and not _is_known(connection, posting.job_id)
        ):
            posting = fetch_detail(posting)
        outcome = upsert_job(connection, posting)
        found += 1
        if outcome == "new":
            new += 1
        else:
            duplicates += 1
    return found, new, duplicates


# -- run journal ---------------------------------------------------------------


def _upsert_source_progress(
    connection: sqlite3.Connection,
    run_id: int,
    source: str,
    *,
    found: int,
    new: int,
    duplicates: int,
    state: str,
    now: datetime,
) -> None:
    """One source's line in the journal, as of the page just stored.

    Written per page (§9: progress lives on disk, not in a process's memory)
    so the web app's progress panel is a SELECT, and a browser reload mid-run
    shows the same numbers the run is producing.
    """
    connection.execute(
        "INSERT INTO run_sources"
        " (run_id, source, found_count, new_count, duplicate_count, state, last_event_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(run_id, source) DO UPDATE SET"
        " found_count = excluded.found_count,"
        " new_count = excluded.new_count,"
        " duplicate_count = excluded.duplicate_count,"
        " state = excluded.state,"
        " last_event_at = excluded.last_event_at",
        (run_id, source, found, new, duplicates, state, _stamp(now)),
    )
    connection.commit()


def _start_run(
    connection: sqlite3.Connection, spec: SearchSpec, sources: list[str], *, now: datetime
) -> int:
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
            _stamp(now),
            _stamp(now),
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
