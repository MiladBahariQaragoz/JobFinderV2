"""The Bavarian city list — coordinates, radius defaults, forgiving lookup."""

from __future__ import annotations

import pytest

from jobfinder.cities import CITY_COORDS, resolve_city


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
