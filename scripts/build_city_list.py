"""Regenerate `src/jobfinder/city_data.py` — every German town worth naming.

    pip install geonamescache
    python scripts/build_city_list.py

`geonamescache` ships the GeoNames "cities above 15,000 people" extract as a
JSON file. It is a build-time tool and never a dependency of the app: the town
list is generated once, committed as plain Python, and read offline by both the
test suite and the frozen exe. Re-run this when the extract is updated, read the
diff, and commit it.

Three corrections are applied on the way through, each of them a decision this
file is the record of:

- **Boroughs are not towns.** GeoNames lists city districts as places of their
  own. Berlin and Hamburg are each a single municipality, so their districts go
  wholesale; elsewhere a place is treated as a borough when it sits within 10 km
  of a neighbour at least four times its size in the same state *and* GeoNames
  knows almost no other names for it. That heuristic swallows a handful of real
  municipalities, which are listed in `ALWAYS_KEEP` and put back.
- **The names are German.** The extract carries English exonyms for a few big
  cities and an umlaut-free spelling for others. A German advert says
  `München`, so the list does.
- **The thirteen towns from Phase 4 keep their recorded coordinates**, so
  nothing that was measured against them — distances, the Overpass call-list —
  moves by a few hundred metres for no reason.
"""

from __future__ import annotations

from math import asin, cos, radians, sin, sqrt
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT = REPO_ROOT / "src" / "jobfinder" / "city_data.py"

# GeoNames admin1 codes for Germany, read off the extract itself by checking
# which state each code's biggest city is in.
STATES = {
    "01": "Baden-Württemberg",
    "02": "Bayern",
    "03": "Bremen",
    "04": "Hamburg",
    "05": "Hessen",
    "06": "Niedersachsen",
    "07": "Nordrhein-Westfalen",
    "08": "Rheinland-Pfalz",
    "09": "Saarland",
    "10": "Schleswig-Holstein",
    "11": "Brandenburg",
    "12": "Mecklenburg-Vorpommern",
    "13": "Sachsen",
    "14": "Sachsen-Anhalt",
    "15": "Thüringen",
    "16": "Berlin",
}

# The city-states: one municipality each, except Bremen, which is two. Every
# other place the extract files under these codes is a district.
CITY_STATE_MUNICIPALITIES = {
    "16": {"Berlin"},
    "04": {"Hamburg"},
    "03": {"Bremen", "Bremerhaven"},
}

# What a German advert calls the place.
RENAMED = {
    "Munich": "München",
    "Nuremberg": "Nürnberg",
    "Ibbenbueren": "Ibbenbüren",
    "Meissen": "Meißen",
    "Universitäts- und Hansestadt Greifswald": "Greifswald",
}

# Real municipalities the borough heuristic would otherwise swallow, checked by
# hand against the list it produced on 2026-08-24.
ALWAYS_KEEP = {
    "Sankt Ingbert",
    "Ostfildern",
    "Wetter",
    "Griesheim",
    "Steinhagen",
    "Hemmingen",
    "Korntal",
    "Stockelsdorf",
    "Ratekau",
    "Wardenburg",
    "Grefrath",
    "Wickede",
}

# Two towns can share a name — there is a Friedberg in Bayern and one in
# Hessen, a Senden in each of Bayern and Nordrhein-Westfalen, a Langen in
# Hessen and one in Niedersachsen. Every job source is searched by town *name*,
# and the store keys a posting's city by name too, so a second `Friedberg`
# would be a town nothing could tell apart from the first. The bigger one keeps
# the name and the smaller one is left out, which is the honest version of an
# ambiguity the sources have as well.
BOROUGH_RADIUS_KM = 10.0
BOROUGH_SIZE_RATIO = 4
BOROUGH_MAX_ALIASES = 4

