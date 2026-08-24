"""The generated town list: a country, not a commute.

`city_data.py` is written by `scripts/build_city_list.py` from the GeoNames
extract and committed as source, so the offline suite and the frozen exe both
read plain Python and nothing is fetched at runtime. These tests are what the
generator has to satisfy — they are about the shape and the honesty of the
list, not about any one town's population.
"""

from __future__ import annotations

from jobfinder.city_data import CITIES

STATES = {
    "Baden-Württemberg",
    "Bayern",
    "Berlin",
    "Brandenburg",
    "Bremen",
    "Hamburg",
    "Hessen",
    "Mecklenburg-Vorpommern",
    "Niedersachsen",
    "Nordrhein-Westfalen",
    "Rheinland-Pfalz",
    "Saarland",
    "Sachsen",
    "Sachsen-Anhalt",
    "Schleswig-Holstein",
    "Thüringen",
}


def test_the_list_is_large_enough_to_be_a_country():
    """Thirteen towns was a commute. A job search anywhere in Germany needs
    every town worth naming — which is every one above 15,000 people."""
    assert len(CITIES) > 900


def test_every_german_state_is_represented():
    assert {state for _name, _lat, _lon, _pop, state in CITIES} == STATES


def test_every_town_has_plausible_coordinates():
    for name, lat, lon, _pop, _state in CITIES:
        assert 47.2 < lat < 55.1, f"{name}: latitude {lat} is not in Germany"
        assert 5.8 < lon < 15.1, f"{name}: longitude {lon} is not in Germany"


def test_every_town_is_named_once():
    names = [name for name, *_rest in CITIES]
    duplicates = {name for name in names if names.count(name) > 1}
    assert not duplicates, f"the picker would offer these twice: {duplicates}"


def test_the_big_towns_are_named_in_german():
    """Job sites are searched by town name, so the list has to say what a
    German advert says. GeoNames ships the English exonyms for the two biggest
    Bavarian cities, and they are corrected by hand in the generator."""
    names = {name for name, *_rest in CITIES}

    for german in ("München", "Nürnberg", "Köln", "Hannover", "Braunschweig", "Ibbenbüren"):
        assert german in names
    for english in ("Munich", "Nuremberg", "Cologne", "Hanover", "Ibbenbueren"):
        assert english not in names


def test_the_boroughs_of_the_city_states_are_not_offered_as_towns():
    """Berlin and Hamburg are each one municipality. GeoNames lists their
    districts as places of their own, and a picker that offers `Kreuzberg` and
    `Wandsbek` beside `Berlin` is offering somewhere you cannot apply to."""
    names = {name for name, *_rest in CITIES}

    for borough in ("Kreuzberg", "Neukölln", "Prenzlauer Berg", "Wandsbek", "Altona", "Nippes"):
        assert borough not in names
    for city in ("Berlin", "Hamburg", "Bremen", "Bremerhaven"):
        assert city in names


def test_the_towns_that_look_like_boroughs_but_are_not_survived():
    """The borough rule is a heuristic, so the generator carries a list of the
    towns it would otherwise swallow — real municipalities that happen to sit
    next to a much bigger neighbour."""
    names = {name for name, *_rest in CITIES}

    for town in ("Sankt Ingbert", "Ostfildern", "Hemmingen", "Stockelsdorf", "Grefrath"):
        assert town in names


def test_the_towns_are_ordered_by_size():
    """The picker shows the first few matches for what was typed, so `ber`
    has to put Berlin first — which it does because the list is in this order."""
    populations = [pop for _name, _lat, _lon, pop, _state in CITIES]

    assert populations == sorted(populations, reverse=True)
