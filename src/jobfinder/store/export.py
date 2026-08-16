"""CSV exports — §5's column sets, §5's encoding rules, §9's atomic replace.

Written to `*.tmp` and `os.replace`d into place, so a crash mid-export always
leaves the previous good CSV. The status column joins in from her table; the
job rows themselves are raw source facts, never LLM output.
"""

from __future__ import annotations

import csv
import os
import sqlite3
from pathlib import Path

COLUMNS = [
    "job_id",
    "source",
    "source_id",
    "dedupe_key",
    "title",
    "company",
    "city",
    "plz",
    "lat",
    "lon",
    "employment_type_raw",
    "is_minijob",
    "is_parttime",
    "is_fulltime",
    "is_internship",
    "is_werkstudent",
    "homeoffice",
    "published_at",
    "apply_url",
    "source_url",
    "also_seen_on",
    "has_description",
    "content_hash",
    "first_seen_at",
    "last_seen_at",
    "status",
]

# Columns before `status` come straight from `jobs`; `status` joins in so a
# missing status row still reads 'new' in the export.
_SELECT = """
SELECT {columns}, COALESCE(s.status, 'new')
FROM jobs j
LEFT JOIN status s ON s.job_id = j.job_id
ORDER BY j.job_id
""".format(columns=", ".join(f"j.{name}" for name in COLUMNS[:-1]))


def export_jobs_init(connection: sqlite3.Connection, path: Path) -> int:
    """Write jobs-init.csv atomically; returns the number of job rows."""
    path = Path(path)
    target_tmp = path.with_name(path.name + ".tmp")
    target_tmp.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    try:
        # utf-8-sig + newline="" — or Excel mangles every umlaut (§5).
        with open(target_tmp, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(COLUMNS)
            for row in connection.execute(_SELECT):
                writer.writerow(row)
                written += 1
    except BaseException:
        target_tmp.unlink(missing_ok=True)
        raise
    os.replace(target_tmp, path)
    return written


# --- jobs-enriched.csv (Phase 7) ---------------------------------------------


def append_enriched_row(path: Path, row: list) -> None:
    """Add one enriched job to the CSV the moment its answer lands (§9).

    Appending rather than re-exporting is what lets her open the file while a
    run is still going, and what makes an interrupted run leave a complete
    readable file instead of nothing. The header is written once, with the file.
    """
    from jobfinder.enrich.fields import ENRICHED_COLUMNS

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fresh = not path.exists() or path.stat().st_size == 0
    # utf-8-sig only on creation — a BOM in the middle of a file is a stray
    # "ï»¿" in her spreadsheet.
    encoding = "utf-8-sig" if fresh else "utf-8"
    with open(path, "a", encoding=encoding, newline="") as handle:
        writer = csv.writer(handle)
        if fresh:
            writer.writerow(ENRICHED_COLUMNS)
        writer.writerow(row)


def export_jobs_enriched(connection: sqlite3.Connection, path: Path, prompt_version: str) -> int:
    """Rewrite jobs-enriched.csv from the database; returns the rows written.

    The appended file holds arrival order and, after a `--force` re-run, the
    same job twice. This is the tidy-up pass: one row per job, sorted, written
    atomically so a crash leaves the previous good file.
    """
    from jobfinder.enrich.fields import ENRICHED_COLUMNS, enriched_row
    from jobfinder.store.enrichment import stored_enrichments

    path = Path(path)
    target_tmp = path.with_name(path.name + ".tmp")
    target_tmp.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    try:
        with open(target_tmp, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(ENRICHED_COLUMNS)
            for stored in stored_enrichments(connection, prompt_version):
                writer.writerow(
                    enriched_row(
                        stored.answer,
                        job_id=stored.job_id,
                        prompt_version=prompt_version,
                        provider_used=stored.provider_used,
                        enriched_at=stored.enriched_at,
                    )
                )
                written += 1
    except BaseException:
        target_tmp.unlink(missing_ok=True)
        raise
    try:
        os.replace(target_tmp, path)
    except BaseException:
        target_tmp.unlink(missing_ok=True)
        raise
    return written
