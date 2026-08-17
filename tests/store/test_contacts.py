"""The call-list in the store, and the decisions she makes about it.

`contacts` was created in schema v1 and has been empty ever since — Phase 9 was
anticipated. Two rules carry over from the jobs side and matter more here:

- **Re-running must never duplicate a place, and never overwrite her.** She will
  build this list more than once. A second run that forgets she already rang
  the bakery makes the whole list untrustworthy.
- **A place is saved the moment it is parsed** (§9), not at the end of a run.
"""

from __future__ import annotations

import pytest

from jobfinder.sources.overpass import Place
from jobfinder.store.contacts import (
    VALID_OUTCOMES,
    contact_by_osm_id,
    list_contacts,
    set_contact_notes,
    set_contact_outcome,
    upsert_contact,
)
from jobfinder.store.db import connect, migrate


@pytest.fixture
def db(tmp_path):
    connection = connect(tmp_path / "jobfinder.db")
    migrate(connection)
    yield connection
    connection.close()


def place(osm_id="node/1", name="Bäckerei Müller & Söhne", kind="bakery", **overrides) -> Place:
    values = dict(
        contact_id=osm_id,
        name=name,
        kind=kind,
        city="Neuburg an der Donau",
        street="Färberstraße 12",
        phone="+498431648595",
        email=None,
        website=None,
        lat=48.7325,
        lon=11.1878,
    )
    values.update(overrides)
    return Place(**values)


class TestStoringAPlace:
    def test_a_contact_is_stored_with_its_kind_city_and_route(self, db):
        upsert_contact(db, place(), score=85, reason="A bakery: mostly back-of-house work.")

        stored = contact_by_osm_id(db, "node/1")
        assert stored["name"] == "Bäckerei Müller & Söhne"
        assert stored["kind"] == "bakery"
        assert stored["city"] == "Neuburg an der Donau"
        assert stored["street"] == "Färberstraße 12"
        assert stored["phone"] == "+498431648595"
        assert stored["back_of_house_score"] == 85
        assert "back-of-house" in stored["score_reason"]

    def test_the_osm_id_is_what_identifies_a_place(self, db):
        upsert_contact(db, place(osm_id="way/42"), score=80, reason="")

        assert contact_by_osm_id(db, "way/42") is not None
        assert contact_by_osm_id(db, "node/42") is None

    def test_re_running_updates_a_contact_rather_than_duplicating_it(self, db):
        upsert_contact(db, place(), score=85, reason="")
        upsert_contact(db, place(phone="+498431000000"), score=85, reason="")

        rows = list_contacts(db)
        assert len(rows) == 1
        assert rows[0]["phone"] == "+498431000000"

    def test_a_place_that_lost_its_phone_keeps_the_one_we_had(self, db):
        """OSM data goes backwards sometimes — a surveyor deletes a tag. Losing
        the number she was going to ring is worse than holding a stale one."""
        upsert_contact(db, place(), score=85, reason="")
        upsert_contact(db, place(phone=None, email="hallo@example.de"), score=85, reason="")

        stored = contact_by_osm_id(db, "node/1")
        assert stored["phone"] == "+498431648595"
        assert stored["email"] == "hallo@example.de"

    def test_first_seen_at_is_set_once_and_never_moved(self, db):
        upsert_contact(db, place(), score=85, reason="")
        first = contact_by_osm_id(db, "node/1")["first_seen_at"]

        upsert_contact(db, place(name="Bäckerei Müller"), score=85, reason="")

        assert contact_by_osm_id(db, "node/1")["first_seen_at"] == first

    def test_a_contact_is_committed_immediately(self, db, tmp_path):
        """§9: a run killed the next instant keeps what it stored."""
        upsert_contact(db, place(), score=85, reason="")

        other = connect(tmp_path / "jobfinder.db")
        try:
            assert other.execute("SELECT COUNT(*) FROM contacts").fetchone()[0] == 1
        finally:
            other.close()

    def test_umlauts_survive_the_round_trip(self, db):
        upsert_contact(db, place(name="Café Größenwahn"), score=45, reason="")

        assert contact_by_osm_id(db, "node/1")["name"] == "Café Größenwahn"


