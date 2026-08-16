"""Starting, watching and stopping runs — from the browser (§10).

The web app does not own a search; it owns a *thread* that runs the same
`run_search_until_done` the CLI runs, against the same adapters, with one
addition: a `stop_event` the Cancel button sets. Everything the panel shows
comes from the `runs` journal, so the browser can close, reload, reopen —
the progress is in the database, not in this process's memory.

Enrichment-from-the-browser is gated here rather than in the route: a
missing key or an unreadable CV refuses the *explanations*, never the
search, and the refusal is a sentence with a link (§10).
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable

    from jobfinder.config import Settings
    from jobfinder.search_spec import SearchSpec


class StartRefused(Exception):
    """A run that cannot start, and the one sentence + link that say why."""

    def __init__(self, sentence: str, link: str = "/"):
        super().__init__(sentence)
        self.sentence = sentence
        self.link = link


def _comma_list(raw: str | None) -> list[str]:
    return [part.strip() for part in (raw or "").split(",") if part.strip()]


class RunManager:
    """One search at a time, in a daemon thread, journalled by the runner."""

    def __init__(
        self,
        settings: Settings,
        *,
        adapter_factory: Callable | None = None,
        companion_factory: Callable | None = None,
        runner: Callable | None = None,
    ):
        self._settings = settings
        # `adapter_factory()` builds one leg's adapters, exactly as the CLI's
        # does — tests hand in a fake source, production builds the registry.
        self._adapter_factory = adapter_factory or production_adapter_factory(settings)
        self._companion_factory = companion_factory
        self._runner = runner
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._companion = None
        self._failure: str | None = None
        self._lock = threading.Lock()

    # -- the panel's questions -------------------------------------------------

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def failure(self) -> str | None:
        """Why the last run died early, in her words — or None."""
        with self._lock:
            return self._failure

    # -- her buttons -----------------------------------------------------------

    def start(
        self,
        *,
        resume: bool = False,
        enrich: bool = False,
        cities: str | None = None,
        types: str | None = None,
        keywords: str | None = None,
    ) -> None:
        if self.is_running():
            raise StartRefused(
                "A search is already running — watch it below, or cancel it first.", link="/"
            )

        spec = self._build_spec(cities, types, keywords)

        companion = None
        if enrich:
            factory = self._companion_factory or production_companion_factory(self._settings)
            companion = factory()  # may refuse: no key, no readable CV

        with self._lock:
            self._failure = None
        self._cancel = threading.Event()
        self._companion = companion
        self._thread = threading.Thread(
            target=self._work, args=(spec, resume, companion), daemon=True, name="search-run"
        )
        self._thread.start()

    def cancel(self) -> None:
        """Stop between pages. Everything already stored is kept (§9)."""
        self._cancel.set()
        if self._companion is not None:
            self._companion.cancel()

    def wait(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    # -- the machinery ----------------------------------------------------------

    def _build_spec(
        self, cities: str | None, types: str | None, keywords: str | None
    ) -> SearchSpec:
        from jobfinder.cli import DEFAULT_CITIES, DEFAULT_TYPES
        from jobfinder.search_spec import SearchSpec, SearchSpecError

        try:
            return SearchSpec.build(
                mode="general",
                employment_types=_comma_list(types) or list(DEFAULT_TYPES),
                city_names=_comma_list(cities) or list(DEFAULT_CITIES),
                keywords=_comma_list(keywords),
            )
        except (SearchSpecError, ValueError) as exc:
            raise StartRefused(str(exc), link="/") from exc

    def _work(self, spec: SearchSpec, resume: bool, companion) -> None:
        settings = self._settings
        connection: sqlite3.Connection
        try:
            from jobfinder.search import run_search_until_done
            from jobfinder.store.db import connect, migrate

            runner = self._runner or run_search_until_done
            connection = connect(settings.db_path)
            try:
                migrate(connection)
                if companion is not None:
                    companion.start()
                runner(
                    connection,
                    self._adapter_factory,
                    spec,
                    resume=resume,
                    stop_event=self._cancel,
                    csv_path=settings.jobs_init_csv,
                    max_legs=settings.max_search_legs,
                    db_path=settings.db_path,
                )
            finally:
                connection.close()
        except Exception as exc:  # the panel must have a sentence, not a traceback
            with self._lock:
                self._failure = (
                    f"The search stopped unexpectedly ({type(exc).__name__}). "
                    "Everything it stored is safe — try again, or run it from a terminal."
                )
        finally:
            if companion is not None:
                try:
                    companion.finish()
                except Exception:
                    pass  # the companion journals its own outcome


def production_adapter_factory(settings: Settings):
    """The real sources, built per leg exactly as the CLI builds them."""

    def factory():
        from jobfinder.sources.http import PoliteClient
        from jobfinder.sources.registry import build_adapters

        def client_factory(_settings, delay_seconds: float) -> PoliteClient:
            return PoliteClient(
                cache_dir=settings.data_dir / "http-cache",
                budget=settings.request_budget,
                min_delay=delay_seconds,
            )

        return build_adapters(settings, client_factory).adapters

    return factory


def production_companion_factory(settings: Settings):
    """The enrichment worker for `explain while searching` — or a refusal."""

    def factory():
        from jobfinder.enrich.companion import EnrichmentCompanion
        from jobfinder.llm.pool import LLMConfigError, build_pool
        from jobfinder.llm.schema import enrichment_answer_validator
        from jobfinder.profile import ProfileError, load_profile
        from jobfinder.roles import build_cv_digest

        try:
            resume = load_profile(settings.pool_path)
        except ProfileError as exc:
            raise StartRefused(
                f"The search can run, but jobs will not be explained: {exc}",
                link="/settings",
            ) from exc

        try:
            pool = build_pool(settings, enrichment_answer_validator)
        except LLMConfigError as exc:
            raise StartRefused(
                "No LLM API key yet. The search runs fine — to also explain jobs in "
                "English as they arrive, add a free key in Settings.",
                link="/settings",
            ) from exc

        return EnrichmentCompanion(
            settings.db_path,
            pool,
            settings,
            cv_digest=build_cv_digest(resume),
            csv_path=settings.jobs_enriched_csv,
            workers=settings.llm_workers,
        )

    return factory


def elapsed_seconds(started_at: str | None) -> int | None:
    """Whole seconds since a run started, for the panel's clock."""
    if not started_at:
        return None
    try:
        started = datetime.strptime(started_at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    except ValueError:
        return None
    return max(0, int((datetime.now(UTC) - started).total_seconds()))
