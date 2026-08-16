"""One end-to-end path through a real browser: filter, open, mark applied.

Skips cleanly when Playwright (or its Chromium) is not installed — the suite
must stay green offline; this test is the honest check that the HTML she
reads actually works in the thing she reads it with.
"""

from __future__ import annotations

import threading
import time

import pytest

pytest.importorskip("playwright.sync_api", reason="Playwright is not installed")

from playwright.sync_api import sync_playwright  # noqa: E402
from tests.web.conftest import store_job  # noqa: E402

from jobfinder.config import Settings  # noqa: E402
from jobfinder.store.db import connect, migrate  # noqa: E402
from jobfinder.web.app import SERVER_HOST, create_app  # noqa: E402


def _free_port() -> int:
    import socket

    with socket.socket() as sock:
        sock.bind((SERVER_HOST, 0))
        return sock.getsockname()[1]


@pytest.fixture
def server_url(tmp_path):
    import uvicorn

    settings = Settings(project_root=tmp_path)
    connection = connect(settings.db_path)
    try:
        migrate(connection)
        store_job(
            connection,
            job_id="BA:1",
            title="Bäckerei Aushilfe",
            city="Ingolstadt",
            minijob=True,
        )
        store_job(
            connection,
            job_id="AN:2",
            title="Café Assistant",
            city="München",
            parttime=True,
        )
    finally:
        connection.close()

    app = create_app(settings)
    port = _free_port()
    config = uvicorn.Config(app, host=SERVER_HOST, port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while time.time() < deadline and not server.started:
        time.sleep(0.05)
    yield f"http://{SERVER_HOST}:{port}"
    server.should_exit = True
    thread.join(timeout=15)


def test_playwright_smoke_filter_open_job_mark_applied(server_url):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(server_url)

            # Filter to one city — the list narrows without a reload.
            page.select_option("select[name='city']", "Ingolstadt")
            page.wait_for_timeout(600)  # the HTMX swap settles
            body = page.inner_text("body")
            assert "Bäckerei Aushilfe" in body
            assert "Café Assistant" not in body

            # Open the job, mark it applied, and read it back.
            page.click("text=Bäckerei Aushilfe")
            page.wait_for_selector("#actions")
            page.click("button[value='applied']")
            page.wait_for_selector(".status-chip.applied")
            assert "applied" in page.inner_text("#actions")

            # A reload must show the same state — §9, from the database.
            page.reload()
            page.wait_for_selector("#actions")
            assert "applied" in page.inner_text("#actions")
        finally:
            browser.close()
