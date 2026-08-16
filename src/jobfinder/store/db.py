"""Connections and schema for the one database her data lives in.

Every connection opens WAL + synchronous=NORMAL (MASTER_PLAN §9 — a hard kill
must never corrupt the file), and every migration is idempotent so reopening
the database is always safe. The tables follow §5's data contracts; columns
match the `jobs-init.csv` export exactly so the export is a plain projection.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id              TEXT PRIMARY KEY,
    source              TEXT NOT NULL,
    source_id           TEXT NOT NULL,
    dedupe_key          TEXT NOT NULL,
    title               TEXT NOT NULL,
    company             TEXT,
    city                TEXT,
    plz                 TEXT,
    lat                 REAL,
    lon                 REAL,
    employment_type_raw TEXT,
    is_minijob          INTEGER NOT NULL DEFAULT 0,
    is_parttime         INTEGER NOT NULL DEFAULT 0,
    is_fulltime         INTEGER NOT NULL DEFAULT 0,
    is_internship       INTEGER NOT NULL DEFAULT 0,
    is_werkstudent      INTEGER NOT NULL DEFAULT 0,
    homeoffice          INTEGER NOT NULL DEFAULT 0,
    published_at        TEXT,
    apply_url           TEXT,
    source_url          TEXT,
    has_description     INTEGER NOT NULL DEFAULT 0,
    content_hash        TEXT,
    first_seen_at       TEXT NOT NULL,
    last_seen_at        TEXT NOT NULL
);

-- Full German ad text, kept out of `jobs` so exports stay small.
CREATE TABLE IF NOT EXISTS job_descriptions (
    job_id      TEXT PRIMARY KEY REFERENCES jobs(job_id),
    description TEXT NOT NULL,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- LLM-derived fields, Phase 7. Re-enrichment appends a new prompt_version,
-- never destroys the old answer.
CREATE TABLE IF NOT EXISTS enrichment (
    job_id         TEXT NOT NULL REFERENCES jobs(job_id),
    prompt_version TEXT NOT NULL,
    answer         TEXT NOT NULL,
    enriched_at    TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (job_id, prompt_version)
);

-- The only table she writes to.
CREATE TABLE IF NOT EXISTS status (
    job_id     TEXT PRIMARY KEY REFERENCES jobs(job_id),
    status     TEXT NOT NULL DEFAULT 'new',
    notes      TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- General-work places from Overpass, Phase 9. Created now so the schema is
-- complete from day one.
CREATE TABLE IF NOT EXISTS contacts (
    contact_id          INTEGER PRIMARY KEY,
    name                TEXT NOT NULL,
    kind                TEXT,
    city                TEXT,
    street              TEXT,
    phone               TEXT,
    email               TEXT,
    website             TEXT,
    back_of_house_score REAL,
    osm_id              TEXT,
    first_seen_at       TEXT NOT NULL DEFAULT (datetime('now')),
    last_contacted_at   TEXT,
    outcome             TEXT,
    notes               TEXT
);

-- One row per search/enrich/contacts run (§9 run journal).
CREATE TABLE IF NOT EXISTS runs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    kind             TEXT NOT NULL,
    spec             TEXT,
    sources          TEXT,
    state            TEXT NOT NULL,
    started_at       TEXT NOT NULL DEFAULT (datetime('now')),
    last_progress_at TEXT,
    finished_at      TEXT,
    found_count      INTEGER NOT NULL DEFAULT 0,
    new_count        INTEGER NOT NULL DEFAULT 0,
    duplicate_count  INTEGER NOT NULL DEFAULT 0,
    errors           TEXT
);

-- Per-source cursors so a resumed search re-enters at the right page.
CREATE TABLE IF NOT EXISTS source_state (
    source               TEXT PRIMARY KEY,
    query_hash           TEXT,
    last_completed_page  INTEGER NOT NULL DEFAULT 0,
    last_success_at      TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    cooldown_until       TEXT
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    """Open the database with §9's durability settings, creating directories."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def migrate(connection: sqlite3.Connection) -> None:
    """Bring the database up to SCHEMA_VERSION. Safe to run on every open."""
    connection.executescript(_SCHEMA)
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    connection.commit()
