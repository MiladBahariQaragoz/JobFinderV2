"""The cold-contact source: places that hire without ever posting a job.

The fixture is the real Neuburg an der Donau answer, recorded from
`gall.openstreetmap.de` on 2026-08-17 — 118 places, 110 named, 34 with a phone
or an email, 18 of them mapped as ways rather than nodes. Recorded, never
hand-written (§7), because every assumption in this file was wrong about
something before the payload was read.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jobfinder.sources.http import SourceUnavailable
from jobfinder.sources.overpass import (
    ENDPOINTS,
    OverpassSource,
    parse_places,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "overpass" / "neuburg_places.json"
NEUBURG = (48.7325, 11.1878)


@pytest.fixture(scope="module")
def payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def places(payload) -> list:
    return parse_places(payload["elements"], city="Neuburg an der Donau")


def by_name(places, name):
    return next((place for place in places if place.name == name), None)


def element(osm_type="node", osm_id=1, **tags):
    """One Overpass element, in the shape the real payload uses."""
    return {"type": osm_type, "id": osm_id, "tags": tags}


class FakeClient:
    """Answers each POST from a script; records the bodies it was given."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.bodies: list[str] = []
        self.urls: list[str] = []

    def post_json(self, url, *, body, headers=None):
        self.bodies.append(body)
        self.urls.append(url)
        answer = self.answers.pop(0) if self.answers else {"elements": []}
        if isinstance(answer, Exception):
            raise answer
        return answer


class TestParsingTheRealPayload:
    def test_the_fixture_parses_places_with_and_without_contact_details(self, places):
        assert len(places) > 30
        assert any(place.phone for place in places)
        assert any(place.email for place in places)

    def test_a_place_with_no_name_is_skipped(self):
        parsed = parse_places(
            [{"type": "node", "id": 1, "tags": {"amenity": "cafe", "phone": "+49 8431 20781"}}],
            city="Neuburg an der Donau",
        )

        assert parsed == []

    def test_a_place_with_no_contact_route_at_all_is_excluded(self):
        parsed = parse_places(
            [{"type": "node", "id": 1, "tags": {"amenity": "cafe", "name": "Ohne Kontakt"}}],
            city="Neuburg an der Donau",
        )

        assert parsed == []

    def test_a_place_with_only_a_website_is_kept_for_the_imprint_step(self):
        parsed = parse_places(
            [
                {
                    "type": "node",
                    "id": 1,
                    "tags": {
                        "amenity": "cafe",
                        "name": "Nur Website",
                        "website": "https://cafe.example.de",
                    },
                }
            ],
            city="Neuburg an der Donau",
        )

        assert [place.name for place in parsed] == ["Nur Website"]
        assert parsed[0].phone is None and parsed[0].email is None
        assert parsed[0].website == "https://cafe.example.de"

    def test_both_the_plain_and_the_contact_prefixed_tags_are_read(self):
        """OSM carries `phone` and `contact:phone` interchangeably — 9 of her
        118 places use the prefixed form, and reading only one loses them."""
        parsed = parse_places(
            [
                {
                    "type": "node",
                    "id": 1,
                    "tags": {
                        "amenity": "cafe",
                        "name": "Prefixed",
                        "contact:phone": "+49 8431 20782",
                        "contact:email": "hallo@cafe.example.de",
                        "contact:website": "https://cafe.example.de",
                    },
                }
            ],
            city="Neuburg an der Donau",
        )

        assert parsed[0].phone == "+49843120782"
        assert parsed[0].email == "hallo@cafe.example.de"
        assert parsed[0].website == "https://cafe.example.de"

    def test_ways_are_parsed_as_well_as_nodes(self, payload):
        """18 of her 118 places are ways — a POI mapped as a building. A
        node-only query loses 15 % of the list."""
        ways = [element for element in payload["elements"] if element["type"] == "way"]
        parsed = parse_places(ways, city="Neuburg an der Donau")

        assert parsed, "no way-mapped place survived parsing"

    def test_hotels_come_from_the_tourism_tag_not_the_amenity_one(self, places):
        """MASTER_PLAN asked for `amenity=hotel`, which returns nothing at all.
        Hotels are `tourism=hotel` — 9 in Neuburg, and a hotel kitchen is one of
        the best fits in the list for someone with little German."""
        assert any(place.kind == "hotel" for place in places)

    def test_the_street_and_house_number_become_one_address_line(self):
        parsed = parse_places(
            [
                {
                    "type": "node",
                    "id": 1,
                    "tags": {
                        "shop": "bakery",
                        "name": "Bäckerei Müller & Söhne",
                        "phone": "+49 8431 20783",
                        "addr:street": "Färberstraße",
                        "addr:housenumber": "12",
                    },
                }
            ],
            city="Neuburg an der Donau",
        )

        assert parsed[0].street == "Färberstraße 12"

    def test_a_street_without_a_number_is_still_an_address(self):
        parsed = parse_places(
            [
                {
                    "type": "node",
                    "id": 1,
                    "tags": {
                        "shop": "bakery",
                        "name": "Ohne Nummer",
                        "phone": "+49 8431 20784",
                        "addr:street": "Färberstraße",
                    },
                }
            ],
            city="Neuburg an der Donau",
        )

        assert parsed[0].street == "Färberstraße"

    def test_the_city_is_the_one_that_was_searched(self, places):
        assert {place.city for place in places} == {"Neuburg an der Donau"}

    def test_umlauts_survive_the_parse(self, places):
        assert any("ä" in place.name or "ü" in place.name or "ö" in place.name for place in places)


