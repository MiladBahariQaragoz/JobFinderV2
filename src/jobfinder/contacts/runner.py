"""Building the call-list: one run over several cities, saved as it goes.

Two project rules do most of the work here.

**§9 — nothing lives only in memory.** Every place is committed the moment it is
parsed, and the CSV is rewritten after each city. A run killed halfway leaves a
shorter list, never no list, and the next run continues rather than restarting.

**§10 — nothing ever looks frozen.** The run journals its counts city by city, so
the browser reads progress out of the database rather than out of this process.

Everything that can fail here fails narrowly: a city Overpass will not answer, a
website that never loads, a place whose tags make no sense. Each costs itself and
nothing else — a call-list missing one town is still a call-list.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from jobfinder.cities import resolve_city
from jobfinder.contacts.score import back_of_house_score, score_reason
from jobfinder.store.contacts import contact_counts, upsert_contact
from jobfinder.store.contacts_export import export_contacts
from jobfinder.store.db import connect, migrate

if TYPE_CHECKING:
    import threading

    from jobfinder.config import Settings

# The radius each city is searched with. Six kilometres covers a Bavarian town
# and its edges; measured, it returned 118 places for Neuburg.
DEFAULT_RADIUS_KM = 6


@dataclass
class ContactsRun:
    """What one pass over the cities did, in the words the summary uses."""

    found: int = 0
    new: int = 0
    reachable: int = 0
    emails_recovered: int = 0
    per_city: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    interrupted: bool = False


def run_contacts(
    settings: Settings,
    source,
    *,
    cities: tuple[str, ...],
    radius_km: int = DEFAULT_RADIUS_KM,
    languages: tuple[str, ...] = (),
    imprint_lookup=None,
    stop_event: threading.Event | None = None,
    on_city=None,
) -> ContactsRun:
    """Find, score and store the callable places in each city.

    `imprint_lookup` is optional and off by default: it fetches one page per
    website-only place, which is a request to someone's server, so it happens
    because she asked for it rather than as a side effect.
    """
    result = ContactsRun()
    connection = connect(settings.db_path)
    try:
        migrate(connection)
        run_id = _start_run(connection, cities)
        for name in cities:
            if stop_event is not None and stop_event.is_set():
                result.interrupted = True
                break
            result.per_city[name] = 0
            try:
                city = resolve_city(name)
            except Exception as exc:  # an unknown city is a typo, not a crash
                result.errors.append(f"{name}: {exc}")
                continue

            try:
                places = source.places_near(city.lat, city.lon, city=city.name, radius_km=radius_km)
            except Exception as exc:
                result.errors.append(f"{name}: {exc}")
                continue

            for place in places:
                place = _with_recovered_email(place, imprint_lookup, result)
                score = back_of_house_score(place, languages=languages)
                outcome = upsert_contact(
                    connection,
                    place,
                    score=score,
                    reason=score_reason(place, languages=languages),
                )
                result.found += 1
                result.per_city[name] += 1
                if outcome == "new":
                    result.new += 1
            result.errors.extend(getattr(source, "failures", []) or [])
            _note_progress(connection, run_id, result.found)
            export_contacts(connection, settings.contacts_csv)
            if on_city is not None:
                on_city(name, result)

        result.reachable = contact_counts(connection)["reachable"]
        _finish_run(connection, run_id, result)
    finally:
        connection.close()
    return result


def _with_recovered_email(place, imprint_lookup, result: ContactsRun):
    """One imprint fetch for a place we cannot otherwise reach."""
    if imprint_lookup is None or place.has_direct_route or not place.website:
        return place
    try:
        found = imprint_lookup(place)
    except Exception:
        return place  # a site that is a maze costs this place, nothing more
    if not found:
        return place
    result.emails_recovered += 1
    from dataclasses import replace

    return replace(place, email=found)


# -- the journal (§10) ---------------------------------------------------------


def _start_run(connection, cities: tuple[str, ...]) -> int:
    cursor = connection.execute(
        "INSERT INTO runs (kind, spec, state, started_at, last_progress_at)"
        " VALUES ('contacts', ?, 'running', datetime('now'), datetime('now'))",
        (", ".join(cities),),
    )
    connection.commit()
    return int(cursor.lastrowid)


def _note_progress(connection, run_id: int, found: int) -> None:
    connection.execute(
        "UPDATE runs SET contacts_count = ?, last_progress_at = datetime('now') WHERE id = ?",
        (found, run_id),
    )
    connection.commit()


def _finish_run(connection, run_id: int, result: ContactsRun) -> None:
    connection.execute(
        "UPDATE runs SET state = ?, finished_at = datetime('now'), contacts_count = ?, errors = ?"
        " WHERE id = ?",
        (
            "interrupted" if result.interrupted else "done",
            result.found,
            json.dumps(result.errors, ensure_ascii=False),
            run_id,
        ),
    )
    connection.commit()
