"""The launcher: the port it picks, and where it decides the data lives.

Both questions only have wrong answers on her machine — a port already taken by
something else, and a `data/` directory that would otherwise land inside a
temporary folder PyInstaller deletes on exit.
"""

from __future__ import annotations

import socket

import pytest

from jobfinder.config import Settings
from jobfinder.launch import NoFreePort, choose_port, install_root

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


# -- where the data lives ------------------------------------------------------


def test_the_install_root_is_the_working_directory_when_running_from_source(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    assert install_root() == tmp_path


def test_the_install_root_is_beside_the_exe_when_frozen(tmp_path, monkeypatch):
    installed = tmp_path / "JobFinder"
    installed.mkdir()
    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr("sys.executable", str(installed / "JobFinder.exe"))

    assert install_root() == installed


def test_data_dir_resolves_next_to_the_exe_when_frozen(tmp_path, monkeypatch):
    """The point of the whole function: PyInstaller unpacks itself into a temp
    directory it deletes on exit, so a `data/` resolved from the running module
    would take her database with it."""
    installed = tmp_path / "JobFinder"
    installed.mkdir()
    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr("sys.executable", str(installed / "JobFinder.exe"))
    monkeypatch.setattr("sys._MEIPASS", str(tmp_path / "_MEI12345"), raising=False)

    settings = Settings(project_root=install_root())

    assert settings.data_dir == installed / "data"
    assert settings.db_path == installed / "data" / "jobfinder.db"
