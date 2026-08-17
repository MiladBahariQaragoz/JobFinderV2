"""Building the call-list: one run, several cities, saved as it goes.

§9 is the rule that shapes this: every place is committed the moment it is
parsed, so a run killed halfway leaves a shorter list rather than no list, and
the next run continues instead of starting again. §10 is the other: the run
journals its counts as it goes, so the browser can narrate it.
"""

from __future__ import annotations

import pytest

from jobfinder.config import Settings
from jobfinder.contacts.runner import ContactsRun, run_contacts
from jobfinder.sources.http import SourceUnavailable
from jobfinder.store.contacts import contact_by_osm_id, list_contacts
from jobfinder.store.db import connect, migrate


@pytest.fixture
def settings(tmp_path) -> Settings:
    settings = Settings(project_root=tmp_path)
    connection = connect(settings.db_path)
    migrate(connection)
    connection.close()
    return settings


def element(osm_type="node", osm_id=1, **tags):
    return {"type": osm_type, "id": osm_id, "tags": tags}


class FakeSource:
    """Stands in for the Overpass adapter: per-city answers, recorded calls."""

    def __init__(self, by_city, failures=()):
        self.by_city = dict(by_city)
        self.failures = list(failures)
        self.asked: list[str] = []

    def places_near(self, lat, lon, *, city, radius_km=6):
        self.asked.append(city)
        answer = self.by_city.get(city, [])
        if isinstance(answer, Exception):
            raise answer
        from jobfinder.sources.overpass import parse_places

        return parse_places(answer, city=city)


def bakery(osm_id=1, name="Bäckerei", city="Neuburg an der Donau"):
    return element("node", osm_id, shop="bakery", name=name, phone="+498431648595")


def bar(osm_id=2, name="Bar"):
    return element("node", osm_id, amenity="bar", name=name, phone="+498431648596")


def website_only(osm_id=3, name="Nur Website"):
    return element("node", osm_id, amenity="cafe", name=name, website="https://x.example.de")


class TestOneRun:
    def test_places_are_stored_for_every_city_asked_for(self, settings):
        source = FakeSource(
            {
                "Neuburg an der Donau": [bakery()],
                "Ingolstadt": [bakery(osm_id=10, name="Ingo Bäckerei")],
            }
        )

        result = run_contacts(settings, source, cities=("Neuburg an der Donau", "Ingolstadt"))

        assert isinstance(result, ContactsRun)
        assert result.found == 2
        assert result.new == 2
        connection = connect(settings.db_path)
        try:
            assert len(list_contacts(connection)) == 2
        finally:
            connection.close()

    def test_the_run_reports_per_city_counts(self, settings):
        source = FakeSource(
            {
                "Neuburg an der Donau": [bakery(), bar()],
                "Ingolstadt": [bakery(osm_id=10)],
            }
        )

        result = run_contacts(settings, source, cities=("Neuburg an der Donau", "Ingolstadt"))

        assert result.per_city == {"Neuburg an der Donau": 2, "Ingolstadt": 1}

    def test_a_place_is_scored_and_the_reason_stored(self, settings):
        source = FakeSource({"Neuburg an der Donau": [bakery()]})

        run_contacts(settings, source, cities=("Neuburg an der Donau",))

        connection = connect(settings.db_path)
        try:
            stored = contact_by_osm_id(connection, "node/1")
        finally:
            connection.close()
        assert stored["back_of_house_score"] >= 80  # a bakery ranks high
        assert "bakery" in stored["score_reason"].lower()

    def test_a_second_run_updates_rather_than_duplicating(self, settings):
        source = FakeSource({"Neuburg an der Donau": [bakery()]})
        run_contacts(settings, source, cities=("Neuburg an der Donau",))

        second = run_contacts(settings, source, cities=("Neuburg an der Donau",))

        assert second.found == 1
        assert second.new == 0
        connection = connect(settings.db_path)
        try:
            assert len(list_contacts(connection)) == 1
        finally:
            connection.close()

    def test_the_csv_is_written(self, settings):
        source = FakeSource({"Neuburg an der Donau": [bakery()]})

        run_contacts(settings, source, cities=("Neuburg an der Donau",))

        csv_path = settings.contacts_csv
        assert csv_path.exists()
        assert "Bäckerei" in csv_path.read_text(encoding="utf-8-sig")

    def test_a_city_with_no_places_is_not_an_error(self, settings):
        source = FakeSource({"Neuburg an der Donau": [], "Ingolstadt": [bakery(osm_id=10)]})

        result = run_contacts(settings, source, cities=("Neuburg an der Donau", "Ingolstadt"))

        assert result.found == 1
        assert result.per_city["Neuburg an der Donau"] == 0

    def test_a_city_that_cannot_be_searched_costs_only_that_city(self, settings):
        source = FakeSource(
            {
                "Neuburg an der Donau": SourceUnavailable("overpass said 504"),
                "Ingolstadt": [bakery(osm_id=10, name="Ingo")],
            }
        )

        result = run_contacts(settings, source, cities=("Neuburg an der Donau", "Ingolstadt"))

        assert result.found == 1
        assert any("Neuburg" in error for error in result.errors)

    def test_an_unknown_city_is_reported_and_skipped(self, settings):
        source = FakeSource({"Ingolstadt": [bakery(osm_id=10)]})

        result = run_contacts(settings, source, cities=("Atlantis", "Ingolstadt"))

        assert result.found == 1
        assert any("Atlantis" in error for error in result.errors)


