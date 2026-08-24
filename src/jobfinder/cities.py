"""The town list: coordinates, default radius, forgiving name lookup.

Every town that can be searched is known here up front — an unknown one must
fail at second zero with a readable error, never produce an empty result list
after four minutes of searching.

The list itself is generated: `city_data.py` holds every German town above
15,000 people, biggest first, written by `scripts/build_city_list.py`. This
module is what the rest of the app talks to.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, replace

from jobfinder.city_data import CITIES

DEFAULT_RADIUS_KM = 25

# name -> (latitude, longitude), and the two lookups the picker needs beside it
CITY_COORDS: dict[str, tuple[float, float]] = {
    name: (lat, lon) for name, lat, lon, _population, _state in CITIES
}
CITY_STATE: dict[str, str] = {name: state for name, _lat, _lon, _population, state in CITIES}

CITY_NAMES = tuple(CITY_COORDS)

# City name -> (URL slug, Kleinanzeigen location id), recorded by hand from
# their location picker's own links on 2026-08-16 (Bayern page -> Landkreis
# page -> city). The `l{id}` code is a Kleinanzeigen location id, not a city
# name — `l7414` looks like Ingolstadt and is Stockstadt — so the map is a
# deliverable, asserted by a live test, never guessed at runtime.
KLEINANZEIGEN_LOCATIONS: dict[str, tuple[str, str]] = {
    "Neuburg an der Donau": ("neuburg-ad-donau", "6603"),
    "Ingolstadt": ("ingolstadt", "7586"),
    "München": ("muenchen", "6411"),
    "Erlangen": ("erlangen", "6791"),
    "Nürnberg": ("nuernberg", "6810"),
    "Würzburg": ("wuerzburg", "7667"),
    "Ansbach": ("ansbach", "6095"),
    "Regensburg": ("regensburg", "7636"),
    "Augsburg": ("augsburg", "7518"),
    "Landshut": ("landshut", "6388"),
    "Bamberg": ("bamberg", "6885"),
    "Bayreuth": ("bayreuth", "7483"),
    "Passau": ("passau", "7441"),
}


# What postcodes a correct location id actually returns, recorded from the
# live site on 2026-08-16 by reading the ads each id produced. The live test
# checks *this* rather than the city name, because big cities label their ads
# by borough — Nürnberg's browse says "Mitte" and "Südstadt", never
# "Nürnberg", and a name check called a perfectly good id wrong. A misrouted
# id shows up here immediately: Stockstadt's ads are 63xxx, Ingolstadt's 85xxx.
# Erlangen is absent on purpose — its browse had no ads the day this was
# recorded, and a guessed prefix would be worse than none.
KLEINANZEIGEN_PLZ_PREFIXES: dict[str, tuple[str, ...]] = {
    "Neuburg an der Donau": ("86",),
    "Ingolstadt": ("85",),
    "München": ("80", "81"),
    "Nürnberg": ("90",),
    "Würzburg": ("97",),
    "Ansbach": ("91",),
    "Regensburg": ("93",),
    "Augsburg": ("86",),
    "Landshut": ("84",),
    "Bamberg": ("96",),
    "Bayreuth": ("95",),
    "Passau": ("94",),
}


def kleinanzeigen_location(name: str) -> tuple[str, str] | None:
    """The (slug, location id) pair for a city — None when it is not mapped.

    Accepts the same umlaut-free spellings `resolve_city` does, so one
    keyboard produces both answers.
    """
    if name in KLEINANZEIGEN_LOCATIONS:
        return KLEINANZEIGEN_LOCATIONS[name]
    try:
        canonical = resolve_city(name).name
    except ValueError:
        return None
    return KLEINANZEIGEN_LOCATIONS.get(canonical)


# A keyboard without umlauts produces both "Muenchen" and "Munchen" — accept either.
_FULL = {"ü": "ue", "ö": "oe", "ä": "ae", "ß": "ss"}
_BARE = {"ü": "u", "ö": "o", "ä": "a", "ß": "s"}


def _variants(name: str) -> set[str]:
    """Lowercased spellings a name can be typed as: {'muenchen', 'munchen'}."""
    lowered = name.lower()
    full = lowered
    for source, target in _FULL.items():
        full = full.replace(source, target)
    bare = lowered
    for source, target in _BARE.items():
        bare = bare.replace(source, target)
    return {lowered, full, bare}


@dataclass(frozen=True)
class City:
    name: str
    lat: float
    lon: float
    radius_km: int = DEFAULT_RADIUS_KM

    def with_radius(self, radius_km: int) -> City:
        return replace(self, radius_km=radius_km)


# Every spelling of every town, worked out once at import rather than on each
# keystroke: nine hundred towns times three spellings is cheap to build and not
# something to rebuild while someone is typing.
_SPELLINGS: tuple[tuple[str, frozenset[str]], ...] = tuple(
    (name, frozenset(_variants(name))) for name in CITY_NAMES
)

SEARCH_LIMIT = 20


def search_cities(query: str, limit: int = SEARCH_LIMIT, exclude: object = ()) -> list[str]:
    """The towns worth offering for what has been typed so far.

    Towns that *start* with it first, then the ones that merely contain it,
    each group biggest first — because someone typing `ber` means Berlin, and
    someone typing `burg` probably means a town called Burg-something rather
    than Augsburg. Empty query means "the biggest towns", so the picker has
    something on it before a single key is pressed.
    """
    skip = set(exclude or ())
    typed = _variants(query.strip())
    if not query.strip():
        return [name for name in CITY_NAMES if name not in skip][:limit]

    starts: list[str] = []
    contains: list[str] = []
    for name, spellings in _SPELLINGS:
        if name in skip:
            continue
        if any(spelling.startswith(word) for spelling in spellings for word in typed):
            starts.append(name)
        elif any(word in spelling for spelling in spellings for word in typed):
            contains.append(name)
    return (starts + contains)[:limit]


def _suggestions(name: str) -> list[str]:
    """The two or three towns someone probably meant."""
    found = search_cities(name, limit=3)
    if found:
        return found
    folded = {spelling: town for town, spellings in _SPELLINGS for spelling in spellings}
    close = difflib.get_close_matches(_variants(name).pop(), list(folded), n=3, cutoff=0.7)
    # dict.fromkeys keeps the order and drops the town a second spelling of it
    # would otherwise name twice.
    return list(dict.fromkeys(folded[spelling] for spelling in close))


def resolve_city(name: str) -> City:
    """One town by name — exact, cased, or umlaut-folded — or a readable error."""
    if name in CITY_COORDS:
        lat, lon = CITY_COORDS[name]
        return City(name=name, lat=lat, lon=lon)

    variants = _variants(name)
    for canonical, (lat, lon) in CITY_COORDS.items():
        if variants & _variants(canonical):
            return City(name=canonical, lat=lat, lon=lon)

    # Naming every valid town was the helpful answer when there were thirteen.
    # There are nine hundred, so it names the ones that look like what was
    # meant instead.
    suggestions = _suggestions(name)
    hint = f" Did you mean {', '.join(suggestions)}?" if suggestions else ""
    raise ValueError(
        f"Unknown town '{name}'.{hint} "
        "Pick one from the list on the Search page — umlaut-free spellings "
        "like 'Muenchen' work too."
    )
