"""Enrichment, run from the browser — the heart of the product, unreachable.

Her store holds 859 jobs and 20 English answers, because enrichment has only
ever run from a terminal. Everything the list and the job page promise — the
summary, the German level, the fit score — is blank for the rest.

Two rules shape every test here. The free-tier rule (cross-cutting concerns):
a run says how many calls it will make *before* making them, so the button
carries a count and a bound. And §9: a pass killed at any moment keeps every
answer it stored, and pressing the button again continues rather than repeats.
"""

from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient
from tests.fakes import FakePool
from tests.web.conftest import PROMPT_VERSION, enrichment_answer, store_job

from jobfinder.config import Settings
from jobfinder.enrich.companion import EnrichmentCompanion
from jobfinder.store.db import connect, migrate
from jobfinder.web.app import create_app
from jobfinder.web.runs import RunManager, StartRefused

DIGEST = "# Skills\n- Programming Languages: Python"


def unenriched_store(settings: Settings, count: int = 4) -> Settings:
    """A store shaped like hers: jobs with ad text and no answer at all."""
    connection = connect(settings.db_path)
    try:
        migrate(connection)
        for index in range(count):
            store_job(
                connection,
                job_id=f"BA:{index}",
                title=f"Aushilfe Bäckerei {index}",
                description=(
                    f"Wir suchen eine Aushilfe für Filiale {index}. "
                    "Gute Deutschkenntnisse in Wort und Schrift."
                ),
            )
    finally:
        connection.close()
    return settings


def enriched_count(settings: Settings) -> int:
    connection = connect(settings.db_path)
    try:
        return connection.execute("SELECT COUNT(*) FROM enrichment").fetchone()[0]
    finally:
        connection.close()


