"""The app she opens — localhost-only, answering, opened by one command.

Phase 8's product surface starts here: `jobfinder serve` starts the server on
127.0.0.1 and opens her browser at it. Everything else (list, job pages,
progress) is built on this skeleton.
"""

from __future__ import annotations

import socket
import threading
import time

import httpx
import pytest
import uvicorn
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


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind((SERVER_HOST, 0))
        return probe.getsockname()[1]


def test_serve_opens_the_browser_once_against_a_server_that_answers(tmp_path, monkeypatch):
    """The real `_uvicorn_serve`, not the injected seam the CLI tests use.

    Two things have to hold at once, and only a real server can show both:
    when `on_ready` fires the port is already answering, and it fires exactly
    once — a browser that reopens her tab every second is as broken as one
    that never opens it.
    """
    from jobfinder.cli import _uvicorn_serve

    port = free_port()
    app = create_app(Settings(project_root=tmp_path))

    servers: list[uvicorn.Server] = []

    class RecordingServer(uvicorn.Server):
        """The real server, kept where the test can shut it down again."""

        def __init__(self, config):
            super().__init__(config)
            servers.append(self)

    monkeypatch.setattr(uvicorn, "Server", RecordingServer)

    answers: list[int] = []

    def on_ready() -> None:
        answers.append(httpx.get(f"http://{SERVER_HOST}:{port}/", timeout=5).status_code)

    thread = threading.Thread(
        target=_uvicorn_serve,
        args=(app,),
        kwargs={"host": SERVER_HOST, "port": port, "on_ready": on_ready},
        daemon=True,
    )
    thread.start()
    try:
        deadline = time.time() + 10
        while time.time() < deadline and not answers:
            time.sleep(0.05)
        # Long enough for uvicorn's periodic heartbeat to come round again.
        time.sleep(1.5)
    finally:
        for server in servers:
            server.should_exit = True
        thread.join(timeout=10)

    assert servers, "_uvicorn_serve never built a uvicorn server"
    assert answers == [200], f"expected one 200 as the tab opens, got {answers}"
    assert not thread.is_alive(), "the server did not stop"


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


def test_healthcheck_answers_ok(tmp_path):
    """The build smoke test's only question: did the exe actually come up?

    It is exempt from the first-run redirect on purpose — a health check that
    answers 303 before setup would report a healthy app as broken.
    """
    from fastapi.testclient import TestClient

    (tmp_path / "config.yaml").unlink(missing_ok=True)
    with TestClient(create_app(Settings(project_root=tmp_path))) as client:
        response = client.get("/healthz", follow_redirects=False)

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


class TestServeGoesThroughTheLauncher:
    """`jobfinder serve` and `JobFinder.exe` must be the same code path.

    They were not: the CLI had its own copy of "make an app, serve it, open a
    browser", so the exe would have been the only untested way in. The CLI is
    now a thin call into `launch.start`, and a port that is busy is handled
    for both.
    """

    def call(self, tmp_path, argv, serve, browser):
        from jobfinder.cli import main

        return main(["serve", "--root", str(tmp_path), *argv], _serve=serve, _browser=browser)

    def test_serve_says_where_the_data_is(self, tmp_path, capsys):
        self.call(tmp_path, ["--port", "8123", "--no-browser"], lambda *a, **k: None, browser=None)

        assert str(tmp_path / "data") in capsys.readouterr().out

    def test_serve_moves_to_a_free_port_when_the_asked_one_is_taken(self, tmp_path, capsys):
        seen = {}

        def fake_serve(app, *, host, port, on_ready):
            seen["port"] = port

        with socket.socket() as taken:
            taken.bind((SERVER_HOST, 0))
            taken.listen()
            busy = taken.getsockname()[1]

            self.call(
                tmp_path,
                ["--port", str(busy), "--no-browser"],
                fake_serve,
                browser=None,
            )

        assert seen["port"] != busy
