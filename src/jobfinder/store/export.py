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
