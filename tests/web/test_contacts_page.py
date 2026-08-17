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

    def test_still_to_try_counts_only_places_she_can_actually_try(self, stocked, client):
        """Found on the real 357-place list: the header read "255 places you can
        reach · 357 still to try", which cannot both be true. `pending` counted
        every place without an answer, including the ones with no phone or email
        — places she cannot try at all."""
        client.post("/contacts/node%2F1/outcome", data={"outcome": "called"})

        body = client.get("/contacts").text

        # 3 reachable, 1 answered for → 2 left to try. Never 3, and never the
        # 4 that includes the website-only place.
        assert '<span class="num">2</span> still to try' in body

    def test_no_still_to_try_line_when_nothing_has_been_answered(self, client):
        """With every reachable place still open, the second number would just
        repeat the first."""
        body = client.get("/contacts").text

        assert "still to try" not in body


class TestPaging:
    """Found on the real list: three cities returned **357** places, and every
    one of them rendered as a card on a single page. A call-list is worked
    through from the top, a few at a time, so it pages like the job list does.
    """

    @pytest.fixture
    def many(self, settings) -> Settings:
        connection = connect(settings.db_path)
        try:
            migrate(connection)
            for index in range(60):
                upsert_contact(
                    connection,
                    place(osm_id=f"node/{index}", name=f"Bäckerei {index:02d}"),
                    score=90 - index % 10,
                    reason="",
                )
        finally:
            connection.close()
        return settings

    def test_only_one_page_of_places_is_rendered(self, many):
        from jobfinder.web.routes import CONTACTS_PAGE_SIZE

        with TestClient(create_app(many)) as client:
            body = client.get("/contacts").text

        assert body.count('class="contact-row"') == CONTACTS_PAGE_SIZE

    def test_the_next_page_is_offered_and_shows_the_rest(self, many):
        with TestClient(create_app(many)) as client:
            first = client.get("/contacts").text
            assert "page=2" in first

            second = client.get("/contacts?page=2").text

        assert 'class="contact-row"' in second
        assert "Bäckerei 00" not in second  # the first page's places are not repeated

    def test_the_first_page_offers_no_previous(self, many):
        with TestClient(create_app(many)) as client:
            body = client.get("/contacts").text

        assert "page=0" not in body

    def test_a_short_list_offers_no_paging_at_all(self, client):
        body = client.get("/contacts").text

        assert "page=2" not in body

    def test_a_page_beyond_the_end_is_not_an_error(self, many):
        with TestClient(create_app(many)) as client:
            response = client.get("/contacts?page=99")

        assert response.status_code == 200
        assert "Traceback" not in response.text

    def test_an_unreadable_page_number_falls_back_to_the_first(self, many):
        with TestClient(create_app(many)) as client:
            body = client.get("/contacts?page=banana").text

        assert "Bäckerei 00" in body


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

    def test_marking_it_reaches_the_csv_she_prints(self, stocked, client):
        """Found by comparing the two on real data: the CSV is only rewritten by a
        run, so 357 rows of it said nothing about the place she had just rung. The
        call-list is the one part of this app meant to be printed and carried, so
        a CSV that disagrees with the screen is a defect, not a lag."""
        import csv

        client.post("/contacts/node%2F1/outcome", data={"outcome": "called"})
        client.post("/contacts/node%2F1/notes", data={"notes": "Come by Tuesday"})

        with open(stocked.contacts_csv, encoding="utf-8-sig", newline="") as handle:
            rows = {row["osm_id"]: row for row in csv.DictReader(handle)}

        assert rows["node/1"]["outcome"] == "called"
        assert rows["node/1"]["notes"] == "Come by Tuesday"

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