def enrich_run(settings: Settings):
    connection = connect(settings.db_path)
    try:
        return connection.execute(
            "SELECT * FROM runs WHERE kind = 'enrich' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        connection.close()


def fake_companion_factory(settings: Settings, answers: int = 20, gate=None):
    """The real companion over a FakePool — the manager's seam, nothing else.

    `gate` holds the pool open on its first answer, which is what "she pressed
    Cancel while it was working" looks like from the inside.
    """

    class GatedPool(FakePool):
        def run_batch(self, *args, **kwargs):
            if gate is not None:
                gate.wait(timeout=10)
            return super().run_batch(*args, **kwargs)

    pool_class = GatedPool if gate is not None else FakePool

    def factory(*, limit: int | None = None):
        return EnrichmentCompanion(
            settings.db_path,
            pool_class([enrichment_answer()] * answers),
            settings,
            cv_digest=DIGEST,
            csv_path=settings.jobs_enriched_csv,
            workers=1,
            poll_seconds=0.01,
            prompt_version=PROMPT_VERSION,
            limit=limit,
        )

    return factory


@pytest.fixture
def enriching(tmp_path):
    """Settings + manager + client wired to a companion that spends no money."""
    settings = unenriched_store(Settings(project_root=tmp_path))
    manager = RunManager(
        settings,
        adapter_factory=lambda: [],
        companion_factory=fake_companion_factory(settings),
    )
    with TestClient(create_app(settings, run_manager=manager)) as client:
        yield settings, manager, client


def wait_until(predicate, timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


class TestManagerStartsEnrichment:
    def test_start_enrich_runs_the_companion_and_journals_an_enrich_run(self, enriching):
        settings, manager, _client = enriching

        manager.start_enrich()
        manager.wait_enrich(timeout=15)

        assert enriched_count(settings) == 4
        run = enrich_run(settings)
        assert run is not None
        assert run["state"] == "done"
        assert run["enriched_count"] == 4

    def test_start_enrich_honours_the_limit_it_was_given(self, enriching):
        settings, manager, _client = enriching

        manager.start_enrich(limit=2)
        manager.wait_enrich(timeout=15)

        assert enriched_count(settings) == 2

    def test_start_enrich_is_refused_while_an_enrichment_is_already_running(self, tmp_path):
        settings = unenriched_store(Settings(project_root=tmp_path))
        gate = threading.Event()
        manager = RunManager(
            settings,
            adapter_factory=lambda: [],
            companion_factory=fake_companion_factory(settings, gate=gate),
        )
        manager.start_enrich()
        assert wait_until(manager.is_enriching)

        with pytest.raises(StartRefused) as refused:
            manager.start_enrich()

        assert "already" in str(refused.value)
        gate.set()
        manager.wait_enrich(timeout=15)

    def test_start_enrich_is_allowed_while_a_search_is_running(self, tmp_path):
        """A search waits on job-site hosts and enrichment on LLM providers
        (§9), so the one must never be refused because the other is going."""
        settings = unenriched_store(Settings(project_root=tmp_path))
        searching = threading.Event()

        def slow_runner(*_args, **_kwargs):
            searching.wait(timeout=10)

        manager = RunManager(
            settings,
            adapter_factory=lambda: [],
            companion_factory=fake_companion_factory(settings),
            runner=slow_runner,
        )
        manager.start()
        assert wait_until(manager.is_running)

        manager.start_enrich()  # must not raise
        manager.wait_enrich(timeout=15)

        assert enriched_count(settings) == 4
        searching.set()
        manager.wait(timeout=10)

    def test_a_search_is_still_refused_while_a_search_is_running(self, enriching):
        """The other direction of the same rule: enrichment must not have
        loosened the one-search-at-a-time guard."""
        settings, manager, _client = enriching
        searching = threading.Event()
        manager._runner = lambda *_a, **_k: searching.wait(timeout=10)
        manager.start()
        assert wait_until(manager.is_running)

        with pytest.raises(StartRefused):
            manager.start()

        searching.set()
        manager.wait(timeout=10)


class TestManagerCancelsEnrichment:
    def test_cancel_enrich_stops_the_pass_and_keeps_what_it_saved(self, tmp_path):
        settings = unenriched_store(Settings(project_root=tmp_path), count=6)
        gate = threading.Event()
        manager = RunManager(
            settings,
            adapter_factory=lambda: [],
            companion_factory=fake_companion_factory(settings, gate=gate),
        )
        manager.start_enrich()
        assert wait_until(manager.is_enriching)

        manager.cancel_enrich()
        gate.set()
        manager.wait_enrich(timeout=15)

        run = enrich_run(settings)
        assert run["state"] == "interrupted"  # not 'done' — she stopped it
        assert enriched_count(settings) == run["enriched_count"]  # journal agrees with the store

    def test_cancel_enrich_does_not_cancel_a_running_search(self, tmp_path):
        settings = unenriched_store(Settings(project_root=tmp_path))
        stopped = threading.Event()

        def watching_runner(*_args, stop_event=None, **_kwargs):
            # The search's own stop event: if Cancel-enrich reached it, this
            # sees it set, which is the bug the test exists to catch.
            for _ in range(100):
                if stop_event is not None and stop_event.is_set():
                    stopped.set()
                    return
                time.sleep(0.01)

        manager = RunManager(
            settings,
            adapter_factory=lambda: [],
            companion_factory=fake_companion_factory(settings),
            runner=watching_runner,
        )
        manager.start()
        assert wait_until(manager.is_running)

        manager.start_enrich()
        manager.wait_enrich(timeout=15)
        manager.cancel_enrich()
        manager.wait(timeout=10)

        assert not stopped.is_set()

    def test_cancel_search_does_not_cancel_a_running_enrichment(self, tmp_path):
        settings = unenriched_store(Settings(project_root=tmp_path), count=6)
        gate = threading.Event()
        manager = RunManager(
            settings,
            adapter_factory=lambda: [],
            companion_factory=fake_companion_factory(settings, gate=gate),
            runner=lambda *_a, **_k: None,
        )
        manager.start_enrich()
        assert wait_until(manager.is_enriching)

        manager.cancel()  # the search's Cancel, pressed while enrichment runs
        gate.set()
        manager.wait_enrich(timeout=15)

        assert enrich_run(settings)["state"] == "done"
        assert enriched_count(settings) == 6


class TestManagerRefusals:
    def test_enrich_without_a_key_refuses_with_a_sentence_and_a_link(self, tmp_path, monkeypatch):
        import shutil
        from pathlib import Path

        import llmpool

        settings = Settings(project_root=tmp_path)
        shutil.copy(
            Path(__file__).resolve().parents[2] / "pool.template.yaml", tmp_path / "pool.yaml"
        )
        for _name, env_var, _url in llmpool.missing_keys(llmpool.load_catalog(), env={}):
            monkeypatch.delenv(env_var, raising=False)

        manager = RunManager(settings, adapter_factory=lambda: [])
        with pytest.raises(StartRefused) as refused:
            manager.start_enrich()

        assert "No LLM API key" in refused.value.sentence
        assert refused.value.link == "/settings"

    def test_enrich_without_a_readable_cv_refuses_and_links_to_settings(self, tmp_path):
        settings = Settings(project_root=tmp_path)  # no pool.yaml at all
        manager = RunManager(settings, adapter_factory=lambda: [])

        with pytest.raises(StartRefused) as refused:
            manager.start_enrich()

        assert refused.value.link == "/settings"

    def test_an_enrichment_that_dies_leaves_a_sentence_not_a_traceback(self, tmp_path):
        settings = unenriched_store(Settings(project_root=tmp_path))

        def exploding_factory(*, limit: int | None = None):
            class Exploding:
                def start(self):
                    raise RuntimeError("the provider hung up")

                def cancel(self):
                    pass

                def finish(self, timeout=None):
                    pass

            return Exploding()

        manager = RunManager(
            settings, adapter_factory=lambda: [], companion_factory=exploding_factory
        )
        manager.start_enrich()
        manager.wait_enrich(timeout=10)

        failure = manager.enrich_failure()
        assert failure is not None
        assert "Traceback" not in failure
        assert "RuntimeError" in failure  # named, so a bug report is possible
