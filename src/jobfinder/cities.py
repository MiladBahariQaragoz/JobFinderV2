"""The Bavarian city list: coordinates, default radius, forgiving name lookup.

Every city she can search is known here up front — an unknown city must fail at
second zero with a readable error, never produce an empty result list after four
minutes of searching.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

DEFAULT_RADIUS_KM = 25

# name -> (latitude, longitude)
CITY_COORDS: dict[str, tuple[float, float]] = {
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

CITY_NAMES = tuple(CITY_COORDS)

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


def resolve_city(name: str) -> City:
    """One city by name — exact, cased, or umlaut-folded — or a readable error."""
    if name in CITY_COORDS:
        lat, lon = CITY_COORDS[name]
        return City(name=name, lat=lat, lon=lon)

    variants = _variants(name)
    for canonical, (lat, lon) in CITY_COORDS.items():
        if variants & _variants(canonical):
            return City(name=canonical, lat=lat, lon=lon)

    raise ValueError(
        f"Unknown city '{name}'. "
        f"Valid cities are: {', '.join(CITY_NAMES)}. "
        "Umlaut-free spellings like 'Muenchen' also work."
    )
