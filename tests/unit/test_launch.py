"""The launcher: the port it picks, and where it decides the data lives.

Both questions only have wrong answers on her machine — a port already taken by
something else, and a `data/` directory that would otherwise land inside a
temporary folder PyInstaller deletes on exit.
"""

from __future__ import annotations

import socket

import pytest

from jobfinder.config import Settings
from jobfinder.launch import (
    DEFAULT_PORT,
    NoFreePort,
    choose_port,
    entry,
    install_root,
    start,
)

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


# -- the console window she actually sees --------------------------------------


class Recorder:
    """What the launcher would have done, without doing any of it."""

    def __init__(self):
        self.served = None
        self.opened = []

    def serve(self, app, *, host, port, on_ready):
        self.served = (host, port)
        on_ready()

    def open_browser(self, url):
        self.opened.append(url)


def test_the_launcher_says_which_address_to_open(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    recorder = Recorder()

    start(root=tmp_path, serve=recorder.serve, open_browser=recorder.open_browser)

    out = capsys.readouterr().out
    host, port = recorder.served
    assert f"http://{host}:{port}" in out


def test_the_launcher_opens_the_browser_at_the_port_it_got(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    recorder = Recorder()

    start(root=tmp_path, serve=recorder.serve, open_browser=recorder.open_browser)

    _host, port = recorder.served
    assert recorder.opened == [f"http://127.0.0.1:{port}"]


def test_the_launcher_says_how_to_stop_it(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    recorder = Recorder()

    start(root=tmp_path, serve=recorder.serve, open_browser=recorder.open_browser)

    assert "closing it stops the app" in capsys.readouterr().out.lower()


def test_the_launcher_creates_the_data_directory_when_it_is_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    recorder = Recorder()

    start(root=tmp_path, serve=recorder.serve, open_browser=recorder.open_browser)

    assert (tmp_path / "data").is_dir()


def test_the_launcher_says_something_readable_when_every_port_is_taken(
    tmp_path, capsys, monkeypatch
):
    monkeypatch.chdir(tmp_path)

    def no_ports(*args, **kwargs):
        raise NoFreePort("Ports 8000 to 8019 are all in use.")

    exit_code = start(
        root=tmp_path,
        serve=lambda *a, **k: None,
        open_browser=lambda url: None,
        pick_port=no_ports,
    )

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "8000" in out
    assert "Traceback" not in out


def test_the_launcher_does_not_open_a_browser_when_asked_not_to(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    recorder = Recorder()

    start(
        root=tmp_path,
        serve=recorder.serve,
        open_browser=recorder.open_browser,
        open_browser_at_start=False,
    )

    assert recorder.opened == []


class TestTheExeEntryPoint:
    """`JobFinder.exe --port 8123 --no-browser` — the two flags a build smoke
    test needs, and nothing else. She double-clicks and passes none of them."""

    def test_no_arguments_means_the_default_port_and_a_browser(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        seen = {}

        def fake_start(**kwargs):
            seen.update(kwargs)
            return 0

        monkeypatch.setattr("jobfinder.launch.start", fake_start)
        assert entry([]) == 0
        assert seen["port"] == DEFAULT_PORT
        assert seen["open_browser_at_start"] is True

    def test_the_flags_reach_the_launcher(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        seen = {}

        def fake_start(**kwargs):
            seen.update(kwargs)
            return 0

        monkeypatch.setattr("jobfinder.launch.start", fake_start)
        entry(["--port", "8123", "--no-browser"])
        assert seen["port"] == 8123
        assert seen["open_browser_at_start"] is False

    def test_an_unknown_flag_is_ignored_rather_than_fatal(self, tmp_path, monkeypatch):
        """A double-click can carry a stray argument from a shortcut, and the
        program exiting with "unrecognized arguments" would be the whole app
        lost to a typo in a shortcut she did not make."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("jobfinder.launch.start", lambda **kwargs: 0)

        assert entry(["--nonsense"]) == 0


def test_the_console_lines_are_plain_ascii(tmp_path, capsys, monkeypatch):
    """A Windows console is not always UTF-8. Under the older code pages an em
    dash is either mojibake or a crash inside `print` — and the console window
    is the one surface she cannot reload."""
    monkeypatch.chdir(tmp_path)
    recorder = Recorder()

    start(root=tmp_path, serve=recorder.serve, open_browser=recorder.open_browser)

    out = capsys.readouterr().out
    assert out.isascii(), f"non-ASCII in the console output: {out!r}"
