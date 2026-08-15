"""Shared test fixtures.

The important one is `no_network`: unless a test is marked `live` or `live_llm`,
any outbound connection fails loudly. A test that needs data from a source reads
a recorded fixture instead — see `scripts/record_fixture.py`.
"""

from __future__ import annotations

import socket
import sqlite3
from pathlib import Path

import pytest

FIXTURE_ROOT = Path(__file__).parent / "fixtures"
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "0.0.0.0"}

_real_connect = socket.socket.connect
_real_create_connection = socket.create_connection


def _host_of(address) -> str | None:
    if isinstance(address, tuple) and address:
        return str(address[0])
    return None


def _refuse_unless_local(address) -> None:
    host = _host_of(address)
    if host is None or host in LOCAL_HOSTS:
        return
    raise RuntimeError(
        f"blocked network access to {host} — tests run offline. "
        f"Use a recorded fixture, or mark the test @pytest.mark.live."
    )


@pytest.fixture(autouse=True)
def no_network(request, monkeypatch):
    """Fail any outbound connection in tests that are not explicitly live."""
    if request.node.get_closest_marker("live") or request.node.get_closest_marker("live_llm"):
        return

    def guarded_connect(self, address, *args, **kwargs):
        _refuse_unless_local(address)
        return _real_connect(self, address, *args, **kwargs)

    def guarded_create_connection(address, *args, **kwargs):
        _refuse_unless_local(address)
        return _real_create_connection(address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "create_connection", guarded_create_connection)


def _is_closed(connection: sqlite3.Connection) -> bool:
    try:
        connection.execute("SELECT 1")
    except sqlite3.ProgrammingError:
        return True
    return False


@pytest.fixture
def sqlite_leaks(monkeypatch):
    """Report which SQLite connections opened during this test are still open.

    An unclosed connection is not cosmetic: on Windows it keeps a lock on the
    database file, and it surfaces later as a `ResourceWarning` attributed to
    whichever unlucky test the garbage collector was running at the time.
    """
    opened: list[sqlite3.Connection] = []
    real_connect = sqlite3.connect

    def tracking_connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", tracking_connect)

    def still_open() -> list[sqlite3.Connection]:
        return [connection for connection in opened if not _is_closed(connection)]

    return still_open


@pytest.fixture
def fixture_path():
    """Path to a recorded response, e.g. fixture_path("ba", "jobs_werkstudent.json")."""

    def _path(source: str, name: str) -> Path:
        return FIXTURE_ROOT / source / name

    return _path
