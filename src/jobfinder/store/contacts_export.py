"""`contacts.csv` — the call-list as a file she can print and hold.

§5's column set, §5's encoding rules (`utf-8-sig`, `newline=""` — or Excel
mangles every umlaut), and §9's atomic replace: written to `*.tmp` and moved
into place, so a crash mid-export always leaves the previous good file.

Unlike `jobs-enriched.csv` this is a full re-export rather than an append. The
call-list is small (tens of rows, not hundreds), and every row can change after
she rings someone — an append-only file would hold four versions of the bakery.
"""

from __future__ import annotations

import csv
import os
import sqlite3
from pathlib import Path

CONTACT_COLUMNS = [
    "contact_id",
    "name",
    "kind",
    "city",
    "street",
    "phone",
    "email",
    "website",
    "back_of_house_score",
    "osm_id",
    "first_seen_at",
    "last_contacted_at",
    "outcome",
    "notes",
]

# Best first: the same order the page uses, so the printout and the screen agree.
_SELECT = (
    f"SELECT {', '.join(CONTACT_COLUMNS)} FROM contacts"
    " ORDER BY back_of_house_score DESC, name COLLATE NOCASE"
)


def export_contacts(connection: sqlite3.Connection, path: Path) -> int:
    """Write contacts.csv atomically; returns the number of places written."""
    path = Path(path)
    target_tmp = path.with_name(path.name + ".tmp")
    target_tmp.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    try:
        with open(target_tmp, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(CONTACT_COLUMNS)
            for row in connection.execute(_SELECT):
                # A NULL must reach her spreadsheet as an empty cell, never as
                # the word "None".
                writer.writerow(["" if value is None else value for value in row])
                written += 1
    except BaseException:
        target_tmp.unlink(missing_ok=True)
        raise
    os.replace(target_tmp, path)
    return written
