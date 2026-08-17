"""Starting the app the way she starts it: a double-click, not a command.

Everything here answers a question that only exists once the app leaves this
machine — which port is free, where `data/` belongs when there is no project
directory, and what the little console window says while the browser opens.
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path

# Where to start looking. 8000 is the port the CLI has always used, and the
# likeliest thing holding it is a JobFinder she already has open.
DEFAULT_PORT = 8000
# How many ports to try before giving up. Twenty is far past "something else is
# using 8000" and well short of scanning her machine.
PORT_TRIES = 20


class NoFreePort(Exception):
    """Every port we tried was taken — said in a sentence, not a stack trace."""


def start(
    *,
    root: Path | None = None,
    port: int = DEFAULT_PORT,
    open_browser_at_start: bool = True,
    serve=None,
    open_browser=None,
    pick_port=None,
) -> int:
    """Start the app the way `JobFinder.exe` starts it, and narrate it.

    The little console window is the only thing she sees before her browser
    opens, so it is written for her: where the app is, that the window has to
    stay open, and how to stop it. Nothing here prints a traceback — a launcher
    that fails with one has failed twice.
    """
    from jobfinder.config import Settings
    from jobfinder.web.app import SERVER_HOST, create_app

    serve = serve or _uvicorn_serve
    open_browser = open_browser or _open_browser
    pick_port = pick_port or choose_port

    settings = Settings.load(root or install_root())
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    print("JobFinder")
    print(f"  Your files are in {settings.data_dir}")

    try:
        chosen = pick_port(port, host=SERVER_HOST)
    except NoFreePort as exc:
        print(f"  {exc}")
        return 1

    url = f"http://{SERVER_HOST}:{chosen}"
    print(f"  Open {url} in your browser if it does not open by itself.")
    print("  Leave this window open while you use JobFinder — close this window to stop it.")

    def ready() -> None:
        if open_browser_at_start:
            open_browser(url)

    serve(create_app(settings), host=SERVER_HOST, port=chosen, on_ready=ready)
    return 0


def _open_browser(url: str) -> None:
    import webbrowser

    webbrowser.open(url)


def _uvicorn_serve(app, *, host: str, port: int, on_ready) -> None:
    """Run the server; `on_ready` fires once, as soon as the port answers."""
    from jobfinder.cli import _uvicorn_serve as serve

    serve(app, host=host, port=port, on_ready=on_ready)


def install_root() -> Path:
    """The directory `data/`, `.env` and `config.yaml` belong to.

    Frozen, that is the folder holding `JobFinder.exe`. PyInstaller unpacks the
    program itself into a temporary directory (`sys._MEIPASS`) and deletes it on
    exit, so anything resolved from the running module would take her database
    with it. Unfrozen, it is the working directory, exactly as the CLI has
    always treated it.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


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