class TestHerDecisions:
    def test_marking_called_records_the_outcome(self, db):
        upsert_contact(db, place(), score=85, reason="")

        set_contact_outcome(db, "node/1", "called")

        assert contact_by_osm_id(db, "node/1")["outcome"] == "called"

    def test_marking_called_stamps_the_day_once_and_never_rewrites_it(self, db):
        upsert_contact(db, place(), score=85, reason="")
        set_contact_outcome(db, "node/1", "called", now="2026-08-17 09:00:00")

        set_contact_outcome(db, "node/1", "no", now="2026-08-24 09:00:00")

        stored = contact_by_osm_id(db, "node/1")
        assert stored["outcome"] == "no"
        assert stored["last_contacted_at"] == "2026-08-17 09:00:00"

    def test_an_outcome_note_is_saved_and_read_back(self, db):
        upsert_contact(db, place(), score=85, reason="")

        set_contact_notes(db, "node/1", "Called — come by Tuesday at 9")

        assert contact_by_osm_id(db, "node/1")["notes"] == "Called — come by Tuesday at 9"

    def test_a_note_survives_a_later_re_run_of_the_source(self, db):
        upsert_contact(db, place(), score=85, reason="")
        set_contact_outcome(db, "node/1", "called", now="2026-08-17 09:00:00")
        set_contact_notes(db, "node/1", "Come by Tuesday")

        upsert_contact(db, place(phone="+498431111111"), score=85, reason="")

        stored = contact_by_osm_id(db, "node/1")
        assert stored["outcome"] == "called"
        assert stored["notes"] == "Come by Tuesday"
        assert stored["last_contacted_at"] == "2026-08-17 09:00:00"

    def test_an_unknown_outcome_is_refused_with_a_sentence(self, db):
        upsert_contact(db, place(), score=85, reason="")

        with pytest.raises(ValueError) as refused:
            set_contact_outcome(db, "node/1", "maybe later")

        assert "maybe later" in str(refused.value)
        for outcome in VALID_OUTCOMES:
            assert outcome in str(refused.value)

    def test_an_outcome_on_a_place_we_never_stored_is_refused(self, db):
        with pytest.raises(ValueError) as refused:
            set_contact_outcome(db, "node/999", "called")

        assert "node/999" in str(refused.value)


class TestTheQueue:
    def _three(self, db):
        upsert_contact(
            db, place(osm_id="node/1", name="Bäckerei", kind="bakery"), score=85, reason=""
        )
        upsert_contact(db, place(osm_id="node/2", name="Hotel", kind="hotel"), score=80, reason="")
        upsert_contact(db, place(osm_id="node/3", name="Bar", kind="bar"), score=20, reason="")

    def test_contacts_come_back_best_first(self, db):
        self._three(db)

        assert [row["name"] for row in list_contacts(db)] == ["Bäckerei", "Hotel", "Bar"]

    def test_marking_no_moves_it_out_of_the_queue(self, db):
        self._three(db)
        set_contact_outcome(db, "node/3", "no")

        assert [row["name"] for row in list_contacts(db, pending_only=True)] == [
            "Bäckerei",
            "Hotel",
        ]

    def test_a_place_she_has_answered_can_still_be_found(self, db):
        self._three(db)
        set_contact_outcome(db, "node/3", "no")

        assert len(list_contacts(db)) == 3

    def test_the_queue_can_be_narrowed_to_one_city(self, db):
        self._three(db)
        upsert_contact(
            db, place(osm_id="node/4", name="Ingo", city="Ingolstadt"), score=70, reason=""
        )

        names = [row["name"] for row in list_contacts(db, cities=("Ingolstadt",))]
        assert names == ["Ingo"]

    def test_a_place_with_only_a_website_is_kept_apart_from_the_call_queue(self, db):
        """It cannot be rung yet — the imprint step may give it an email. Until
        then it is not something she can act on today."""
        self._three(db)
        upsert_contact(
            db,
            place(osm_id="node/5", name="Nur Website", phone=None, website="https://x.example.de"),
            score=65,
            reason="",
        )

        assert "Nur Website" not in [row["name"] for row in list_contacts(db, reachable_only=True)]
        assert "Nur Website" in [row["name"] for row in list_contacts(db)]
