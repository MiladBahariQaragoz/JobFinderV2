"""One always-present live test, so the live lane is never empty.

Contract tests for each source land here as their adapters are built. Run with:

    pytest -m live
"""

import socket

import pytest


@pytest.mark.live
def test_live_probe_can_reach_the_internet():
    """Proves the live lane really is allowed out, unlike the default run."""
    with socket.create_connection(("rest.arbeitsagentur.de", 443), timeout=15) as sock:
        assert sock.getpeername()
