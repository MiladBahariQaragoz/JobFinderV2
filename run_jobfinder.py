"""What `JobFinder.exe` runs: the launcher, and nothing else.

PyInstaller needs a script rather than an entry point, and this is deliberately
the thinnest one that can exist — everything it would do is in `launch.start`,
which `jobfinder serve` calls too, so the packaged app and the developed app are
the same code path.
"""

from __future__ import annotations

import multiprocessing
import sys

from jobfinder.launch import entry

if __name__ == "__main__":
    # Frozen Windows builds re-execute this file for every child process; without
    # this line a program that ever spawns one starts itself again instead.
    multiprocessing.freeze_support()
    sys.exit(entry())
