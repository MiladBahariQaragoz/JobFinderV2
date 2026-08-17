"""Build `JobFinder.exe` from this checkout.

    python scripts/build_exe.py

PyInstaller is a build-time tool, not a dependency of the app: it lives in the
`dev` extras, so a machine that only runs JobFinder never installs it. What
goes into the bundle is decided in `jobfinder/packaging.py`, where the tests
can read it.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller is not installed. Install the dev extras first:")
        print("  pip install -e .[dev]")
        return 1

    print("Building JobFinder.exe — this takes a few minutes.")
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "JobFinder.spec"],
        cwd=REPO_ROOT,
        check=False,
    )
    if result.returncode != 0:
        print("The build failed. The output above says where.")
        return result.returncode

    built = REPO_ROOT / "dist" / "JobFinder.exe"
    print(f"\nBuilt: {built}")
    print(f"       {built.stat().st_size / 1e6:.0f} MB")
    print("\nTo install it for her: copy that one file into a folder of its own.")
    print("Everything it writes — data/, config.yaml, .env — lands beside it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
