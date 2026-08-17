"""The Contacts page: a list to work through with a phone in her hand.

This page is not a job board and must not read like one. Each row is a place she
is about to ring, with the number on it, the German to say, and three buttons for
what happened. §10's rules apply as everywhere else: English except the script
itself, an honest empty state, and her decisions surviving a restart.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from jobfinder.config import Settings
from jobfinder.sources.overpass import Place
from jobfinder.store.contacts import contact_by_osm_id, upsert_contact
from jobfinder.store.db import connect, migrate
from jobfinder.web.app import create_app

SCRIPT = (
    "Guten Tag, mein Name ist Saba.\n    Hello, my name is Saba.\n"
    "Suchen Sie im Moment Aushilfen?\n    Are you looking for helpers at the moment?"
)


def place(osm_id="node/1", name="Bäckerei Schlegl", kind="bakery", **overrides) -> Place:
    values = dict(
        contact_id=osm_id,
        name=name,
        kind=kind,
        city="Neuburg an der Donau",
        street="Färberstraße 12",
        phone="+4984318324",
        email=None,
        website=None,
        lat=48.7325,
        lon=11.1878,
    )
    values.update(overrides)
    return Place(**values)


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(project_root=tmp_path)


@pytest.fixture
def stocked(settings) -> Settings:
    """A call-list like the real one: a bakery, a hotel, a bar, a website-only."""
    connection = connect(settings.db_path)
    try:
        migrate(connection)
        upsert_contact(
            connection,
            place(),
            score=93,
            reason="A bakery: mostly back-of-house work, you can write instead of phoning.",
        )
        upsert_contact(
            connection,
            place(osm_id="node/2", name="Sporthotel Neuburg", kind="hotel", phone="+49843167500"),
            score=88,
            reason="A hotel: mostly back-of-house work.",
        )
        upsert_contact(
            connection,
            place(
                osm_id="node/3",
                name="Route66 Bar",
                kind="bar",
                phone=None,
                email="bar@example.de",
            ),
            score=28,
            reason="A bar: mostly serving customers.",
        )
        upsert_contact(
            connection,
            place(
                osm_id="node/4",
                name="Nur Website",
                kind="cafe",
                phone=None,
                website="https://x.example.de",
            ),
            score=45,
            reason="A cafe: some kitchen work, some customer contact.",
        )
        connection.execute(
            "UPDATE contacts SET script = ?, email_draft = ? WHERE osm_id = 'node/1'",
            (SCRIPT, "Guten Tag,\n\nich bin Studentin…\n\nSaba"),
        )
        connection.commit()
    finally:
        connection.close()
    return settings


@pytest.fixture
def client(stocked) -> TestClient:
    with TestClient(create_app(stocked)) as test_client:
        yield test_client


class TestTheList:
    def test_the_page_lists_contacts_best_first(self, client):
        body = client.get("/contacts").text

        assert body.index("Bäckerei Schlegl") < body.index("Sporthotel Neuburg")
        assert body.index("Sporthotel Neuburg") < body.index("Route66 Bar")

    def test_the_page_shows_the_phone_the_kind_and_the_street(self, client):
        body = client.get("/contacts").text

        assert "+4984318324" in body
        assert "bakery" in body
        assert "Färberstraße 12" in body

    def test_a_phone_number_is_a_tel_link_she_can_tap(self, client):
        body = client.get("/contacts").text

        assert 'href="tel:+4984318324"' in body

    def test_an_email_place_offers_a_mailto(self, client):
        body = client.get("/contacts").text

        assert "mailto:bar@example.de" in body

    def test_the_reason_a_place_ranks_where_it_does_is_shown(self, client):
        body = client.get("/contacts").text

        assert "mostly back-of-house work" in body

    def test_the_score_is_shown_as_a_number(self, client):
        body = client.get("/contacts").text

        assert ">93<" in body

    def test_a_website_only_place_is_kept_apart_from_the_call_queue(self, client):
        """She cannot ring it, so it does not belong in the list she is working
        through — but it is not thrown away either."""
        body = client.get("/contacts").text

        assert "Nur Website" in body
        assert "no phone or email yet" in body

    def test_the_nav_links_to_the_contacts_page(self, client):
        assert 'href="/contacts"' in client.get("/").text

    def test_the_page_says_how_many_she_can_reach(self, client):
        body = client.get("/contacts").text

        assert ">3<" in body  # three of the four have a phone or an email


class TestTheScript:
    def test_the_page_offers_the_script_for_that_place(self, client):
        body = client.get("/contacts").text

        assert "Guten Tag, mein Name ist Saba." in body
        assert "Hello, my name is Saba." in body

    def test_a_place_without_a_script_says_so_rather_than_showing_nothing(self, client):
        body = client.get("/contacts").text

        assert "No script yet" in body

    def test_everything_except_the_script_is_english(self, client):
        """§10: nothing on screen is in German except the German she will say.
        The script and the place names are the exceptions."""
        body = client.get("/contacts").text

        for german in ("Anrufen", "Auswahl", "Kontakte", "Ergebnis"):
            assert german not in body


class TestMarkingWhatHappened:
    def test_marking_called_persists(self, stocked, client):
        response = client.post(
            "/contacts/node%2F1/outcome", data={"outcome": "called"}, follow_redirects=True
        )

        assert response.status_code == 200
        connection = connect(stocked.db_path)
        try:
            assert contact_by_osm_id(connection, "node/1")["outcome"] == "called"
        finally:
            connection.close()

    def test_marking_it_survives_a_restart_of_the_app(self, stocked):
        with TestClient(create_app(stocked)) as first:
            first.post("/contacts/node%2F1/outcome", data={"outcome": "called"})

        with TestClient(create_app(stocked)) as second:
            body = second.get("/contacts").text

        assert "called" in body

    def test_a_note_is_saved_and_shown_back(self, stocked, client):
        client.post(
            "/contacts/node%2F1/notes",
            data={"notes": "Come by Tuesday at 9"},
            follow_redirects=True,
        )

        body = client.get("/contacts").text
        assert "Come by Tuesday at 9" in body

    def test_a_marked_place_leaves_the_queue_but_can_be_found_again(self, stocked, client):
        client.post("/contacts/node%2F3/outcome", data={"outcome": "no"})

        working = client.get("/contacts").text
        everything = client.get("/contacts?show=all").text

        assert "Route66 Bar" not in working
        assert "Route66 Bar" in everything

    def test_an_unknown_outcome_is_refused_readably(self, client):
        response = client.post("/contacts/node%2F1/outcome", data={"outcome": "maybe"})

        assert response.status_code == 400
        assert "maybe" in response.text
        assert "Traceback" not in response.text

    def test_an_unknown_place_is_a_readable_404(self, client):
        response = client.post("/contacts/node%2F999/outcome", data={"outcome": "called"})

        assert response.status_code == 404
        assert "Traceback" not in response.text

    def test_the_three_outcomes_are_offered_on_every_row(self, client):
        body = client.get("/contacts").text

        for label in ("Called", "Emailed", "Not for me"):
            assert label in body


class TestTheEmptyState:
    def test_an_empty_call_list_says_how_to_build_it(self, settings):
        connection = connect(settings.db_path)
        try:
            migrate(connection)
        finally:
            connection.close()

        with TestClient(create_app(settings)) as client:
            body = client.get("/contacts").text

        assert "No places yet" in body
        assert "jobfinder contacts" in body

    def test_a_fully_worked_through_list_says_so(self, stocked, client):
        for osm_id in ("node%2F1", "node%2F2", "node%2F3"):
            client.post(f"/contacts/{osm_id}/outcome", data={"outcome": "no"})

        body = client.get("/contacts").text

        assert "been through every place" in body