class TestSavingAsItGoes:
    def test_each_place_is_committed_before_the_run_ends(self, settings):
        """§9: a kill mid-run leaves a shorter list, never an empty one."""
        seen: list[int] = []

        class WatchingSource(FakeSource):
            def places_near(self, lat, lon, *, city, radius_km=6):
                other = connect(settings.db_path)
                try:
                    seen.append(other.execute("SELECT COUNT(*) FROM contacts").fetchone()[0])
                finally:
                    other.close()
                return super().places_near(lat, lon, city=city, radius_km=radius_km)

        source = WatchingSource(
            {
                "Neuburg an der Donau": [bakery()],
                "Ingolstadt": [bakery(osm_id=10)],
            }
        )
        run_contacts(settings, source, cities=("Neuburg an der Donau", "Ingolstadt"))

        # By the time the second city was asked for, the first city's place was
        # already on disk, visible to another connection.
        assert seen == [0, 1]

    def test_a_stop_event_ends_the_run_and_keeps_what_it_stored(self, settings):
        import threading

        stop = threading.Event()

        class StoppingSource(FakeSource):
            def places_near(self, lat, lon, *, city, radius_km=6):
                found = super().places_near(lat, lon, city=city, radius_km=radius_km)
                stop.set()  # she pressed Cancel while the first city was landing
                return found

        source = StoppingSource(
            {
                "Neuburg an der Donau": [bakery()],
                "Ingolstadt": [bakery(osm_id=10)],
            }
        )
        result = run_contacts(
            settings, source, cities=("Neuburg an der Donau", "Ingolstadt"), stop_event=stop
        )

        assert result.found == 1
        assert result.interrupted is True
        assert source.asked == ["Neuburg an der Donau"]


class TestTheJournal:
    def _run_row(self, settings):
        connection = connect(settings.db_path)
        try:
            return connection.execute(
                "SELECT * FROM runs WHERE kind = 'contacts' ORDER BY id DESC LIMIT 1"
            ).fetchone()
        finally:
            connection.close()

    def test_a_run_row_is_journalled_and_finished(self, settings):
        source = FakeSource({"Neuburg an der Donau": [bakery()]})

        run_contacts(settings, source, cities=("Neuburg an der Donau",))

        row = self._run_row(settings)
        assert row["state"] == "done"
        assert row["contacts_count"] == 1
        assert row["finished_at"]

    def test_an_interrupted_run_says_so_in_the_journal(self, settings):
        import threading

        stop = threading.Event()
        stop.set()
        source = FakeSource({"Neuburg an der Donau": [bakery()]})

        run_contacts(settings, source, cities=("Neuburg an der Donau",), stop_event=stop)

        assert self._run_row(settings)["state"] == "interrupted"

    def test_the_journal_carries_the_errors_it_hit(self, settings):
        source = FakeSource({"Neuburg an der Donau": SourceUnavailable("504")})

        run_contacts(settings, source, cities=("Neuburg an der Donau",))

        assert "504" in (self._run_row(settings)["errors"] or "")


class TestTheImprintStep:
    def test_a_website_only_place_gains_an_email(self, settings):
        source = FakeSource({"Neuburg an der Donau": [website_only()]})

        run_contacts(
            settings,
            source,
            cities=("Neuburg an der Donau",),
            imprint_lookup=lambda place: "hallo@x.example.de",
        )

        connection = connect(settings.db_path)
        try:
            assert contact_by_osm_id(connection, "node/3")["email"] == "hallo@x.example.de"
        finally:
            connection.close()

    def test_a_place_that_already_has_a_route_is_not_looked_up(self, settings):
        looked_up: list[str] = []
        source = FakeSource({"Neuburg an der Donau": [bakery()]})

        run_contacts(
            settings,
            source,
            cities=("Neuburg an der Donau",),
            imprint_lookup=lambda place: looked_up.append(place.name),
        )

        assert looked_up == []

    def test_the_lookup_is_off_unless_asked_for(self, settings):
        source = FakeSource({"Neuburg an der Donau": [website_only()]})

        result = run_contacts(settings, source, cities=("Neuburg an der Donau",))

        assert result.emails_recovered == 0

    def test_a_recovered_email_is_counted(self, settings):
        source = FakeSource({"Neuburg an der Donau": [website_only()]})

        result = run_contacts(
            settings,
            source,
            cities=("Neuburg an der Donau",),
            imprint_lookup=lambda place: "hallo@x.example.de",
        )

        assert result.emails_recovered == 1

    def test_a_lookup_that_finds_nothing_leaves_the_place_alone(self, settings):
        source = FakeSource({"Neuburg an der Donau": [website_only()]})

        result = run_contacts(
            settings,
            source,
            cities=("Neuburg an der Donau",),
            imprint_lookup=lambda place: None,
        )

        assert result.emails_recovered == 0
        connection = connect(settings.db_path)
        try:
            assert contact_by_osm_id(connection, "node/3")["email"] is None
        finally:
            connection.close()

    def test_a_lookup_that_raises_costs_only_that_place(self, settings):
        def exploding(place):
            raise RuntimeError("that site is a maze")

        source = FakeSource({"Neuburg an der Donau": [website_only(), bakery()]})

        result = run_contacts(
            settings, source, cities=("Neuburg an der Donau",), imprint_lookup=exploding
        )

        assert result.found == 2  # the bakery still landed


class TestWhatItReports:
    def test_the_summary_counts_reachable_places(self, settings):
        source = FakeSource({"Neuburg an der Donau": [bakery(), website_only()]})

        result = run_contacts(settings, source, cities=("Neuburg an der Donau",))

        assert result.found == 2
        assert result.reachable == 1  # the website-only place cannot be rung yet
