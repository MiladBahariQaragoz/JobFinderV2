"""Assemble the folder that gets handed over.

    python scripts/build_exe.py
    python scripts/stage_install.py "C:\\Users\\Student\\JobFinder"

Copies `dist/JobFinder.exe` into that folder, and the provider keys from this
checkout's `.env` beside it, so the person using it never has to sign up for a
language model or paste a key. Only the keys JobFinder itself needs are copied;
everything else in the developer `.env` stays here.

Anything already in the folder — `data/`, `config.yaml`, her CV — is left
exactly as it is, so this is also how a new build is installed over an old one.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from jobfinder.packaging import shareable_env, stage_install  # noqa: E402

BUILT = REPO_ROOT / "dist" / "JobFinder.exe"
ENV = REPO_ROOT / ".env"


def main(argv: list[str]) -> int:
    if not argv:
        print("Where should it go?  python scripts/stage_install.py <folder>")
        return 1
    if not BUILT.exists():
        print(f"No build at {BUILT}. Run `python scripts/build_exe.py` first.")
        return 1

    env_file = ENV if ENV.exists() else None
    target = stage_install(BUILT, Path(argv[0]), env_file=env_file)

    print(f"Installed into {target}")
    print(f"  JobFinder.exe   {BUILT.stat().st_size / 1e6:.0f} MB")
    if env_file is None:
        print("  no .env found here, so it was handed over without keys")
    else:
        # Names only. A key's value has no business on a screen or in a log.
        names = [line.split("=", 1)[0] for line in shareable_env(ENV.read_text("utf-8")).split()]
        print(f"  .env            {len(names)} keys: {', '.join(sorted(names))}")
    print("\nDouble-click JobFinder.exe in that folder. Everything it writes stays there.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
