"""The launcher: the port it picks, and where it decides the data lives.

Both questions only have wrong answers on her machine — a port already taken by
something else, and a `data/` directory that would otherwise land inside a
temporary folder PyInstaller deletes on exit.
"""

from __future__ import annotations

import socket

import pytest

from jobfinder.launch import NoFreePort, choose_port

HOST = "127.0.0.1"


def test_the_preferred_port_is_used_when_it_is_free():
    with socket.socket() as probe:
        probe.bind((HOST, 0))
        free_port = probe.getsockname()[1]
    # The probe is closed, so the port it borrowed is free again.

    assert choose_port(free_port, host=HOST) == free_port


def test_the_next_port_is_chosen_when_the_preferred_one_is_busy():
    with socket.socket() as taken:
        taken.bind((HOST, 0))
        taken.listen()
        busy_port = taken.getsockname()[1]

        chosen = choose_port(busy_port, host=HOST)

    assert chosen != busy_port
    assert chosen > busy_port


def test_a_wall_of_busy_ports_is_refused_with_a_sentence():
    with socket.socket() as taken:
        taken.bind((HOST, 0))
        taken.listen()
        busy_port = taken.getsockname()[1]

        with pytest.raises(NoFreePort) as refused:
            choose_port(busy_port, host=HOST, tries=1)

    assert str(busy_port) in str(refused.value)