# Phase 4 recorded these by hand; they stay exactly as they were.
PINNED_COORDS = {
    "Neuburg an der Donau": (48.7370, 11.1807),
    "Ingolstadt": (48.7665, 11.4258),
    "München": (48.1351, 11.5820),
    "Erlangen": (49.5964, 11.0044),
    "Nürnberg": (49.4520, 11.0768),
    "Würzburg": (49.7913, 9.9534),
    "Ansbach": (49.3005, 10.5722),
    "Regensburg": (49.0134, 12.1016),
    "Augsburg": (48.3712, 10.8982),
    "Landshut": (48.5366, 12.1512),
    "Bamberg": (49.8981, 10.9030),
    "Bayreuth": (49.9456, 11.5713),
    "Passau": (48.5667, 13.4319),
}


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    a1, o1, a2, o2 = map(radians, (lat1, lon1, lat2, lon2))
    h = sin((a2 - a1) / 2) ** 2 + cos(a1) * cos(a2) * sin((o2 - o1) / 2) ** 2
    return 6371.0 * 2 * asin(sqrt(h))


def german_towns() -> list[dict]:
    """Every German place in the extract, biggest first, districts removed."""
    import geonamescache

    everything = geonamescache.GeonamesCache().get_cities().values()
    places = [
        place
        for place in everything
        if place["countrycode"] == "DE"
        and (
            place["admin1code"] not in CITY_STATE_MUNICIPALITIES
            or place["name"] in CITY_STATE_MUNICIPALITIES[place["admin1code"]]
        )
    ]

    kept: list[dict] = []
    taken: set[str] = set()
    for place in sorted(places, key=lambda p: -p["population"]):
        name = RENAMED.get(place["name"], place["name"])
        if name in taken:
            continue
        if name not in ALWAYS_KEEP and _looks_like_a_borough(place, kept):
            continue
        taken.add(name)
        lat, lon = PINNED_COORDS.get(name, (place["latitude"], place["longitude"]))
        kept.append(
            {
                "name": name,
                "lat": lat,
                "lon": lon,
                "population": place["population"],
                "state": STATES[place["admin1code"]],
                "admin1code": place["admin1code"],
            }
        )
    return kept


def _looks_like_a_borough(place: dict, kept: list[dict]) -> bool:
    """Close to a much bigger neighbour, and known by almost no other name."""
    if len(place["alternatenames"]) > BOROUGH_MAX_ALIASES:
        return False
    return any(
        bigger["admin1code"] == place["admin1code"]
        and bigger["population"] >= BOROUGH_SIZE_RATIO * place["population"]
        and distance_km(bigger["lat"], bigger["lon"], place["latitude"], place["longitude"])
        < BOROUGH_RADIUS_KM
        for bigger in kept
    )


def render(towns: list[dict]) -> str:
    rows = "\n".join(
        f'    ("{town["name"]}", {town["lat"]}, {town["lon"]}, '
        f'{town["population"]}, "{town["state"]}"),'
        for town in towns
    )
    return f'''"""Every German town above 15,000 people — GENERATED, do not edit by hand.

Written by `scripts/build_city_list.py` from the GeoNames extract that
`geonamescache` ships. The decisions behind what is in here — why a borough is
not a town, why the names are German, which coordinates are pinned — are
documented in that script.

Ordered biggest first, which is what makes the town someone means the first
match the picker offers.
"""

from __future__ import annotations

# name, latitude, longitude, population, federal state
CITIES: tuple[tuple[str, float, float, int, str], ...] = (
{rows}
)
'''


def main() -> int:
    try:
        import geonamescache  # noqa: F401
    except ImportError:
        print("geonamescache is not installed. It is a build-time tool only:")
        print("  pip install geonamescache")
        return 1

    towns = german_towns()
    OUTPUT.write_text(render(towns), encoding="utf-8")
    print(f"{len(towns)} towns -> {OUTPUT.relative_to(REPO_ROOT)}")
    print(f"largest:  {towns[0]['name']} ({towns[0]['population']:,})")
    print(f"smallest: {towns[-1]['name']} ({towns[-1]['population']:,})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
