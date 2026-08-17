"""The one question that only a real build can answer: does the exe come up?

Marked `live` because it starts a real server on a real port. It does not hit
the internet, but it takes about ten seconds and needs `dist/JobFinder.exe` to
exist, so it has no business in the offline suite.

    python scripts/build_exe.py
    pytest -m live tests/live/test_built_exe.py

Everything else about the bundle is checked offline in
`tests/unit/test_packaging.py`. This checks the thing those lists exist for:
that the program starts on a machine, serves a page built from a bundled
template, and answers `/healthz`.
"""

from __future__ import annotations

import json
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BUILT = REPO_ROOT / "dist" / "JobFinder.exe"
HOST = "127.0.0.1"


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind((HOST, 0))
        return probe.getsockname()[1]


def wait_for(url: str, *, timeout: float = 45.0):
    """The exe unpacks itself before it listens, so this waits rather than polls once."""
    deadline = time.monotonic() + timeout
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            # The server is up and the page is broken — waiting longer will not
            # change that, and the status is the whole diagnosis. Retrying here
            # once turned a bundling bug into a 45-second silence.
            raise AssertionError(f"{url} answered {exc.code}") from exc
        except (urllib.error.URLError, OSError) as exc:
            last = exc
            time.sleep(0.5)
    raise AssertionError(f"{url} never answered within {timeout}s (last: {last})")


@pytest.mark.live
def test_built_exe_starts_and_answers_healthcheck(tmp_path):
    if not BUILT.exists():
        pytest.skip(f"no build at {BUILT} — run `python scripts/build_exe.py` first")

    install = tmp_path / "JobFinder"
    install.mkdir()
    # A fresh install: no config, so this also proves the wizard path comes up.
    exe = install / "JobFinder.exe"
    exe.write_bytes(BUILT.read_bytes())
    port = free_port()

    # Its console output goes to a file rather than a pipe: an unread pipe is a
    # handle this test would leak, and the log is what says why a build failed.
    log = install / "console.log"
    with open(log, "w", encoding="utf-8") as console:
        process = subprocess.Popen(
            [str(exe), "--port", str(port), "--no-browser"],
            cwd=install,
            stdout=console,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            status, body = wait_for(f"http://{HOST}:{port}/healthz")
            assert status == 200
            assert json.loads(body)["status"] == "ok"

            # A page, so a missing template shows up here rather than on her laptop.
            status, body = wait_for(f"http://{HOST}:{port}/setup")
            assert status == 200
            assert b"Welcome" in body

            # And `data/` landed beside the exe, not in PyInstaller's temp folder.
            assert (install / "data").is_dir()

            # The console window is the only thing she sees before the browser
            # opens, so it has to say the address *while the app runs* — not
            # when it exits. A frozen build block-buffers stdout, so this was
            # empty until the process ended.
            console_so_far = log.read_text(encoding="utf-8")
            assert f"http://{HOST}:{port}" in console_so_far
            assert "closing it stops the app" in console_so_far.lower()
        finally:
            process.terminate()
            process.wait(timeout=30)

    print(log.read_text(encoding="utf-8"))
