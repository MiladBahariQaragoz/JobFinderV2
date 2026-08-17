"""`jobfinder contacts` — the call-list from a terminal.

What it prints is the whole interface: how many places, how many she can reach
today, per city, and where the CSV is. A run that says "done" and nothing else
leaves her wondering whether it worked.
"""

from __future__ import annotations

import pytest

from jobfinder.cli import main
from jobfinder.store.contacts import list_contacts
from jobfinder.store.db import connect, migrate


def element(osm_type="node", osm_id=1, **tags):
    return {"type": osm_type, "id": osm_id, "tags": tags}


class FakeSource:
    failures: list[str] = []

    def __init__(self, by_city):
        self.by_city = dict(by_city)

    def places_near(self, lat, lon, *, city, radius_km=6):
        from jobfinder.sources.overpass import parse_places

        answer = self.by_city.get(city, [])
        if isinstance(answer, Exception):
            raise answer
        return parse_places(answer, city=city)


@pytest.fixture
def project(tmp_path):
    connection = connect(tmp_path / "data" / "jobfinder.db")
    migrate(connection)
    connection.close()
    return tmp_path


def bakery(osm_id=1, name="Bäckerei Müller"):
    return element("node", osm_id, shop="bakery", name=name, phone="+498431648595")


def website_only(osm_id=3, name="Nur Website"):
    return element("node", osm_id, amenity="cafe", name=name, website="https://x.example.de")


def run(project, capsys, source, *extra):
    code = main(
        ["contacts", "--root", str(project), "--cities", "Neuburg an der Donau", *extra],
        _contacts_source=lambda settings, client: source,
    )
    return code, capsys.readouterr().out


class TestTheCommand:
    def test_the_command_stores_contacts_and_writes_the_csv(self, project, capsys):
        source = FakeSource({"Neuburg an der Donau": [bakery()]})

        code, out = run(project, capsys, source)

        assert code == 0
        connection = connect(project / "data" / "jobfinder.db")
        try:
            assert len(list_contacts(connection)) == 1
        finally:
            connection.close()
        assert (project / "data" / "contacts.csv").exists()
        assert "contacts.csv" in out

    def test_it_says_how_many_places_and_how_many_are_reachable(self, project, capsys):
        source = FakeSource({"Neuburg an der Donau": [bakery(), website_only()]})

        _code, out = run(project, capsys, source)

        assert "2" in out
        assert "reach" in out.lower()

    def test_this_run_and_the_whole_list_are_not_mixed_in_one_sentence(self, project, capsys):
        """Seen for real: "53 places, 255 you can reach today" — 53 was this
        run's count and 255 was the whole store's, so the sentence claimed she
        could reach five times more places than the run had found. The same
        mistake the page header made."""
        first = FakeSource({"Neuburg an der Donau": [bakery(1, "Erste"), bakery(2, "Zweite")]})
        run(project, capsys, first)

        # A second run over one city only: it finds 1, the list still holds 3.
        second = FakeSource({"Neuburg an der Donau": [bakery(3, "Dritte")]})
        _code, out = run(project, capsys, second)

        assert "Found 1 place" in out
        assert "Your list now holds" in out
        assert "3" in out.split("Your list now holds")[1]

    def test_it_says_what_it_found_per_city(self, project, capsys):
        source = FakeSource(
            {"Neuburg an der Donau": [bakery()], "Ingolstadt": [bakery(osm_id=9, name="Ingo")]}
        )

        code = main(
            [
                "contacts",
                "--root",
                str(project),
                "--cities",
                "Neuburg an der Donau,Ingolstadt",
            ],
            _contacts_source=lambda settings, client: source,
        )
        out = capsys.readouterr().out

        assert code == 0
        assert "Neuburg an der Donau" in out
        assert "Ingolstadt" in out

    def test_a_city_with_no_places_says_so_rather_than_nothing(self, project, capsys):
        source = FakeSource({"Neuburg an der Donau": []})

        code, out = run(project, capsys, source)

        assert code == 0
        assert "0" in out

    def test_a_source_failure_is_reported_and_the_command_still_succeeds(self, project, capsys):
        from jobfinder.sources.http import SourceUnavailable

        source = FakeSource({"Neuburg an der Donau": SourceUnavailable("overpass said 504")})

        code, out = run(project, capsys, source)

        assert code == 0  # one dead source never fails a run
        assert "504" in out

    def test_the_top_of_the_list_is_printed_so_she_can_start_calling(self, project, capsys):
        source = FakeSource({"Neuburg an der Donau": [bakery(name="Bäckerei Schlegl")]})

        _code, out = run(project, capsys, source)

        assert "Bäckerei Schlegl" in out
        assert "+498431648595" in out

    def test_the_imprint_lookup_is_off_unless_asked_for(self, project, capsys):
        source = FakeSource({"Neuburg an der Donau": [website_only()]})

        _code, out = run(project, capsys, source)

        assert "--imprint" in out  # offered, not done behind her back

    def test_the_radius_can_be_widened(self, project, capsys):
        asked: list[int] = []

        class RecordingSource(FakeSource):
            def places_near(self, lat, lon, *, city, radius_km=6):
                asked.append(radius_km)
                return super().places_near(lat, lon, city=city, radius_km=radius_km)

        source = RecordingSource({"Neuburg an der Donau": [bakery()]})

        run(project, capsys, source, "--radius", "12")

        assert asked == [12]
