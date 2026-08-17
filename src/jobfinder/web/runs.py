"""Starting, watching and stopping runs — from the browser (§10).

The web app does not own a search; it owns a *thread* that runs the same
`run_search_until_done` the CLI runs, against the same adapters, with one
addition: a `stop_event` the Cancel button sets. Everything the panel shows
comes from the `runs` journal, so the browser can close, reload, reopen —
the progress is in the database, not in this process's memory.

Enrichment-from-the-browser is gated here rather than in the route: a
missing key or an unreadable CV refuses the *explanations*, never the
search, and the refusal is a sentence with a link (§10).

**A search and an enrichment pass are two independent runs, on two threads.**
§9's reason is that they wait on different things — job-site hosts and LLM
providers — so neither may be refused or cancelled because of the other. One
manager owns both handles rather than two managers owning one each, because
`search --enrich` still needs the search's own companion, which is a third
case: enrichment attached to a search, cancelled with it.
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


def _her_languages(settings: Settings) -> tuple[str, ...]:
    """The languages on her CV, for the call-list's cuisine nudge. Empty when
    there is no CV — a missing CV must never stop the list being built."""
    try:
        from jobfinder.profile import load_profile

        resume = load_profile(settings.pool_path)
    except Exception:
        return ()
    return tuple(language.name.strip().lower() for language in resume.languages)


class RunManager:
    """One search at a time, in a daemon thread, journalled by the runner."""

    def __init__(
        self,
        settings: Settings,
        *,
        adapter_factory: Callable | None = None,
        companion_factory: Callable | None = None,
        runner: Callable | None = None,
        contacts_runner: Callable | None = None,
        contacts_source_factory: Callable | None = None,
    ):
        self._settings = settings
        self._contacts_runner = contacts_runner
        self._contacts_source_factory = contacts_source_factory
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
        # The standalone enrichment pass: its own thread, its own companion,
        # its own failure sentence. Nothing here is shared with the search.
        self._enrich_thread: threading.Thread | None = None
        self._enrich_companion = None
        self._enrich_failure: str | None = None
        self._enrich_stopping = False
        # The call-list run: a third independent slot, for the same reason as the
        # second. Overpass and the job boards are different hosts and different
        # waits, so building the call-list must not be refused by a search.
        self._contacts_thread: threading.Thread | None = None
        self._contacts_cancel = threading.Event()
        self._contacts_failure: str | None = None

    # -- the panel's questions -------------------------------------------------

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def is_enriching(self) -> bool:
        return self._enrich_thread is not None and self._enrich_thread.is_alive()

    def enrich_is_stopping(self) -> bool:
        """Cancel has been pressed and the jobs already sent are still landing.

        Measured on her real store: a pass stops *between batches*, so Cancel
        took 90 seconds to take effect while the panel went on saying
        "Explaining jobs in English". §10's rule against a screen that hides
        work applies just as much to hiding that stopping is under way.
        """
        return self._enrich_stopping and self.is_enriching()

    def failure(self) -> str | None:
        """Why the last run died early, in her words — or None."""
        with self._lock:
            return self._failure

    def enrich_failure(self) -> str | None:
        """Why the last enrichment pass died early, in her words — or None."""
        with self._lock:
            return self._enrich_failure

    def is_finding_contacts(self) -> bool:
        return self._contacts_thread is not None and self._contacts_thread.is_alive()

    def contacts_failure(self) -> str | None:
        """Why the last call-list run died early, in her words — or None."""
        with self._lock:
            return self._contacts_failure

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
            # No limit: a companion beside a search has to keep up with what
            # arrives, and the search's own budget already bounds the run.
            companion = factory(limit=None)  # may refuse: no key, no readable CV

        with self._lock:
            self._failure = None
        self._cancel = threading.Event()
        self._companion = companion
        self._thread = threading.Thread(
            target=self._work, args=(spec, resume, companion), daemon=True, name="search-run"
        )
        self._thread.start()

    def start_enrich(self, *, limit: int | None = None) -> None:
        """Explain jobs already in the store — no search involved (§9).

        The store is the queue, so this needs no handover from a search and
        can run beside one. `limit` caps the LLM calls the pass will make,
        which is what lets the button promise a cost before spending it.
        """
        if self.is_enriching():
            raise StartRefused(
                "Jobs are already being explained — watch it below, or cancel it first.",
                link="/enrich",
            )

        factory = self._companion_factory or production_companion_factory(self._settings)
        companion = factory(limit=limit)  # may refuse: no key, no readable CV

        with self._lock:
            self._enrich_failure = None
        self._enrich_stopping = False
        self._enrich_companion = companion
        self._enrich_thread = threading.Thread(
            target=self._enrich_work, args=(companion,), daemon=True, name="enrich-run"
        )
        self._enrich_thread.start()

    def start_contacts(self, *, cities: str | None = None, radius_km: int | None = None) -> None:
        """Build the call-list from the browser (Phase 9).

        Overpass answers slowly and unevenly — a city can take minutes — so this
        is a thread and a journal row like every other run, not a request she
        waits on.
        """
        if self.is_finding_contacts():
            raise StartRefused(
                "The call-list is already being built — watch it below, or cancel it first.",
                link="/contacts",
            )

        from jobfinder.cli import DEFAULT_CITIES

        names = tuple(_comma_list(cities) or DEFAULT_CITIES)
        with self._lock:
            self._contacts_failure = None
        self._contacts_cancel = threading.Event()
        self._contacts_thread = threading.Thread(
            target=self._contacts_work,
            args=(names, radius_km),
            daemon=True,
            name="contacts-run",
        )
        self._contacts_thread.start()

    def cancel_contacts(self) -> None:
        """Stop between cities. Every place already found is kept (§9)."""
        self._contacts_cancel.set()

    def wait_contacts(self, timeout: float | None = None) -> None:
        if self._contacts_thread is not None:
            self._contacts_thread.join(timeout)

    def _contacts_work(self, cities: tuple[str, ...], radius_km: int | None) -> None:
        try:
            from jobfinder.contacts.runner import DEFAULT_RADIUS_KM, run_contacts

            runner = self._contacts_runner or run_contacts
            runner(
                settings=self._settings,
                source=self._contacts_source(),
                cities=cities,
                radius_km=radius_km or DEFAULT_RADIUS_KM,
                languages=_her_languages(self._settings),
                stop_event=self._contacts_cancel,
            )
        except Exception as exc:  # the page must have a sentence, not a traceback
            with self._lock:
                self._contacts_failure = (
                    f"Building the call-list stopped unexpectedly ({type(exc).__name__}). "
                    "Every place it found is safe — try again."
                )

    def _contacts_source(self):
        if self._contacts_source_factory is not None:
            return self._contacts_source_factory()
        from jobfinder.sources.http import PoliteClient
        from jobfinder.sources.overpass import OverpassSource

        # Overpass is a donated public server: a long gap between requests is the
        # etiquette, and it is what stops a 429 becoming the normal answer.
        return OverpassSource(
            PoliteClient(
                cache_dir=self._settings.data_dir / "http-cache",
                budget=self._settings.request_budget,
                min_delay=6.0,
            )
        )

    def cancel(self) -> None:
        """Stop between pages. Everything already stored is kept (§9)."""
        self._cancel.set()
        if self._companion is not None:
            self._companion.cancel()

    def cancel_enrich(self) -> None:
        """Stop the standalone pass between batches, keeping every answer (§9)."""
        if self._enrich_companion is not None:
            self._enrich_stopping = True
            self._enrich_companion.cancel()

    def wait(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def wait_enrich(self, timeout: float | None = None) -> None:
        if self._enrich_thread is not None:
            self._enrich_thread.join(timeout)

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

    def _enrich_work(self, companion) -> None:
        """The standalone pass: start, drain, close its own journal row."""
        try:
            companion.start()
            companion.finish()
        except Exception as exc:  # the panel must have a sentence, not a traceback
            with self._lock:
                self._enrich_failure = (
                    f"Explaining jobs stopped unexpectedly ({type(exc).__name__}). "
                    "Every answer it saved is safe — press Explain again to continue."
                )


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
    """The enrichment worker — for `explain while searching`, or on its own.

    `limit` is None for the search's companion, which is meant to keep up with
    whatever arrives, and a number for a pass she started from the browser,
    where the promised cost has to be one the pass keeps to.
    """

    def factory(*, limit: int | None = None):
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
            limit=limit,
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
