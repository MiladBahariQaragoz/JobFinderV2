"""Connections and schema for the one database her data lives in.

Every connection opens WAL + synchronous=NORMAL (MASTER_PLAN §9 — a hard kill
must never corrupt the file), and every migration is idempotent so reopening
the database is always safe. The tables follow §5's data contracts; columns
match the `jobs-init.csv` export exactly so the export is a plain projection.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 8

# How long a writer waits for another writer before giving up (§8 rule 2).
# Enrichment is meant to run while a search is still storing jobs, and WAL
# lets readers through but still takes turns between writers. The driver
# happens to default to 5 s; a rule her data depends on is stated here rather
# than inherited, with room for a laptop that is busy doing something else.
BUSY_TIMEOUT_MS = 15_000

# The timeout in force while a connection is only setting itself up. The two
# durability pragmas can block on a database still in rollback-journal mode,
# and waiting the full BUSY_TIMEOUT_MS to find that out would make opening a
# second connection feel like a hang. Losing that race is handled below.
SETUP_TIMEOUT_MS = 500

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
    -- v7: the same date, comparable. `published_at` keeps whatever the source
    -- said (three shapes across five sources); this one is always YYYY-MM-DD,
    -- because "posted within a week" cannot be asked of a mixed column.
    published_on        TEXT,
    apply_url           TEXT,
    source_url          TEXT,
    also_seen_on        TEXT,
    has_description     INTEGER NOT NULL DEFAULT 0,
    content_hash        TEXT,
    first_seen_at       TEXT NOT NULL,
    last_seen_at        TEXT NOT NULL
);

-- Every stored posting is looked up by `dedupe_key` once (the cross-source
-- merge), so this index is what keeps a run linear instead of quadratic.
CREATE INDEX IF NOT EXISTS jobs_dedupe_key ON jobs(dedupe_key);

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
    -- v5: the hash of the ad text this answer was read from. Without it the
    -- skip rule can only ask "already enriched?", never "still the same ad?".
    content_hash   TEXT,
    -- v5: who answered, when the runner could tell. §5's CSV asks for it.
    provider_used  TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (job_id, prompt_version)
);

-- The only table she writes to.
CREATE TABLE IF NOT EXISTS status (
    job_id     TEXT PRIMARY KEY REFERENCES jobs(job_id),
    status     TEXT NOT NULL DEFAULT 'new',
    notes      TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- General-work places from Overpass, Phase 9. Created in v1 so the schema was
-- complete from day one; filled in for the first time in v8.
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
    -- v8: the sentence behind the score, where the place is, and the two German
    -- texts once a model has written them. Listed here for a fresh database and
    -- in ADDED_COLUMNS for one that already exists.
    score_reason        TEXT,
    lat                 REAL,
    lon                 REAL,
    script              TEXT,
    email_draft         TEXT,
    osm_id              TEXT,
    first_seen_at       TEXT NOT NULL DEFAULT (datetime('now')),
    last_contacted_at   TEXT,
    outcome             TEXT,
    notes               TEXT
);

-- v8 (Phase 9): `osm_id` is the real identity of a place — `contact_id` is a
-- surrogate. Without this index a second run inserts every place again, and a
-- list she has already worked through becomes untrustworthy.
CREATE UNIQUE INDEX IF NOT EXISTS contacts_osm_id ON contacts(osm_id);

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

-- v6 (Phase 8): one row per source per search run, written as pages land.
-- §10 promises progress read from the database, so the per-source lines the
-- CLI prints ("Bundesagentur — 42 found, 7 new") live here too, and a browser
-- reload mid-run shows the same state.
CREATE TABLE IF NOT EXISTS run_sources (
    run_id          INTEGER NOT NULL REFERENCES runs(id),
    source          TEXT NOT NULL,
    found_count     INTEGER NOT NULL DEFAULT 0,
    new_count       INTEGER NOT NULL DEFAULT 0,
    duplicate_count INTEGER NOT NULL DEFAULT 0,
    state           TEXT NOT NULL DEFAULT 'running',
    last_event_at   TEXT,
    PRIMARY KEY (run_id, source)
);

-- Per-source cursors so a resumed search re-enters at the right page.
CREATE TABLE IF NOT EXISTS source_state (
    source               TEXT PRIMARY KEY,
    query_hash           TEXT,
    last_query_index     INTEGER NOT NULL DEFAULT 0,
    last_completed_page  INTEGER NOT NULL DEFAULT 0,
    last_success_at      TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    cooldown_until       TEXT,
    last_error           TEXT
);
"""


