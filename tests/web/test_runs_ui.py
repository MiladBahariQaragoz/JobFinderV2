"""The live progress surface — §10, the part she stares at for four minutes.

Every number on it is read from the `runs` journal, so a reload mid-run shows
the same state the run is producing; Cancel stops between pages and keeps
what landed; an interrupted run comes back as a banner with Resume.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jobfinder.config import Settings
from jobfinder.sources.base import PageResult, RawPosting
from jobfinder.store.db import connect, migrate
from jobfinder.store.runs import display_state  # noqa: F401  (import surface check)
from jobfinder.web.app import create_app
from jobfinder.web.runs import RunManager


def posting(n: int) -> RawPosting:
    return RawPosting(job_id=f"BA:{n}", source="BA", source_id=str(n), title=f"Job {n}")


class SlowSource:
    """Page one lands, page two only arrives after the cancel event — the
    shape of a real search the moment she presses Cancel."""

    source = "BA"

    def __init__(self):
        self.gate = threading.Event()

    def search_pages(self, spec, *, start_query_index=0, start_page=1):
        yield PageResult(
            source="BA", query_index=0, page=1, postings=[posting(n) for n in range(3)]
        )
        self.gate.wait(timeout=10)  # she cancels while page 2 "downloads"
        yield PageResult(
            source="BA", query_index=0, page=2, postings=[posting(n) for n in range(3, 6)]
        )


@pytest.fixture
def managed(tmp_path):
    """A settings + app whose run engine drives a controllable fake source."""
    settings = Settings(project_root=tmp_path)
    slow = SlowSource()
    manager = RunManager(settings, adapter_factory=lambda: [slow])
    with TestClient(create_app(settings, run_manager=manager)) as client:
        yield settings, manager, client


def seed_running_run(settings, *, found=12, new=5):
    connection = connect(settings.db_path)
    try:
        migrate(connection)
        cursor = connection.execute(
            "INSERT INTO runs (kind, state, started_at, last_progress_at, found_count,"
            " new_count) VALUES ('search', 'running', datetime('now'), datetime('now'),"
            " ?, ?)",
            (found, new),
        )
        connection.execute(
            "INSERT INTO run_sources (run_id, source, found_count, new_count, state,"
            " last_event_at) VALUES (?, 'ba', ?, ?, 'running', datetime('now'))",
            (cursor.lastrowid, found, new),
        )
        connection.commit()
        return int(cursor.lastrowid)
    finally:
        connection.close()


class TestProgressEndpoint:
    def test_progress_endpoint_reports_current_source_and_counts(self, managed):
        settings, _manager, client = managed
        seed_running_run(settings)

        body = client.get("/progress").text
        assert "Bundesagentur" in body  # the label, not the source code
        assert ">12<" in body and "found" in body  # counts, in the mono spans
        assert ">5<" in body and "new" in body

    def test_search_progress_is_persisted_and_survives_a_page_reload(self, managed):
        settings, _manager, client = managed
        seed_running_run(settings)

        first = client.get("/progress").text
        reloaded = client.get("/progress").text  # a fresh request, like F5
        page = client.get("/search").text  # the whole page, reloaded

        for body in (first, reloaded, page):
            assert ">12<" in body  # same counts every time she looks
            assert "Bundesagentur" in body

    def test_the_job_list_still_says_a_search_is_running(self, managed):
        """The panel moved to its own page; the work must not become invisible
        on the one she spends her time on (§10 — nothing ever looks frozen)."""
        settings, _manager, client = managed
        seed_running_run(settings)

        body = client.get("/").text
        assert "A search is running" in body
        assert ">12<" in body  # the same counts, from the same journal
        assert 'href="/search"' in body  # ...and one click to the full panel

    def test_progress_offers_cancel_while_a_run_is_live(self, managed):
        settings, _manager, client = managed
        seed_running_run(settings)

        body = client.get("/progress").text
        assert "Cancel" in body

    def test_a_source_that_failed_says_so_in_plain_english(self, managed):
        settings, _manager, client = managed
        run_id = seed_running_run(settings)
        connection = connect(settings.db_path)
        try:
            connection.execute(
                "UPDATE run_sources SET state = 'failed' WHERE run_id = ?", (run_id,)
            )
            connection.commit()
        finally:
            connection.close()

        body = client.get("/progress").text
        assert "failed" in body


class TestStartAndCancel:
    def test_the_search_button_starts_a_run_the_progress_panel_narrates(self, managed):
        _settings, manager, client = managed

        response = client.post(
            "/run/start", data={"cities": "Ingolstadt", "types": "minijob"}, follow_redirects=True
        )
        assert response.status_code == 200

        # While the run is still waiting on its second page, the panel already
        # narrates page one — that is the whole §10 promise.
        deadline = time.time() + 10
        body = ""
        while time.time() < deadline:
            body = client.get("/progress").text
            if ">3<" in body and "Bundesagentur" in body:
                break
            time.sleep(0.1)
        assert ">3<" in body and "Bundesagentur" in body

        manager.cancel()
        manager.wait(timeout=15)

    def test_cancel_stops_the_run_and_keeps_completed_work(self, managed):
        settings, manager, client = managed

        client.post("/run/start", data={"cities": "Ingolstadt", "types": "minijob"})
        deadline = time.time() + 10
        while time.time() < deadline:
            stored = _count_jobs(settings)
            if stored == 3:
                break
            time.sleep(0.05)
        assert _count_jobs(settings) == 3  # page one is on disk

        response = client.post("/run/cancel", follow_redirects=True)
        assert response.status_code == 200
        manager.wait(timeout=10)

        connection = connect(settings.db_path)
        try:
            run = connection.execute(
                "SELECT * FROM runs WHERE kind = 'search' ORDER BY id DESC LIMIT 1"
            ).fetchone()
        finally:
            connection.close()
        assert run["state"] == "interrupted"  # not 'done': the banner appears
        assert _count_jobs(settings) == 3  # nothing lost, nothing extra

        body = client.get("/progress").text
        assert "Resume" in body

    def test_a_second_start_while_running_is_refused_politely(self, managed):
        _settings, manager, client = managed
        client.post(
            "/run/start", data={"cities": "Ingolstadt", "types": "minijob"}, follow_redirects=True
        )
        assert manager.is_running()

        response = client.post("/run/start", data={"cities": "München", "types": "minijob"})
        assert response.status_code in (200, 409)
        assert "already running" in response.text

        manager.cancel()
        manager.wait(timeout=10)


class TestInterruptedBanner:
    def test_interrupted_run_banner_offers_resume_with_the_right_counts(self, managed):
        settings, _manager, client = managed
        connection = connect(settings.db_path)
        try:
            migrate(connection)
            connection.execute(
                "INSERT INTO runs (kind, state, started_at, last_progress_at, finished_at,"
                " found_count, new_count) VALUES ('search', 'interrupted', datetime('now'),"
                " datetime('now'), datetime('now'), 143, 61)"
            )
            connection.commit()
        finally:
            connection.close()

        body = client.get("/progress").text
        assert "interrupted" in body
        assert "143" in body  # the counts it left behind, not a vague apology
        assert "Resume" in body

    def test_resume_button_continues_the_interrupted_run(self, managed):
        _settings, manager, client = managed
        client.post(
            "/run/start",
            data={"cities": "Ingolstadt", "types": "minijob", "resume": "on"},
            follow_redirects=True,
        )
        # `SlowSource` waits on its own gate for up to 10 s before yielding page
        # two, so joining for a fixed 10 s is a race the busy machine loses —
        # wait for the journal to say `done` instead of assuming a duration.
        slow_page_two = 10 + 5
        deadline = time.time() + slow_page_two
        state = None
        while time.time() < deadline:
            connection = connect(_settings.db_path)
            try:
                row = connection.execute(
                    "SELECT state FROM runs WHERE kind = 'search' ORDER BY id DESC LIMIT 1"
                ).fetchone()
            finally:
                connection.close()
            state = row["state"] if row is not None else None
            if state == "done":
                break
            time.sleep(0.1)
        manager.wait(timeout=5)

        # the run started, journalled, and finished on the fake source
        assert state == "done"


class TestMissingKey:
    def test_missing_api_key_renders_a_sentence_and_a_link_not_a_traceback(
        self, tmp_path, monkeypatch
    ):
        import shutil

        import llmpool

        settings = Settings(project_root=tmp_path)
        # A readable CV, so the refusal is the one the test is about: keys.
        shutil.copy(
            Path(__file__).resolve().parents[2] / "pool.template.yaml",
            tmp_path / "pool.yaml",
        )
        # env={} enumerates *every* provider var — an earlier test may have
        # loaded this repo's real .env into os.environ, and a key that is set
        # would not appear in the plain missing list.
        for _name, env_var, _url in llmpool.missing_keys(llmpool.load_catalog(), env={}):
            monkeypatch.delenv(env_var, raising=False)
        monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
        monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)

        manager = RunManager(settings)
        with TestClient(create_app(settings, run_manager=manager)) as client:
            response = client.post(
                "/run/start",
                data={"cities": "Ingolstadt", "types": "minijob", "enrich": "on"},
            )
            assert response.status_code == 200  # a sentence, not a 500
            body = response.text
            assert "No LLM API key" in body
            assert 'href="/settings"' in body  # the fix, one click away
            assert "Traceback" not in body

    def test_settings_page_lists_what_is_missing(self, tmp_path):
        settings = Settings(project_root=tmp_path)
        with TestClient(create_app(settings)) as client:
            body = client.get("/settings").text
            assert "Settings" in body


def _count_jobs(settings) -> int:
    connection = connect(settings.db_path)
    try:
        return connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    finally:
        connection.close()
