"""The enrichment batch: German ads in, English answers saved as they land.

Two rules shape everything here.

§9 — nothing lives only in memory. Each answer is committed to SQLite and
appended to `jobs-enriched.csv` inside `on_result`, before the next job is
sent. A dropped connection or a spent quota costs nothing already done.

§10 — nothing looks frozen. `on_progress` fires per answer with real counts
read from the store, not a spinner.

Her free-tier quota is the scarce resource, so the batch runs in chunks and
stops the moment the pool says it has nothing left, rather than re-asking a
dead pool once per remaining job.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from llmpool import PoolExhausted, run_batch

from jobfinder.enrich.fields import enriched_row
from jobfinder.llm.cache import LLMCache, cache_key, fingerprint
from jobfinder.llm.prompting import load_prompt, render_enrichment_prompt
from jobfinder.llm.schema import ENRICHMENT_SPEC, enrichment_answer_validator
from jobfinder.store.enrichment import jobs_needing_enrichment, save_enrichment
from jobfinder.store.export import append_enriched_row

if TYPE_CHECKING:
    from collections.abc import Callable

    from jobfinder.config import Settings

# How many jobs go into one `run_batch` call. Small enough that a spent quota
# is noticed within seconds rather than after every remaining job has been
# tried; large enough that the workers stay busy.
CHUNK_MULTIPLE = 3


@dataclass(frozen=True)
class EnrichmentRun:
    """What one run did, in the numbers her summary is written from."""

    total: int = 0  # jobs that needed explaining when the run started
    sent: int = 0  # jobs actually offered to the pool (after limit and budget)
    enriched: int = 0
    failed: int = 0
    remaining: int = 0  # still unexplained when the run ended
    quota_spent: bool = False
    errors: list[str] = field(default_factory=list)


def run_enrichment(
    connection: sqlite3.Connection,
    pool,
    settings: Settings,
    *,
    cv_digest: str,
    limit: int | None = None,
    force: bool = False,
    csv_path: Path | None = None,
    on_progress: Callable[[int, int, sqlite3.Row], None] | None = None,
    workers: int = 4,
    prompt_version: str | None = None,
) -> EnrichmentRun:
    """Explain every job that still needs it, saving each answer as it lands."""
    spec = load_prompt("enrich")
    version = prompt_version or spec.version

    pending = jobs_needing_enrichment(connection, version, force=force)
    total = len(pending)
    if not pending:
        return EnrichmentRun(total=0, remaining=0)

    # Her quota is the budget that matters: `llm_budget` bounds any run, and an
    # explicit --limit may bound it further.
    allowance = settings.llm_budget if limit is None else min(limit, settings.llm_budget)
    queue = pending[:allowance]

    prompts = {
        job["job_id"]: render_enrichment_prompt(
            spec.text,
            job=job,
            description=job["description"],
            cv_digest=cv_digest,
        )
        for job in queue
    }

    enriched = failed = 0
    errors: list[str] = []
    quota_spent = False

    def remember(result, _done: int, _total: int) -> None:
        """Persist one answer the instant it lands (§9), then narrate it (§10)."""
        nonlocal enriched, failed
        job = result.item
        if result.error is not None:
            failed += 1
            errors.append(f"{job['job_id']}: {result.error}")
            return

        ok, reason = enrichment_answer_validator(result.answer)
        if not ok:
            # The pool validates too; this is the database's own guard, and it
            # is what catches an answer that came back from the cache.
            failed += 1
            errors.append(f"{job['job_id']}: unusable answer ({reason})")
            return

        enriched_at = save_enrichment(
            connection,
            job["job_id"],
            version,
            job["content_hash"],
            result.answer,
            provider_used=answering.provider_for(prompts[job["job_id"]]),
        )
        if csv_path is not None:
            append_enriched_row(
                csv_path,
                enriched_row(
                    result.answer,
                    job_id=job["job_id"],
                    prompt_version=version,
                    provider_used=answering.provider_for(prompts[job["job_id"]]),
                    enriched_at=enriched_at,
                ),
            )
        enriched += 1
        if on_progress is not None:
            on_progress(enriched, min(total, len(queue)), job)

    spec_fingerprint = fingerprint({name: asdict(rule) for name, rule in ENRICHMENT_SPEC.items()})
    chunk_size = max(1, workers) * CHUNK_MULTIPLE

    with LLMCache(settings.llm_cache_path) as cache:
        # --force means "ask again": it has to reach past the answer cache as
        # well as past the stored row, or it would re-save yesterday's answer.
        answering = _AnsweringPool(pool, cache, version, spec_fingerprint, read_cache=not force)
        for start in range(0, len(queue), chunk_size):
            chunk = queue[start : start + chunk_size]
            results = run_batch(
                answering,
                chunk,
                lambda job: prompts[job["job_id"]],
                workers=workers,
                on_result=remember,
            )
            if any(isinstance(result.error, PoolExhausted) for result in results):
                # Nothing is left to ask. Asking the rest would spend the run's
                # deadline waiting on providers that already said no.
                quota_spent = True
                break

    return EnrichmentRun(
        total=total,
        sent=len(queue),
        enriched=enriched,
        failed=failed,
        remaining=len(jobs_needing_enrichment(connection, version)),
        quota_spent=quota_spent,
        errors=errors,
    )


class _AnsweringPool:
    """The pool as `run_batch` sees it: cache first, provider second.

    The key is the whole prompt, not the ad text: 60 of her 674 stored
    postings are identical to another one down to the title and company, and
    those are free. Two shops running the same boilerplate are not — keying on
    the text alone would put one company's answer under the other's name.

    The wrapper also notes which provider answered: llmpool has no per-call
    attribution, so it is inferred from the stats it does keep, and only when
    exactly one provider's success count moved. Anything less certain is
    recorded as unknown rather than guessed.
    """

    def __init__(
        self,
        pool,
        cache: LLMCache,
        prompt_version: str,
        spec_fingerprint: str,
        *,
        read_cache: bool = True,
    ):
        self._pool = pool
        self._cache = cache
        self._version = prompt_version
        self._spec_fingerprint = spec_fingerprint
        self._read_cache = read_cache
        self._lock = threading.Lock()
        self._providers: dict[str, str] = {}

    def complete_json(self, prompt: str) -> dict[str, Any]:
        key = cache_key(
            self._version,
            hashlib.sha1(prompt.encode("utf-8")).hexdigest(),
            self._spec_fingerprint,
        )
        if self._read_cache:
            cached = self._cache.get(key)
            if cached is not None:
                return cached

        before = self._successes()
        answer = self._pool.complete_json(prompt)
        provider = self._who_answered(before)

        self._cache.put(key, answer)
        if provider:
            with self._lock:
                self._providers[prompt] = provider
        return answer

    def provider_for(self, prompt: str) -> str:
        """Who answered this prompt, or "" when it cannot be said honestly."""
        with self._lock:
            return self._providers.get(prompt, "")

    def _successes(self) -> dict[str, int]:
        stats = getattr(self._pool, "stats", None)
        if stats is None:  # a fake, or a pool that does not keep them
            return {}
        return {name: int(values.get("ok", 0)) for name, values in stats().items()}

    def _who_answered(self, before: dict[str, int]) -> str:
        """The one provider whose success count rose by exactly one, if any.

        Under concurrency two calls can land together and neither can be
        attributed. That is reported as unknown; it is never guessed.
        """
        if not before:
            return ""
        moved = [
            name for name, count in self._successes().items() if count - before.get(name, 0) == 1
        ]
        return moved[0] if len(moved) == 1 else ""
