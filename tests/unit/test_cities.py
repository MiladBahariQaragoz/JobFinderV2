"""The town list — coordinates, radius defaults, forgiving lookup.

Bavarian until 2026-08-24, when the app stopped being for one commute and
became a job search anywhere in Germany. What is asserted here is the lookup;
the shape of the generated list itself is `test_city_data.py`.
"""

from __future__ import annotations

import pytest

from jobfinder.cities import (
    CITY_COORDS,
    CITY_NAMES,
    KLEINANZEIGEN_LOCATIONS,
    kleinanzeigen_location,
    resolve_city,
)


def test_a_town_anywhere_in_germany_resolves():
    """The list is no longer a commute from Neuburg."""
    for name in ("Leipzig", "Hamburg", "Köln", "Flensburg", "Konstanz"):
        assert resolve_city(name).name == name


def test_the_towns_phase_4_recorded_kept_their_coordinates():
    """Distances and the Overpass call-list were measured against these."""
    assert resolve_city("Neuburg an der Donau").lat == 48.7370
    assert resolve_city("München").lon == 11.5820


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


def test_the_list_is_the_generated_one():
    from jobfinder.city_data import CITIES

    assert len(CITY_COORDS) == len(CITIES)
    assert CITY_NAMES[0] == "Berlin"  # biggest first, which the picker relies on


# -- the Kleinanzeigen location map (Phase 6) -------------------------------------
#
# Ids recorded by hand from their location picker's own links on 2026-08-16
# (Bayern page -> Landkreis page -> city). A wrong id silently returns jobs
# in the wrong part of Germany, which is worse than an error — so every city
# must have one, and the live test asserts each id still resolves to its city.


def test_every_recorded_location_is_a_town_the_app_knows():
    """The ids are hand-recorded for thirteen towns and cannot be derived for a
    thousand, so the map is a subset now — but never of towns that do not
    exist, which is how a typo in it would show up."""
    unknown = [name for name in KLEINANZEIGEN_LOCATIONS if name not in CITY_COORDS]
    assert not unknown, f"Kleinanzeigen location id for a town not in the list: {unknown}"
    assert len(KLEINANZEIGEN_LOCATIONS) == 13


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


def test_every_mapped_location_has_a_recorded_postcode_prefix():
    """A typo'd city name in one map and not the other would go unnoticed."""
    from jobfinder.cities import KLEINANZEIGEN_LOCATIONS, KLEINANZEIGEN_PLZ_PREFIXES

    unknown = set(KLEINANZEIGEN_PLZ_PREFIXES) - set(KLEINANZEIGEN_LOCATIONS)
    assert not unknown, f"postcode prefixes for cities that have no location id: {unknown}"
    # Erlangen is the one deliberate gap: its browse had no ads the day the
    # prefixes were recorded, and a guessed prefix is worse than none.
    assert set(KLEINANZEIGEN_LOCATIONS) - set(KLEINANZEIGEN_PLZ_PREFIXES) == {"Erlangen"}


# -- finding a town by typing the first letters of it -----------------------------
#
# A thousand towns is not a list of checkboxes. What the picker does instead is
# ask for two or three letters and offer what matches: the towns that *start*
# with them first, then the ones that merely contain them, each group biggest
# first, because the town someone means is almost always the big one.


class TestSearchingForATown:
    def test_two_letters_are_enough(self):
        from jobfinder.cities import search_cities

        assert "Ingolstadt" in search_cities("in")

    def test_the_biggest_match_comes_first(self):
        from jobfinder.cities import search_cities

        assert search_cities("ber")[0] == "Berlin"

    def test_a_prefix_beats_a_longer_word_that_merely_contains_it(self):
        from jobfinder.cities import search_cities

        matches = search_cities("burg")

        assert matches.index("Burghausen") < matches.index("Augsburg")

    def test_the_umlaut_free_spellings_find_the_town(self):
        from jobfinder.cities import search_cities

        assert "München" in search_cities("muenchen")
        assert "München" in search_cities("munchen")
        assert "Nürnberg" in search_cities("nurn")

    def test_the_answer_is_bounded(self):
        """The page renders what comes back, so this is what keeps a single
        keystroke from putting nine hundred checkboxes on it."""
        from jobfinder.cities import search_cities

        assert len(search_cities("e")) <= 20
        assert len(search_cities("e", limit=5)) == 5

    def test_nothing_matching_is_an_empty_list_not_an_error(self):
        from jobfinder.cities import search_cities

        assert search_cities("zzzz") == []

    def test_an_empty_query_offers_the_biggest_towns(self):
        """Opening the picker without typing shows somewhere to start."""
        from jobfinder.cities import search_cities

        assert search_cities("")[:2] == ["Berlin", "Hamburg"]

    def test_towns_already_chosen_are_not_offered_again(self):
        from jobfinder.cities import search_cities

        assert "Berlin" not in search_cities("ber", exclude=["Berlin"])


class TestTheRefusalStaysReadable:
    def test_an_unknown_town_names_the_nearest_ones_not_all_of_them(self):
        """Listing every valid name was a helpful sentence when there were
        thirteen. With nine hundred it is a wall, so it suggests instead."""
        with pytest.raises(ValueError) as exc:
            resolve_city("Munchehn")

        message = str(exc.value)
        assert "Munchehn" in message
        assert len(message) < 300

    def test_a_near_miss_is_suggested(self):
        with pytest.raises(ValueError) as exc:
            resolve_city("Ingolstad")

        assert "Ingolstadt" in str(exc.value)
