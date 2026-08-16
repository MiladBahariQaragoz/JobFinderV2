"""Upsert semantics: the §5 re-run rule, in code.

A search that finds a job already stored updates `last_seen_at` and nothing
else — not the description, not first_seen, not her status. That is what stops
the app from re-doing work (and re-spending her LLM quota) every morning.
"""

from __future__ import annotations

import dataclasses

import pytest

from jobfinder.sources.arbeitnow import parse_entry
from jobfinder.sources.base import RawPosting
from jobfinder.store.db import connect, migrate
from jobfinder.store.jobs import upsert_job


@pytest.fixture
def db(tmp_path):
    connection = connect(tmp_path / "jobfinder.db")
    migrate(connection)
    yield connection
    connection.close()


def posting(**overrides) -> RawPosting:
    values = dict(
        job_id="BA:11119-4913285274-S",
        source="BA",
        source_id="11119-4913285274-S",
        title="Werkstudent Küche (m/w/d)",
        company="Bäckerei Müller & Söhne",
        city="Ingolstadt, Donau",  # the form the BA really answers with
        plz="85051",
        description="Wir suchen eine Kraft für das Wochenende an unserer Theke.",
    )
    values.update(overrides)
    return RawPosting(**values)


def job_row(connection, column: str, job_id: str = "BA:11119-4913285274-S"):
    sql = f"SELECT {column} FROM jobs WHERE job_id = ?"
    return connection.execute(sql, (job_id,)).fetchone()[0]


def status_row(connection, columns: str, job_id: str):
    sql = f"SELECT {columns} FROM status WHERE job_id = ?"
    return connection.execute(sql, (job_id,)).fetchone()


class TestUpsertNew:
    def test_new_posting_is_inserted_and_reported_as_new(self, db):
        outcome = upsert_job(db, posting(), now="2026-08-16 08:00:00")
        assert outcome == "new"
        assert job_row(db, "title") == "Werkstudent Küche (m/w/d)"

    def test_first_seen_equals_last_seen_on_insert(self, db):
        upsert_job(db, posting(), now="2026-08-16 08:00:00")
        assert job_row(db, "first_seen_at") == "2026-08-16 08:00:00"
        assert job_row(db, "last_seen_at") == "2026-08-16 08:00:00"

    def test_status_row_defaults_to_new(self, db):
        upsert_job(db, posting(), now="2026-08-16 08:00:00")
        status = status_row(db, "status", posting().job_id)
        assert status[0] == "new"

    def test_description_lands_in_its_own_table_with_hash_in_jobs(self, db):
        upsert_job(db, posting(), now="2026-08-16 08:00:00")
        description = db.execute(
            "SELECT description FROM job_descriptions WHERE job_id = ?", (posting().job_id,)
        ).fetchone()[0]
        assert description == "Wir suchen eine Kraft für das Wochenende an unserer Theke."
        assert job_row(db, "has_description") == 1
        assert job_row(db, "content_hash")  # sha1 of the ad text

    def test_posting_without_description_stores_none_cleanly(self, db):
        upsert_job(db, posting(description=None), now="2026-08-16 08:00:00")
        assert job_row(db, "has_description") == 0
        assert job_row(db, "content_hash") is None
        rows = db.execute("SELECT COUNT(*) FROM job_descriptions").fetchone()[0]
        assert rows == 0


class TestRerunRule:
    def test_same_job_twice_leaves_one_row(self, db):
        upsert_job(db, posting(), now="2026-08-16 08:00:00")
        outcome = upsert_job(db, posting(), now="2026-08-16 09:00:00")
        assert outcome == "duplicate"
        count = db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        assert count == 1

    def test_only_last_seen_moves(self, db):
        upsert_job(db, posting(), now="2026-08-16 08:00:00")
        upsert_job(db, posting(title="A different title entirely"), now="2026-08-16 09:00:00")
        assert job_row(db, "first_seen_at") == "2026-08-16 08:00:00"
        assert job_row(db, "last_seen_at") == "2026-08-16 09:00:00"
        assert job_row(db, "title") == "Werkstudent Küche (m/w/d)"  # untouched

    def test_description_is_not_overwritten_on_rerun(self, db):
        upsert_job(db, posting(), now="2026-08-16 08:00:00")
        upsert_job(db, posting(description="Completely different text."), now="2026-08-16 09:00:00")
        description = db.execute(
            "SELECT description FROM job_descriptions WHERE job_id = ?", (posting().job_id,)
        ).fetchone()[0]
        assert description == "Wir suchen eine Kraft für das Wochenende an unserer Theke."

    def test_rerun_does_not_reset_her_status(self, db):
        upsert_job(db, posting(), now="2026-08-16 08:00:00")
        db.execute(
            "UPDATE status SET status = 'interested', notes = 'Chef kennt sie' WHERE job_id = ?",
            (posting().job_id,),
        )
        upsert_job(db, posting(), now="2026-08-16 09:00:00")
        status = status_row(db, "status, notes", posting().job_id)
        assert tuple(status) == ("interested", "Chef kennt sie")


class TestDedupeKey:
    def test_same_job_on_two_sources_shares_the_dedupe_key(self, db):
        # Since Phase 5 the store enforces what this key promises: the SS copy
        # below merges into the BA row instead of forming a second one.
        ba = posting()  # "Werkstudent Küche (m/w/d)", one spacing
        stepstone = posting(
            job_id="SS:9f2c-ab",
            source="SS",
            source_id="9f2c-ab",
            title="Werkstudent   Küche (m/f/d)",  # other marker, other spacing
        )
        upsert_job(db, ba, now="2026-08-16 08:00:00")
        upsert_job(db, stepstone, now="2026-08-16 09:00:00")
        assert db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
        assert job_row(db, "also_seen_on") == "SS"


