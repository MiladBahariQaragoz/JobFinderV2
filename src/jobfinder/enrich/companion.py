"""Enrichment while the search is still running (MASTER_PLAN §9).

A search waits on job-site hosts; enrichment waits on LLM providers. The two
never contend for the same host, so running them one after the other would add
their wall times together for no reason.

There is no queue and no handover between them: the store *is* the queue. This
worker polls for jobs that have a description and no answer at the current
prompt version, which is exactly what a job the search just committed looks
like. An interrupted search therefore leaves a partly enriched but perfectly
consistent database.

§8 rule 2 is the prerequisite: this thread opens its own connection, and every
connection carries `busy_timeout`, so the second writer waits its turn instead
of failing instantly.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING

from jobfinder.enrich.runner import EnrichmentRun, run_enrichment
from jobfinder.store.db import connect, migrate
from jobfinder.store.enrichment import jobs_needing_enrichment
from jobfinder.store.runs import (
    finish_run,
    note_enriched,
    start_enrichment_run,
)

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable

    from jobfinder.config import Settings

# How long to wait before asking the store again when it had nothing. Short
# enough that a job stored now is explained within seconds, long enough that
# the polling itself never competes with the search for the write lock.
POLL_SECONDS = 2.0

# Jobs per batch. Small, because the point is to keep up with a search that is
# still arriving — not to drain a backlog in one go.
BATCH_MULTIPLE = 4


class EnrichmentCompanion:
    """Explains jobs in a background thread while something else stores them."""

    def __init__(
        self,
        db_path: Path,
        pool,
        settings: Settings,
        *,
        cv_digest: str,
        csv_path: Path | None = None,
        on_progress: Callable[[int, int, sqlite3.Row], None] | None = None,
        workers: int = 4,
        poll_seconds: float = POLL_SECONDS,
        prompt_version: str | None = None,
    ):
        self._db_path = Path(db_path)
        self._pool = pool
        self._settings = settings
        self._cv_digest = cv_digest
        self._csv_path = csv_path
        self._on_progress = on_progress
        self._workers = max(1, workers)
        self._poll_seconds = poll_seconds
        self._prompt_version = prompt_version

        self._no_more_jobs = threading.Event()
        self._thread: threading.Thread | None = None
        self._sent = 0
        self._enriched = 0
        self._failed = 0
        self._quota_spent = False
        self._unevidenced = 0
        self._errors: list[str] = []
        # §9: a job that fails is retried on the next run, not on the next
        # poll two seconds from now. One unanswerable ad would otherwise be
        # re-sent for as long as the search lasts.
        self._already_tried: set[str] = set()
        # §10's Cancel button: stops the worker between batches, keeps every
        # answer already saved, and ends the run row `interrupted`.
        self._cancelled = threading.Event()
        self._run_id: int | None = None
        # Answers journalled so far — the run row's `enriched_count`.
        self._journalled = 0

    def start(self) -> None:
        """Begin explaining, now, on an empty store if that is what there is."""
        if self._thread is not None:
            raise RuntimeError("this enrichment worker has already been started")
        # The journal row is written on the caller's thread, so a progress
        # reader sees the run the moment start() returns — not whenever the
        # worker thread happens to reach its first batch.
        journal = connect(self._db_path)
        try:
            migrate(journal)
            self._run_id = start_enrichment_run(journal)
        finally:
            journal.close()
        self._thread = threading.Thread(target=self._work, name="enrichment", daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        """Stop between batches. Answers already saved stay saved (§9)."""
        self._cancelled.set()
        self._no_more_jobs.set()

    def finish(self, timeout: float | None = None) -> EnrichmentRun:
        """Say no more jobs are coming, let it drain, and report what it did."""
        if self._thread is None:
            raise RuntimeError("this enrichment worker was never started")
        self._no_more_jobs.set()
        self._thread.join(timeout)
        self._close_journal()
        return self._summary()

    def _work(self) -> None:
        connection = connect(self._db_path)  # §8 rule 2: one per thread
        try:
            # On a first-ever run this worker reaches the database before the
            # search has created it. `migrate` is idempotent, so claiming the
            # schema here costs nothing and is the difference between enriching
            # and quietly giving up on "no such table: jobs".
            migrate(connection)
            while not self._cancelled.is_set():
                # Read the flag *before* the batch. A job stored between the
                # query and the flag check would otherwise be left unexplained.
                was_told_to_stop = self._no_more_jobs.is_set()
                result = self._one_batch(connection)
                if result is None or result.quota_spent:
                    break
                if result.total == 0:
                    if was_told_to_stop:
                        break  # the store is empty and nothing more is coming
                    self._no_more_jobs.wait(self._poll_seconds)
        finally:
            connection.close()

    def _journal_progress(self, done_in_batch: int, total: int, job) -> None:
        """One answer landed: count it in the journal, then pass it on (§10)."""
        self._journalled += 1
        journal = connect(self._db_path)
        try:
            note_enriched(journal, self._run_id, self._journalled)
        finally:
            journal.close()
        if self._on_progress is not None:
            self._on_progress(self._journalled, total, job)

    def _close_journal(self) -> None:
        """End the run row: done, or interrupted by cancel / spent quota."""
        if self._run_id is None:
            return
        state = "interrupted" if (self._cancelled.is_set() or self._quota_spent) else "done"
        journal = connect(self._db_path)
        try:
            finish_run(journal, self._run_id, state, errors=self._errors)
        finally:
            journal.close()
        self._run_id = None

    def _one_batch(self, connection: sqlite3.Connection) -> EnrichmentRun | None:
        """One pass over what the store holds; None when the run cannot go on."""
        budget_left = self._settings.llm_budget - self._sent
        if budget_left <= 0:
            return None

        try:
            result = run_enrichment(
                connection,
                self._pool,
                self._settings,
                cv_digest=self._cv_digest,
                limit=min(budget_left, self._workers * BATCH_MULTIPLE),
                csv_path=self._csv_path,
                on_progress=self._journal_progress,
                workers=self._workers,
                prompt_version=self._prompt_version,
                skip=self._already_tried,
            )
        except Exception as exc:  # a broken worker must not take the search with it
            self._errors.append(f"enrichment stopped: {exc}")
            return None

        self._sent += result.sent
        self._enriched += result.enriched
        self._failed += result.failed
        self._unevidenced += result.unevidenced_levels
        self._errors.extend(result.errors)
        self._already_tried.update(result.failed_job_ids)
        if result.quota_spent:
            self._quota_spent = True
        return result

    def _summary(self) -> EnrichmentRun:
        connection = connect(self._db_path)
        try:
            migrate(connection)
            remaining = len(
                jobs_needing_enrichment(connection, self._prompt_version or _current_version())
            )
        finally:
            connection.close()
        return EnrichmentRun(
            total=self._sent,
            sent=self._sent,
            enriched=self._enriched,
            failed=self._failed,
            remaining=remaining,
            quota_spent=self._quota_spent,
            unevidenced_levels=self._unevidenced,
            errors=self._errors,
        )


def _current_version() -> str:
    from jobfinder.llm.prompting import load_prompt

    return load_prompt("enrich").version
