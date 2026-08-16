"""Her decisions — the one table she writes to, now with dates she cares about.

`applied_on` is the column the job page's "you applied on …" line reads. It is
set the first time a job is marked applied and survives status changes after
that: marking something "rejected" a week later must not rewrite history.
"""

from __future__ import annotations

import pytest

from jobfinder.sources.base import RawPosting
from jobfinder.store.db import connect, migrate
from jobfinder.store.jobs import upsert_job
from jobfinder.store.status import VALID_STATUSES, set_notes, set_status


@pytest.fixture
def db(tmp_path):
    connection = connect(tmp_path / "jobfinder.db")
    migrate(connection)
    upsert_job(connection, RawPosting(job_id="BA:1", source="BA", source_id="1", title="Job 1"))
    yield connection
    connection.close()


def row(db, job_id: str = "BA:1"):
    return db.execute("SELECT * FROM status WHERE job_id = ?", (job_id,)).fetchone()


class TestSetStatus:
    def test_set_status_applied_records_the_date(self, db):
        set_status(db, "BA:1", "applied", now="2026-08-16 12:00:00")

        assert row(db)["status"] == "applied"
        assert row(db)["applied_on"] == "2026-08-16 12:00:00"

    def test_applied_on_keeps_its_original_date_when_remarked(self, db):
        set_status(db, "BA:1", "applied", now="2026-08-16 12:00:00")
        set_status(db, "BA:1", "interested", now="2026-08-18 09:00:00")
        set_status(db, "BA:1", "applied", now="2026-08-18 10:00:00")

        # She applied on the 16th; the detour through 'interested' and back
        # must not move the date she actually sent it.
        assert row(db)["applied_on"] == "2026-08-16 12:00:00"

    def test_moving_away_from_applied_keeps_the_date(self, db):
        set_status(db, "BA:1", "applied", now="2026-08-16 12:00:00")
        set_status(db, "BA:1", "rejected", now="2026-08-20 09:00:00")

        assert row(db)["status"] == "rejected"
        assert row(db)["applied_on"] == "2026-08-16 12:00:00"

    def test_invalid_status_is_rejected_with_the_valid_ones(self, db):
        with pytest.raises(ValueError) as exc:
            set_status(db, "BA:1", "archived")
        assert "archived" in str(exc.value)
        for valid in VALID_STATUSES:
            assert valid in str(exc.value)

    def test_unknown_job_is_rejected_by_name(self, db):
        with pytest.raises(ValueError) as exc:
            set_status(db, "BA:404", "applied")
        assert "BA:404" in str(exc.value)

    def test_every_status_the_ui_offers_is_valid(self, db):
        # The five buttons on the job page, exercised through the same door.
        for status in ("interested", "applied", "rejected", "deleted", "new"):
            set_status(db, "BA:1", status)
            assert row(db)["status"] == status


class TestNotes:
    def test_set_notes_saves_and_is_read_back(self, db):
        set_notes(db, "BA:1", "Called — come by Tuesday with a printed CV")
        assert "come by Tuesday" in row(db)["notes"]

    def test_notes_survive_a_status_change(self, db):
        set_notes(db, "BA:1", "bring certificates")
        set_status(db, "BA:1", "applied")
        assert row(db)["notes"] == "bring certificates"

    def test_an_empty_note_clears_it(self, db):
        set_notes(db, "BA:1", "scratch thought")
        set_notes(db, "BA:1", "")
        assert row(db)["notes"] == ""

    def test_unknown_job_is_rejected_by_name(self, db):
        with pytest.raises(ValueError) as exc:
            set_notes(db, "BA:404", "note")
        assert "BA:404" in str(exc.value)