class TestBuildingItFromTheBrowser:
    """The same reason the Explain button exists: a feature that needs a terminal
    is a feature she does not have. A contacts run takes minutes — measured, one
    city took several — so it narrates from the journal like every other run."""

    def _managed(self, settings, runner=None, source=None):
        from jobfinder.web.runs import RunManager

        manager = RunManager(
            settings,
            adapter_factory=lambda: [],
            contacts_runner=runner,
            contacts_source_factory=(lambda: source) if source is not None else None,
        )
        return manager

    def test_a_contacts_run_starts_from_the_browser_and_narrates(self, settings):
        """The page shows what the *list* holds, not what a run row claims — so
        this proves the run happened by the places it left behind."""
        import threading

        asked: dict = {}
        started = threading.Event()

        def fake_runner(**kwargs):
            asked.update(kwargs)
            started.set()
            from jobfinder.contacts.runner import ContactsRun

            connection = connect(settings.db_path)
            try:
                migrate(connection)
                upsert_contact(connection, place(name="Bäckerei Gefunden"), score=85, reason="")
            finally:
                connection.close()
            return ContactsRun(found=1, reachable=1, total_stored=1)

        manager = self._managed(settings, runner=fake_runner)
        with TestClient(create_app(settings, run_manager=manager)) as client:
            response = client.post("/run/contacts", data={"cities": "Neuburg an der Donau"})
            assert response.status_code in (200, 303)
            manager.wait_contacts(timeout=10)

            body = client.get("/contacts").text

        assert started.is_set()
        assert asked["cities"] == ("Neuburg an der Donau",)  # the towns she typed
        assert "Bäckerei Gefunden" in body

    def test_the_towns_she_typed_are_the_ones_searched(self, settings):
        asked: dict = {}

        def fake_runner(**kwargs):
            asked.update(kwargs)

        manager = self._managed(settings, runner=fake_runner)
        with TestClient(create_app(settings, run_manager=manager)) as client:
            client.post("/run/contacts", data={"cities": "Ingolstadt, München"})
            manager.wait_contacts(timeout=10)

        assert asked["cities"] == ("Ingolstadt", "München")

    def test_an_empty_towns_field_falls_back_to_her_usual_three(self, settings):
        from jobfinder.cli import DEFAULT_CITIES

        asked: dict = {}

        manager = self._managed(settings, runner=lambda **kwargs: asked.update(kwargs))
        with TestClient(create_app(settings, run_manager=manager)) as client:
            client.post("/run/contacts", data={"cities": ""})
            manager.wait_contacts(timeout=10)

        assert asked["cities"] == DEFAULT_CITIES

    def test_a_second_start_while_one_runs_is_refused_politely(self, settings):
        import threading

        gate = threading.Event()

        manager = self._managed(settings, runner=lambda **kwargs: gate.wait(timeout=10))
        with TestClient(create_app(settings, run_manager=manager)) as client:
            client.post("/run/contacts", data={"cities": "Neuburg an der Donau"})

            response = client.post("/run/contacts", data={"cities": "Ingolstadt"})

            assert response.status_code == 200
            assert "already" in response.text
        gate.set()
        manager.wait_contacts(timeout=10)

    def test_the_page_offers_the_button_and_the_cities(self, settings):
        manager = self._managed(settings)
        with TestClient(create_app(settings, run_manager=manager)) as client:
            body = client.get("/contacts").text

        assert 'action="/run/contacts"' in body
        assert 'name="cities"' in body

    def test_a_failing_run_leaves_a_sentence_not_a_traceback(self, settings):
        def exploding(**kwargs):
            raise RuntimeError("overpass is having a day")

        manager = self._managed(settings, runner=exploding)
        with TestClient(create_app(settings, run_manager=manager)) as client:
            client.post("/run/contacts", data={"cities": "Neuburg an der Donau"})
            manager.wait_contacts(timeout=10)

            body = client.get("/contacts").text

        assert "RuntimeError" in body
        assert "Traceback" not in body

    def test_cancel_stops_a_contacts_run(self, settings):
        import threading

        cancelled = threading.Event()

        def watching(**kwargs):
            stop_event = kwargs.get("stop_event")
            for _ in range(200):
                if stop_event is not None and stop_event.is_set():
                    cancelled.set()
                    return
                threading.Event().wait(0.01)

        manager = self._managed(settings, runner=watching)
        with TestClient(create_app(settings, run_manager=manager)) as client:
            client.post("/run/contacts", data={"cities": "Neuburg an der Donau"})
            client.post("/run/contacts/cancel")
            manager.wait_contacts(timeout=10)

        assert cancelled.is_set()


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
