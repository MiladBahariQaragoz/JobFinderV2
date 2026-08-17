"""Overpass still answers, and Neuburg still has places worth ringing.

The one question a live test should ask (§7): is the contract this adapter was
built against still true? Three things could break it silently —

- the endpoint list could all go dark (measured 2026-08-17: they can, together,
  when this machine has been asking too much);
- the tag vocabulary could shift (`tourism=hotel` is the one MASTER_PLAN got
  wrong, so it is asserted rather than assumed);
- the answers could arrive with no contact details at all, which would leave her
  a list of names she cannot ring.

Slow and deliberately gentle: one tag, one town, at the polite gap. This test
**skips** rather than fails when Overpass refuses the machine, because "the
service is rate-limiting us today" is not a broken contract — the adapter is
built for exactly that, and a red suite would be lying about which.

`pytest -m live`.
"""

from __future__ import annotations

import pytest

from jobfinder.cities import resolve_city
from jobfinder.sources.http import PoliteClient
from jobfinder.sources.overpass import (
    ENDPOINTS,
    REQUEST_GAP_SECONDS,
    TAGS,
    OverpassSource,
)

pytestmark = pytest.mark.live


def build_source(tmp_path, tags):
    client = PoliteClient(
        cache_dir=tmp_path / "http-cache",
        budget=20,
        min_delay=REQUEST_GAP_SECONDS,
    )
    return OverpassSource(client, tags=tags)


def test_neuburg_still_returns_places_with_contact_details(tmp_path):
    """One tag, one town. `shop=bakery` because a bakery is the top of her list
    and there are eleven of them in Neuburg."""
    city = resolve_city("Neuburg an der Donau")
    source = build_source(tmp_path, (("shop", "bakery"),))

    places = source.places_near(city.lat, city.lon, city=city.name, radius_km=6)

    if not places and source.failures:
        pytest.skip(f"Overpass is not answering this machine: {source.failures[0]}")

    assert places, "Neuburg returned no bakeries at all — the tag or the area query changed"
    reachable = [place for place in places if place.has_direct_route]
    assert reachable, "bakeries came back but none had a phone or an email"
    assert all(place.name for place in places)
    assert all(place.city == "Neuburg an der Donau" for place in places)


def test_hotels_are_still_under_the_tourism_tag(tmp_path):
    """The correction this phase is built on. If `amenity=hotel` ever starts
    answering, this test is the place that finds out."""
    city = resolve_city("Neuburg an der Donau")
    source = build_source(tmp_path, (("tourism", "hotel"),))

    places = source.places_near(city.lat, city.lon, city=city.name, radius_km=6)

    if not places and source.failures:
        pytest.skip(f"Overpass is not answering this machine: {source.failures[0]}")

    assert places, "no hotels under tourism=hotel — the tag moved"
    # Not *every* result is labelled `hotel`: a place carrying `amenity=restaurant`
    # as well is labelled by its amenity (her list has one, `Gasthof Neuwirt`).
    # What the contract needs is that the tag still finds hotels at all.
    assert any(place.kind == "hotel" for place in places)


def test_the_endpoint_list_still_has_a_working_member(tmp_path):
    """Not a contract with Overpass so much as with the fallback list itself:
    if every host in it is dead, the list needs a new member, and that is a
    finding rather than a mystery."""
    city = resolve_city("Neuburg an der Donau")
    source = OverpassSource(
        PoliteClient(cache_dir=None, budget=20, min_delay=REQUEST_GAP_SECONDS),
        tags=(("shop", "bakery"),),
        attempts=len(ENDPOINTS),
    )

    places = source.places_near(city.lat, city.lon, city=city.name, radius_km=6)

    if not places and source.failures:
        pytest.skip(
            "every endpoint refused; if this persists across days, the list in "
            f"sources/overpass.py needs a new member: {source.failures[0]}"
        )
    assert places


def test_every_tag_in_the_list_is_one_overpass_understands():
    """Cheap and offline-ish: a typo in a tag key would fail silently as "no
    places of that kind", which looks exactly like a quiet town."""
    valid_keys = {"amenity", "shop", "tourism", "office", "craft"}
    for key, value in TAGS:
        assert key in valid_keys, f"{key} is not an OSM key this adapter should use"
        assert value == value.lower().strip()
        assert " " not in value
