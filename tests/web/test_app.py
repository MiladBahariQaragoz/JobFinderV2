"""The app she opens — localhost-only, answering, opened by one command.

Phase 8's product surface starts here: `jobfinder serve` starts the server on
127.0.0.1 and opens her browser at it. Everything else (list, job pages,
progress) is built on this skeleton.
"""

from __future__ import annotations

import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from jobfinder.config import Settings
from jobfinder.web.app import SERVER_HOST, create_app


@pytest.fixture
def settings(tmp_path):
    return Settings(project_root=tmp_path)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def test_server_binds_localhost_only():
    # §2: one user, one laptop — the server must never listen beyond it.
    assert SERVER_HOST == "127.0.0.1"


def test_the_app_answers_the_index_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_static_assets_are_served_locally(client):
    # The exe must work offline: htmx and the fonts ship inside the app.
    response = client.get("/static/vendor/htmx.min.js")
    assert response.status_code == 200
    assert b"htmx" in response.content[:2000]


class TestServeCommand:
    """The serve seam: (app, host, port, on_ready). `on_ready` fires once the
    server is up — the browser opens against a listening server, not a
    connection the OS has not handed out yet."""

    def call(self, tmp_path, argv, serve, browser):
        from jobfinder.cli import main

        return main(
            ["serve", "--root", str(tmp_path), *argv],
            _serve=serve,
            _browser=browser,
        )

    def test_serve_wires_localhost_and_the_port(self, tmp_path):
        seen = {}

        def fake_serve(app, *, host, port, on_ready):
            seen.update(has_app=app is not None, host=host, port=port)

        self.call(tmp_path, ["--port", "8123", "--no-browser"], fake_serve, browser=None)
        assert seen == {"has_app": True, "host": "127.0.0.1", "port": 8123}

    def test_serve_opens_the_browser_once_the_server_is_ready(self, tmp_path):
        opened = {}

        def fake_serve(app, *, host, port, on_ready):
            on_ready()  # the server is up

        self.call(
            tmp_path,
            ["--port", "8123"],
            fake_serve,
            browser=lambda url: opened.update(url=url) or True,
        )
        assert opened["url"] == "http://127.0.0.1:8123"

    def test_no_browser_flag_leaves_the_browser_alone(self, tmp_path):
        called = []

        def fake_serve(app, *, host, port, on_ready):
            on_ready()

        self.call(tmp_path, ["--port", "8123", "--no-browser"], fake_serve, browser=called.append)
        assert called == []


def test_serve_starts_and_answers_over_http(tmp_path):
    """The real thing: uvicorn on a real socket on this machine, then a GET."""
    import uvicorn

    app = create_app(Settings(project_root=tmp_path))
    config = uvicorn.Config(app, host=SERVER_HOST, port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.time() + 10
        while time.time() < deadline and not server.started:
            time.sleep(0.05)
        assert server.started, "uvicorn never came up"
        (socket,) = server.servers[0].sockets
        port = socket.getsockname()[1]

        response = httpx.get(f"http://127.0.0.1:{port}/", timeout=5)
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
    finally:
        server.should_exit = True
        thread.join(timeout=10)
