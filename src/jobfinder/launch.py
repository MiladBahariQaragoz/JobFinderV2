"""Starting the app the way she starts it: a double-click, not a command.

Everything here answers a question that only exists once the app leaves this
machine — which port is free, where `data/` belongs when there is no project
directory, and what the little console window says while the browser opens.
"""

from __future__ import annotations

import socket

# Where to start looking. 8000 is the port the CLI has always used, and the
# likeliest thing holding it is a JobFinder she already has open.
DEFAULT_PORT = 8000
# How many ports to try before giving up. Twenty is far past "something else is
# using 8000" and well short of scanning her machine.
PORT_TRIES = 20


class NoFreePort(Exception):
    """Every port we tried was taken — said in a sentence, not a stack trace."""


def choose_port(preferred: int = DEFAULT_PORT, *, host: str = "127.0.0.1", tries: int = PORT_TRIES):
    """The first free port at or after `preferred`.

    Binding is the only honest test: a port that answered a moment ago can be
    taken by the time anyone acts on the answer, so we take it ourselves and let
    it go, rather than asking whether it is free.
    """
    for offset in range(tries):
        port = preferred + offset
        # Deliberately no SO_REUSEADDR: on Windows it lets a bind succeed on a
        # port another socket already holds, which would report a busy port as
        # free — the one thing this function exists to get right.
        with socket.socket() as probe:
            try:
                probe.bind((host, port))
            except OSError:
                continue
        return port
    raise NoFreePort(
        f"Ports {preferred} to {preferred + tries - 1} are all in use. "
        "JobFinder may already be running — look for its window before starting another."
    )
