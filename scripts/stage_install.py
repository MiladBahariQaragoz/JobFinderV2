"""Assemble the folder that gets handed over.

    python scripts/build_exe.py
    python scripts/stage_install.py "C:\\Users\\Student\\JobFinder"

Copies into that folder:

- `dist/JobFinder.exe`;
- the provider keys from this checkout's `.env`, so the person using it never
  has to sign up for a language model or paste a key (only the variables
  JobFinder itself uses — everything else in a developer `.env` stays here);
- the work already done: the store, the CSVs and the answers already paid for
  from `data/`, plus `pool.yaml`, so she opens the app on 860 jobs and 357
  places to ring rather than on an empty list. `--no-data` hands over the app
  alone.

Anything already in the folder — a store, a `config.yaml`, a CV — is left
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
DATA = REPO_ROOT / "data"
CV = REPO_ROOT / "pool.yaml"


def main(argv: list[str]) -> int:
    if not argv:
        print("Where should it go?  python scripts/stage_install.py <folder>")
        return 1
    if not BUILT.exists():
        print(f"No build at {BUILT}. Run `python scripts/build_exe.py` first.")
        return 1

    env_file = ENV if ENV.exists() else None
    seed = DATA if "--no-data" not in argv and DATA.is_dir() else None
    cv = CV if "--no-data" not in argv and CV.exists() else None

    target = Path(argv[0])
    already_had_a_store = (target / "data" / "jobfinder.db").exists()
    stage_install(BUILT, target, env_file=env_file, seed_from=seed, cv=cv)

    print(f"Installed into {target}")
    print(f"  JobFinder.exe   {BUILT.stat().st_size / 1e6:.0f} MB")
    if env_file is None:
        print("  no .env found here, so it was handed over without keys")
    else:
        # Names only. A key's value has no business on a screen or in a log.
        names = [line.split("=", 1)[0] for line in shareable_env(ENV.read_text("utf-8")).split()]
        print(f"  .env            {len(names)} keys: {', '.join(sorted(names))}")

    if seed is None:
        print("  no data copied")
    elif already_had_a_store:
        print("  data            left alone — that folder already has a store in it")
    else:
        _describe(target / "data")
    if cv is not None:
        print(f"  pool.yaml       {'copied' if not already_had_a_store else 'left alone'}")

    print("\nDouble-click JobFinder.exe in that folder. Everything it writes stays there.")
    return 0


def _describe(data: Path) -> None:
    """What she will actually find in there, counted from the store itself."""
    import sqlite3

    database = data / "jobfinder.db"
    if not database.exists():
        return
    connection = sqlite3.connect(database)
    try:
        jobs = connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        explained = connection.execute("SELECT COUNT(DISTINCT job_id) FROM enrichment").fetchone()[
            0
        ]
        places = connection.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]
    finally:
        connection.close()
    size = sum(path.stat().st_size for path in data.iterdir() if path.is_file())
    print(
        f"  data            {jobs} jobs ({explained} explained), {places} places to call"
        f" — {size / 1e6:.1f} MB"
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