# Columns added after a database was already created. `CREATE TABLE IF NOT
# EXISTS` cannot evolve a live table, so each of these needs an ALTER path —
# one more reason the list stays short.
ADDED_COLUMNS = {
    "jobs": {
        # v3 (Phase 5): the other sites the same ad was seen on, comma-joined.
        "also_seen_on": "TEXT",
        # v7: the comparable posting date. Her database already holds hundreds
        # of rows, so it arrives by ALTER and is backfilled below.
        "published_on": "TEXT",
    },
    "source_state": {
        # v4 (Phase 6): what the source said the last time it failed, so the
        # summary can name it instead of saying "a source failed".
        "last_error": "TEXT",
    },
    "enrichment": {
        # v5 (Phase 7): the two columns the skip rule and §5's CSV need. Her
        # database already holds hundreds of jobs, so both arrive by ALTER.
        "content_hash": "TEXT",
        "provider_used": "TEXT NOT NULL DEFAULT ''",
    },
    "status": {
        # v6 (Phase 8): the day she applied — the job page's "you applied on
        # …" line reads it, set once, never rewritten.
        "applied_on": "TEXT",
    },
    "runs": {
        # v6 (Phase 8): answers landed in an enrichment run, journalled per
        # answer so the web app's progress panel can read it mid-run.
        "enriched_count": "INTEGER NOT NULL DEFAULT 0",
        # v8 (Phase 9): places found by a contacts run, for the same reason.
        "contacts_count": "INTEGER NOT NULL DEFAULT 0",
    },
    "contacts": {
        # v8 (Phase 9): why a place is where it is in the list, in one English
        # sentence — she should be able to ask, and get more than a number.
        "score_reason": "TEXT",
        # v8: where it is, so the page can say how far she would be travelling.
        "lat": "REAL",
        "lon": "REAL",
        # v8: the German phone script and the email draft, once written.
        "script": "TEXT",
        "email_draft": "TEXT",
    },
}


def connect(db_path: Path) -> sqlite3.Connection:
    """Open the database with §9's durability settings, creating directories.

    One connection per thread — sqlite3's own guard enforces it. A worker that
    runs alongside a search (§8 rule 2) calls this again rather than sharing.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    # Short first, so a lost race costs a moment rather than BUSY_TIMEOUT_MS.
    connection.execute(f"PRAGMA busy_timeout = {SETUP_TIMEOUT_MS}")
    _apply_durability(connection)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    return connection


def _apply_durability(connection: sqlite3.Connection) -> None:
    """Set WAL and synchronous, tolerating a database another writer holds.

    Both of these need a lock while the file is still in rollback-journal mode,
    and `search --enrich` opens two connections at once — so on a first run,
    before anything has switched the file to WAL, one of them can lose that
    race. Raising there would break the one run that must work.

    Losing is survivable and raising is not: the connection that won sets WAL
    for the whole file, every later connection re-applies these, and a
    connection that never manages falls back to the rollback journal — slower,
    not unsafe.
    """
    for pragma in ("journal_mode = WAL", "synchronous = NORMAL"):
        try:
            connection.execute(f"PRAGMA {pragma}")
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
                raise


def migrate(connection: sqlite3.Connection) -> None:
    """Bring the database up to SCHEMA_VERSION. Safe to run on every open."""
    was = int(connection.execute("PRAGMA user_version").fetchone()[0])
    connection.executescript(_SCHEMA)
    _add_missing_columns(connection)
    if was < 3:
        _rebuild_dedupe_keys(connection)
    if was < 7:
        _backfill_published_on(connection)
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    connection.commit()


def _backfill_published_on(connection: sqlite3.Connection) -> None:
    """v7 derives a comparable date — the rows already stored need theirs.

    Without this, a "posted within a week" filter would answer for jobs found
    after the migration and silently exclude every job found before it. The
    derivation is the one function `RawPosting` uses, so an old row and a new
    row can never disagree about what day an ad was posted.
    """
    from jobfinder.dates import published_on

    rows = connection.execute(
        "SELECT job_id, published_at FROM jobs WHERE published_on IS NULL"
    ).fetchall()
    for job_id, published_at in rows:
        derived = published_on(published_at)
        if derived is not None:
            connection.execute(
                "UPDATE jobs SET published_on = ? WHERE job_id = ?", (derived, job_id)
            )


def _rebuild_dedupe_keys(connection: sqlite3.Connection) -> None:
    """v3 keys the location on the city, not the plz — old rows must catch up.

    A key left in the v2 shape can never match the same ad from a source that
    reports no postcode, so the cross-source merge would be dead for every job
    stored before this migration.
    """
    from jobfinder.sources.base import make_dedupe_key

    rows = connection.execute("SELECT job_id, title, company, city FROM jobs").fetchall()
    for job_id, title, company, city in rows:
        connection.execute(
            "UPDATE jobs SET dedupe_key = ? WHERE job_id = ?",
            (make_dedupe_key(title=title, company=company, city=city), job_id),
        )


def _add_missing_columns(connection: sqlite3.Connection) -> None:
    """Evolve tables created before a column existed — idempotent by check."""
    for table, columns in ADDED_COLUMNS.items():
        present = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        for column, ddl in columns.items():
            if column not in present:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