class TestIdentity:
    def test_a_contact_id_is_stable_across_runs(self, payload):
        first = parse_places(payload["elements"], city="Neuburg an der Donau")
        second = parse_places(payload["elements"], city="Neuburg an der Donau")

        assert [place.contact_id for place in first] == [place.contact_id for place in second]

    def test_the_id_is_built_from_the_osm_type_and_id(self):
        parsed = parse_places(
            [
                {
                    "type": "way",
                    "id": 42,
                    "tags": {"amenity": "cafe", "name": "X", "phone": "+4984312071"},
                }
            ],
            city="Neuburg an der Donau",
        )

        assert parsed[0].contact_id == "way/42"

    def test_a_node_and_a_way_with_the_same_number_are_different_places(self):
        parsed = parse_places(
            [
                {
                    "type": "node",
                    "id": 7,
                    "tags": {"amenity": "cafe", "name": "A", "phone": "+4984312071"},
                },
                {
                    "type": "way",
                    "id": 7,
                    "tags": {"amenity": "cafe", "name": "B", "phone": "+4984312072"},
                },
            ],
            city="Neuburg an der Donau",
        )

        assert len({place.contact_id for place in parsed}) == 2


class TestQueryingTheSource:
    def test_one_request_is_made_per_tag(self, payload):
        client = FakeClient([{"elements": []} for _ in range(20)])
        source = OverpassSource(client)

        source.places_near(*NEUBURG, city="Neuburg an der Donau", radius_km=6)

        assert len(client.bodies) == len(source.tags)

    def test_each_query_carries_its_tag_and_the_radius_in_metres(self):
        client = FakeClient([{"elements": []} for _ in range(20)])
        source = OverpassSource(client)

        source.places_near(*NEUBURG, city="Neuburg an der Donau", radius_km=6)

        joined = "\n".join(client.bodies)
        assert 'nwr(around:6000,48.7325,11.1878)["amenity"="restaurant"]' in joined
        assert '["tourism"="hotel"]' in joined
        assert '["shop"="bakery"]' in joined
        assert "node(" not in joined  # nwr, never node-only

    def test_a_place_seen_in_two_tag_queries_appears_once(self):
        element = {
            "type": "node",
            "id": 5,
            "tags": {"amenity": "cafe", "shop": "bakery", "name": "Beides", "phone": "+4984312091"},
        }
        client = FakeClient([{"elements": [element]}, {"elements": [element]}])
        source = OverpassSource(client, tags=(("amenity", "cafe"), ("shop", "bakery")))

        found = source.places_near(*NEUBURG, city="Neuburg an der Donau", radius_km=6)

        assert [place.contact_id for place in found] == ["node/5"]

    def test_a_failing_tag_costs_that_tag_and_not_the_city(self):
        """Measured: firing nine tag queries at Overpass, six failed at least
        once and one failed four times. A run that gives up on the first refusal
        would return nothing on a normal day."""
        good = {
            "elements": [
                {
                    "type": "node",
                    "id": 1,
                    "tags": {"shop": "bakery", "name": "Bäckerei", "phone": "+4984312071"},
                }
            ]
        }
        client = FakeClient([SourceUnavailable("overpass said 504"), good])
        # attempts=1 isolates the rule under test: one refusal, one lost tag.
        source = OverpassSource(client, tags=(("amenity", "cafe"), ("shop", "bakery")), attempts=1)

        found = source.places_near(*NEUBURG, city="Neuburg an der Donau", radius_km=6)

        assert [place.name for place in found] == ["Bäckerei"]
        assert source.failures == ["amenity=cafe: overpass said 504"]

    def test_every_tag_failing_reports_them_all_and_returns_nothing(self):
        client = FakeClient([SourceUnavailable("504"), SourceUnavailable("504")])
        source = OverpassSource(client, tags=(("amenity", "cafe"), ("shop", "bakery")), attempts=1)

        assert source.places_near(*NEUBURG, city="Neuburg an der Donau", radius_km=6) == []
        assert len(source.failures) == 2

    def test_the_endpoint_list_has_more_than_one_member(self):
        """The canonical host answered 504 for four minutes on 2026-08-17 while
        its own backends served the same query instantly. One hard-coded host
        would have made this source look permanently dead."""
        assert len(ENDPOINTS) >= 2
        assert all(url.endswith("/api/interpreter") for url in ENDPOINTS)

    def test_a_failing_endpoint_falls_through_to_the_next_one(self):
        good = {
            "elements": [
                {
                    "type": "node",
                    "id": 1,
                    "tags": {"amenity": "cafe", "name": "Café", "phone": "+4984312071"},
                }
            ]
        }
        client = FakeClient([SourceUnavailable("504"), good])
        source = OverpassSource(client, tags=(("amenity", "cafe"),), attempts=2)

        found = source.places_near(*NEUBURG, city="Neuburg an der Donau", radius_km=6)

        assert [place.name for place in found] == ["Café"]
        assert client.urls[0] != client.urls[1]  # a different endpoint the second time
        assert source.failures == []

    def test_the_endpoint_that_last_answered_is_tried_first(self):
        """Measured twice on 2026-08-17, four hours apart, with opposite results:
        the two endpoints that answered in under a second in the morning were
        refusing TCP connections by midday, while one that had been failing was
        the fast one. A dead host costs ~21 s to discover, so once a run finds a
        host that answers it stays on it — otherwise nine tags pay that toll
        nine times over.
        """
        good = {"elements": [element(amenity="cafe", name="Café", phone="+4984312071")]}
        client = FakeClient([SourceUnavailable("504"), good, good])
        source = OverpassSource(client, tags=(("amenity", "cafe"), ("amenity", "bar")), attempts=2)

        source.places_near(*NEUBURG, city="Neuburg an der Donau", radius_km=6)

        # First tag: endpoint one refused, endpoint two answered. Second tag
        # must start at endpoint two rather than paying for one again.
        assert client.urls[1] == client.urls[2]

    def test_a_malformed_answer_is_a_failure_not_a_crash(self):
        client = FakeClient([{"no elements here": True}])
        source = OverpassSource(client, tags=(("amenity", "cafe"),), attempts=1)

        assert source.places_near(*NEUBURG, city="Neuburg an der Donau", radius_km=6) == []
        assert source.failures
