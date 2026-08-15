"""The guard that keeps the default test run offline.

Without this, one adapter test quietly hitting the real Bundesagentur API would
make the suite slow, flaky, and dependent on someone else's uptime.
"""

import socket

import pytest


def test_outbound_connection_is_blocked():
    with pytest.raises(RuntimeError, match="network access"):
        socket.create_connection(("example.com", 80), timeout=1)


def test_socket_connect_is_blocked_too():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        with pytest.raises(RuntimeError, match="network access"):
            sock.connect(("93.184.216.34", 80))


def test_error_names_the_host_that_was_attempted():
    with pytest.raises(RuntimeError, match="arbeitsagentur"):
        socket.create_connection(("rest.arbeitsagentur.de", 443), timeout=1)


def test_local_connections_are_still_allowed():
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)

    client = socket.create_connection(listener.getsockname(), timeout=1)

    client.close()
    listener.close()
