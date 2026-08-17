"""OpenStreetMap Overpass — the places that hire without ever posting a job.

Every other source in this app finds employers who advertised. This one finds
the restaurants, cafés, bakeries and hotel kitchens that never advertise and
hire when someone calls. It is the cold-contact engine behind Phase 9.

Five things were measured from this machine on 2026-08-17, and each one is a
constraint the code below obeys rather than a preference:

- **`nwr`, not `node`.** 18 of Neuburg's 118 places are mapped as ways — a POI
  drawn as a building. A node-only query loses 15 % of the list.
- **Hotels are `tourism=hotel`.** `amenity=hotel` returns nothing at all, and a
  hotel kitchen is one of the best fits in the list for someone with little
  German.
- **One request per tag.** The union of all nine tags answered `504`; the nine
  small queries answered in seconds. A per-tag request also means a refused tag
  costs one kind of place instead of the whole city.
- **The canonical endpoint cannot be relied on.**
  `overpass-api.de/api/interpreter` refused every attempt across four minutes
  while its own announced backends served the same query instantly, with
  `api/status` reporting free slots. Hence a list of endpoints, tried in turn.
- **429 and 504 are normal.** Nine back-to-back queries produced six failures.
  The client's spacing and backoff carry that; this module only has to survive
  a tag that never arrives.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from jobfinder.phones import normalize_phone
from jobfinder.sources.http import SourceUnavailable

# Tried in order, one per attempt. `overpass-api.de` is deliberately last: it is
# the documented front door and the one that was down, and its own backends are
# what answered.
ENDPOINTS = (
    "https://gall.openstreetmap.de/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://overpass-api.de/api/interpreter",
)

# The kinds of place worth calling, as (key, value) pairs — one query each.
# `pub` and `tourism=hotel` are both absent from MASTER_PLAN's list and both
# turned up real places in Neuburg (5 and 9).
TAGS: tuple[tuple[str, str], ...] = (
    ("amenity", "restaurant"),
    ("amenity", "cafe"),
    ("amenity", "fast_food"),
    ("amenity", "bar"),
    ("amenity", "pub"),
    ("tourism", "hotel"),
    ("shop", "bakery"),
    ("shop", "butcher"),
    ("shop", "supermarket"),
)

# Overpass's own per-query budget, in seconds. Generous enough for a 6 km radius
# and small enough that a wedged query fails rather than hangs.
QUERY_TIMEOUT = 40


@dataclass(frozen=True)
class Place:
    """One place she could walk into or ring, as OSM describes it."""

    contact_id: str
    name: str
    kind: str
    city: str
    street: str | None = None
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    lat: float | None = None
    lon: float | None = None
    # The raw tags, kept so the score can read cuisine, opening hours and the
    # rest without a second fetch. Never shown to her.
    tags: dict[str, Any] = field(default_factory=dict, compare=False)

    @property
    def has_direct_route(self) -> bool:
        """True when she can reach them today, without an imprint lookup."""
        return bool(self.phone or self.email)


def _first_tag(tags: dict, *names: str) -> str | None:
    """OSM carries `phone` and `contact:phone` interchangeably — read both."""
    for name in names:
        value = tags.get(name)
        if value and str(value).strip():
            return str(value).strip()
    return None


def _kind(tags: dict) -> str | None:
    for key in ("amenity", "shop", "tourism"):
        value = tags.get(key)
        if value:
            return str(value)
    return None


def _street(tags: dict) -> str | None:
    street = _first_tag(tags, "addr:street")
    if not street:
        return None
    number = _first_tag(tags, "addr:housenumber")
    return f"{street} {number}" if number else street


def parse_places(elements: list[dict], *, city: str) -> list[Place]:
    """Overpass elements → places worth storing, in the order they arrived.

    Two exclusions, both deliberate. A place with **no name** cannot be asked
    for by name on the phone. A place with **no contact route at all** — no
    phone, no email, no website — is a row she has to skip every time she opens
    the page; a website-only place stays, because one imprint fetch can recover
    an address from it (German law requires one).
    """
    places: list[Place] = []
    seen: set[str] = set()
    for element in elements:
        tags = element.get("tags") or {}
        name = _first_tag(tags, "name")
        kind = _kind(tags)
        if not name or not kind:
            continue

        phone = normalize_phone(_first_tag(tags, "phone", "contact:phone"))
        email = _first_tag(tags, "email", "contact:email")
        website = _first_tag(tags, "website", "contact:website")
        if not (phone or email or website):
            continue

        contact_id = f"{element.get('type')}/{element.get('id')}"
        if contact_id in seen:
            continue  # the same place answered two of the tag queries
        seen.add(contact_id)

        centre = element.get("center") or {}
        places.append(
            Place(
                contact_id=contact_id,
                name=name,
                kind=kind,
                city=city,
                street=_street(tags),
                phone=phone,
                email=email,
                website=website,
                lat=element.get("lat", centre.get("lat")),
                lon=element.get("lon", centre.get("lon")),
                tags=dict(tags),
            )
        )
    return places


class OverpassSource:
    """One city's worth of callable places, one small query per kind."""

    def __init__(
        self,
        client,
        *,
        tags: tuple[tuple[str, str], ...] = TAGS,
        endpoints: tuple[str, ...] = ENDPOINTS,
        attempts: int | None = None,
    ):
        self._client = client
        self.tags = tags
        self.endpoints = endpoints
        # One attempt per endpoint by default: the measured failure mode is a
        # dead front door beside live backends, and only a different host fixes
        # that. The client's own retries handle a host that is merely busy.
        self.attempts = attempts if attempts is not None else len(endpoints)
        self.failures: list[str] = []

    def places_near(self, lat: float, lon: float, *, city: str, radius_km: int = 6) -> list[Place]:
        """Every callable place within `radius_km` of a point, de-duplicated.

        A tag that cannot be fetched is recorded in `failures` and skipped: on a
        normal day some tag fails, and a run that gave up there would return an
        empty list for a city full of restaurants.
        """
        found: dict[str, Place] = {}
        for key, value in self.tags:
            elements = self._ask(key, value, lat, lon, radius_km)
            if elements is None:
                continue
            for place in parse_places(elements, city=city):
                found.setdefault(place.contact_id, place)
        return list(found.values())

    def _ask(self, key: str, value: str, lat: float, lon: float, radius_km: int):
        body = self._query(key, value, lat, lon, radius_km)
        last_error: str | None = None
        for attempt in range(self.attempts):
            endpoint = self.endpoints[attempt % len(self.endpoints)]
            try:
                payload = self._client.post_json(endpoint, body=body)
                elements = payload.get("elements")
                if elements is None:
                    raise ValueError("no 'elements' in the answer")
                return elements
            except (SourceUnavailable, ValueError, KeyError, TypeError) as exc:
                last_error = str(exc)
        self.failures.append(f"{key}={value}: {last_error}")
        return None

    @staticmethod
    def _query(key: str, value: str, lat: float, lon: float, radius_km: int) -> str:
        metres = int(radius_km * 1000)
        return (
            f"[out:json][timeout:{QUERY_TIMEOUT}];"
            f'nwr(around:{metres},{lat},{lon})["{key}"="{value}"];'
            "out tags center;"
        )
