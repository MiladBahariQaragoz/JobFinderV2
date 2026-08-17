"""A copy of her work, taken before every run.

A run writes to the database and rewrites the CSVs. Almost nothing can go wrong
there — §9 makes every write land as it happens — but "almost nothing" is not
what you want standing between someone and eight hundred job postings they
cannot re-fetch, some of which cost free-tier LLM calls to explain.

**What is copied is what cannot be fetched again.** Measured on her real
`data/`: 66 MB, of which 63 MB is `http-cache/` — pages any run can ask for
again. The database, the three CSVs and the LLM cache are 3.5 MB and are the
whole of what a bad run could cost. Copying the directory would be nineteen
times the bytes, five times over, for the same protection.

**A backup never fails a run.** A full disk, a locked file, a folder someone
made read-only: each of those is a reason to carry on without a backup, not a
reason to refuse to search.
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jobfinder.config import Settings

# How many to keep. Five is what MASTER_PLAN asks for: enough to step back past
# a bad run she did not notice at once, and 18 MB rather than 330.
BACKUPS_KEPT = 5


def backup_dir(settings: Settings) -> Path:
    return settings.data_dir / "backups"


def _worth_copying(settings: Settings) -> list[Path]:
    """The files a run could damage and no run could recreate."""
    candidates = [
        settings.db_path,
        settings.jobs_init_csv,
        settings.jobs_enriched_csv,
        settings.contacts_csv,
        settings.llm_cache_path,
        settings.pool_state_path,
        settings.suggested_roles_path,
    ]
    return [path for path in candidates if path.exists()]


def back_up_data(settings: Settings, *, stamp: str | None = None) -> Path | None:
    """Copy the irreplaceable files into `data/backups/<stamp>/`, keep five.

    Returns where they went, or None when there was nothing to copy or the copy
    could not be made. Neither of those is an error worth stopping a run for.
    """
    files = _worth_copying(settings)
    if not files:
        return None

    stamp = stamp or datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    destination = backup_dir(settings) / stamp
    try:
        destination.mkdir(parents=True, exist_ok=True)
        for path in files:
            shutil.copy2(path, destination / path.name)
    except OSError:
        # No backup is a worse day than a backup, and a better day than a run
        # that refused to start because a disk was full.
        shutil.rmtree(destination, ignore_errors=True)
        return None

    _rotate(settings)
    return destination


def _rotate(settings: Settings) -> None:
    """Keep the newest `BACKUPS_KEPT`, drop the rest.

    The stamp sorts chronologically as text, which is the reason it is written
    that way round.
    """
    root = backup_dir(settings)
    existing = sorted((path for path in root.iterdir() if path.is_dir()), key=lambda p: p.name)
    for path in existing[:-BACKUPS_KEPT]:
        shutil.rmtree(path, ignore_errors=True)
