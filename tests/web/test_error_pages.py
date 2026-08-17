"""The failures nobody planned for still have to arrive as a page.

Phase 8 wrote the refusals that can be predicted — no key, no CV, a search
already running. This file is about the other kind: an exception from a corner
nobody thought about, and the one she is most likely to actually meet, which is
a laptop that is not on the internet.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from jobfinder.config import Settings
from jobfinder.web.app import create_app
from jobfinder.web.runs import RunManager


class NoInternet:
    """Every source, on a laptop with the wi-fi off."""

    source = "BA"

    def search_pages(self, spec, *, start_query_index=0, start_page=1):
        raise OSError("[Errno 11001] getaddrinfo failed")
        yield  # pragma: no cover  (never reached; keeps this a generator)


def test_no_internet_produces_a_readable_page_not_a_traceback(tmp_path):
    settings = Settings.load(project_root=tmp_path)
    manager = RunManager(settings, adapter_factory=lambda: [NoInternet()])

    with TestClient(create_app(settings, run_manager=manager)) as client:
        client.post("/run/start", data={})
        manager.wait(timeout=10)
        body = client.get("/progress").text

    assert "getaddrinfo" not in body
    assert "Traceback" not in body
    assert "internet" in body.lower()


def test_an_unexpected_failure_renders_the_error_page_not_a_stack_trace(settings):
    """A route that raises must still answer in her language. The one below is
    deliberately absurd — the point is that no route can be trusted to have
    thought of everything."""

    app = create_app(settings)

    @app.get("/boom")
    def boom():
        raise RuntimeError("a corner nobody thought about")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/boom")

    assert response.status_code == 500
    assert "RuntimeError" not in response.text
    assert "Traceback" not in response.text
    assert "Back to your jobs" in response.text


def test_the_error_page_says_what_to_do_next(settings):
    app = create_app(settings)

    @app.get("/boom")
    def boom():
        raise RuntimeError("nope")

    with TestClient(app, raise_server_exceptions=False) as client:
        body = client.get("/boom").text

    assert "nothing you had is lost" in body.lower()


@pytest.mark.parametrize("path", ["/jobs/BA%3Anope", "/no-such-page"])
def test_a_page_that_does_not_exist_is_a_sentence_too(settings, path):
    with TestClient(create_app(settings)) as client:
        response = client.get(path)

    assert response.status_code == 404
    assert "Back to your jobs" in response.text