def arbeitnow_copy(**overrides) -> RawPosting:
    """The same Bäckerei ad as `posting()`, as the Arbeitnow adapter emits it.

    Built through `parse_entry` rather than by hand, because the merge stands
    or falls on fields the real adapter can produce: Arbeitnow answers a plain
    city string and **no postcode at all**.
    """
    entry = {
        "slug": "werkstudent-kueche-baeckerei-mueller-407715",
        "title": "Werkstudent Küche (m/f/d)",  # same normalised identity
        "company_name": "Bäckerei Müller & Söhne",
        "location": "Ingolstadt",  # no district suffix, no plz
        "job_types": ["Working Student"],
        "description": "<p>Wir suchen eine Kraft für das Wochenende an unserer Theke.</p>",
    }
    parsed = parse_entry(entry)
    assert parsed is not None
    return dataclasses.replace(parsed, **overrides)


class TestCrossSourceMerge:
    """§ Phase 5: one ad on two sites is one row — richest record, her status intact."""

    def test_same_job_from_ba_and_arbeitnow_collapses_to_one_row_with_both_sources(self, db):
        upsert_job(db, posting(), now="2026-08-16 08:00:00")
        outcome = upsert_job(db, arbeitnow_copy(), now="2026-08-16 09:00:00")

        assert outcome == "duplicate"  # the row existed; nothing new was stored
        assert db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
        assert job_row(db, "job_id") == posting().job_id  # identity kept
        assert job_row(db, "source") == "BA"
        assert job_row(db, "also_seen_on") == "AN"  # the alternate, recorded

    def test_richest_record_wins_when_merging(self, db):
        # The BA row arrived without a description (detail fetch skipped or
        # empty); Arbeitnow carries the ad text — backfill, never overwrite.
        upsert_job(db, posting(description=None, apply_url=None), now="2026-08-16 08:00:00")
        upsert_job(
            db,
            arbeitnow_copy(
                description="Die Theke wartet auf dich.", apply_url="https://arbeitnow.example/j"
            ),
            now="2026-08-16 09:00:00",
        )

        assert job_row(db, "has_description") == 1
        assert job_row(db, "content_hash")  # derived from the backfilled text
        assert job_row(db, "apply_url") == "https://arbeitnow.example/j"
        description = db.execute(
            "SELECT description FROM job_descriptions WHERE job_id = ?", (posting().job_id,)
        ).fetchone()
        assert description[0] == "Die Theke wartet auf dich."

    def test_an_existing_description_is_never_overwritten_by_a_merge(self, db):
        upsert_job(db, posting(), now="2026-08-16 08:00:00")
        upsert_job(
            db, arbeitnow_copy(description="A different, shorter text."), now="2026-08-16 09:00:00"
        )
        description = db.execute(
            "SELECT description FROM job_descriptions WHERE job_id = ?", (posting().job_id,)
        ).fetchone()[0]
        assert description == "Wir suchen eine Kraft für das Wochenende an unserer Theke."

    def test_a_merge_never_touches_her_status(self, db):
        upsert_job(db, posting(), now="2026-08-16 08:00:00")
        db.execute(
            "UPDATE status SET status = 'applied', notes = 'beworben am 15.8.' WHERE job_id = ?",
            (posting().job_id,),
        )
        upsert_job(db, arbeitnow_copy(), now="2026-08-16 09:00:00")
        status = status_row(db, "status, notes", posting().job_id)
        assert tuple(status) == ("applied", "beworben am 15.8.")

    def test_a_merge_moves_last_seen_but_not_first_seen(self, db):
        upsert_job(db, posting(), now="2026-08-16 08:00:00")
        upsert_job(db, arbeitnow_copy(), now="2026-08-16 09:00:00")
        assert job_row(db, "first_seen_at") == "2026-08-16 08:00:00"
        assert job_row(db, "last_seen_at") == "2026-08-16 09:00:00"

    def test_the_same_alternate_is_not_recorded_twice(self, db):
        upsert_job(db, posting(), now="2026-08-16 08:00:00")
        upsert_job(db, arbeitnow_copy(), now="2026-08-16 09:00:00")
        upsert_job(db, arbeitnow_copy(), now="2026-08-16 10:00:00")
        assert job_row(db, "also_seen_on") == "AN"

    def test_two_openings_from_the_same_source_stay_two_rows(self, db):
        # Live BA data, one query: Penny-Markt listed two Werkstudent openings
        # in Neuburg under two reference numbers. Same title, same company,
        # same town — and two jobs she can apply to, not one.
        first = posting(job_id="BA:12608-1422085-9313-1-S", source_id="12608-1422085-9313-1-S")
        second = posting(job_id="BA:12608-1422101-9313-1-S", source_id="12608-1422101-9313-1-S")

        upsert_job(db, first, now="2026-08-16 08:00:00")
        outcome = upsert_job(db, second, now="2026-08-16 08:00:01")

        assert outcome == "new"
        assert db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 2
        assert job_row(db, "also_seen_on", first.job_id) is None  # not "also on BA"

    def test_a_third_source_joins_the_alternates_in_arrival_order(self, db):
        stepstone = posting(
            job_id="SS:9f2c-ab", source="SS", source_id="9f2c-ab", title="Werkstudent Küche"
        )
        upsert_job(db, posting(), now="2026-08-16 08:00:00")
        upsert_job(db, arbeitnow_copy(), now="2026-08-16 09:00:00")
        upsert_job(db, stepstone, now="2026-08-16 10:00:00")
        assert job_row(db, "also_seen_on") == "AN,SS"
