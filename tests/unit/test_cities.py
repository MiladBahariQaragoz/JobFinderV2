"""The Bavarian city list — coordinates, radius defaults, forgiving lookup."""

from __future__ import annotations

import pytest

from jobfinder.cities import (
    CITY_COORDS,
    CITY_NAMES,
    KLEINANZEIGEN_LOCATIONS,
    kleinanzeigen_location,
    resolve_city,
)


def test_unknown_city_lists_the_valid_ones():
    with pytest.raises(ValueError) as exc:
        resolve_city("Leipzig")

    message = str(exc.value)
    assert "Leipzig" in message
    for known in ("Neuburg an der Donau", "Ingolstadt", "München", "Nürnberg"):
        assert known in message


def test_city_radius_defaults_to_25km_and_can_be_overridden():
    ingolstadt = resolve_city("Ingolstadt")

    assert ingolstadt.radius_km == 25

    wider = ingolstadt.with_radius(50)

    assert wider.radius_km == 50
    assert wider.name == ingolstadt.name  # a copy, not a mutation


def test_lookup_accepts_umlaut_free_and_cased_spellings():
    assert resolve_city("Muenchen").name == "München"
    assert resolve_city("NUERNBERG").name == "Nürnberg"
    assert resolve_city("neuburg an der donau").name == "Neuburg an der Donau"


def test_every_city_has_plausible_coordinates():
    for name, (lat, lon) in CITY_COORDS.items():
        assert 47 < lat < 51, f"{name}: latitude {lat} is not in Bavaria"
        assert 8 < lon < 14, f"{name}: longitude {lon} is not in Bavaria"


# -- the Kleinanzeigen location map (Phase 6) -------------------------------------
#
# Ids recorded by hand from their location picker's own links on 2026-08-16
# (Bayern page -> Landkreis page -> city). A wrong id silently returns jobs
# in the wrong part of Germany, which is worse than an error — so every city
# must have one, and the live test asserts each id still resolves to its city.


def test_every_searchable_city_has_a_kleinanzeigen_location():
    missing = [name for name in CITY_NAMES if name not in KLEINANZEIGEN_LOCATIONS]
    assert not missing, f"no Kleinanzeigen location id recorded for: {missing}"


def test_each_entry_pairs_a_slug_with_a_numeric_id():
    for name, (slug, location_id) in KLEINANZEIGEN_LOCATIONS.items():
        assert slug == slug.lower() and " " not in slug, name
        assert location_id.isdigit(), name


def test_lookup_returns_the_recorded_pair():
    assert kleinanzeigen_location("Ingolstadt") == ("ingolstadt", "7586")


def test_lookup_folds_umluats_the_way_she_types_them():
    assert kleinanzeigen_location("Muenchen") == ("muenchen", "6411")


def test_a_city_outside_the_map_has_no_location(self=None):
    assert kleinanzeigen_location("Leipzig") is None
