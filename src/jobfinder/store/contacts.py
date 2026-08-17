"""The call-list: places to ring, and what happened when she did.

Two rules shape every statement here, and both come from the fact that she will
build this list more than once:

- **`osm_id` is the identity.** `contact_id` is a surrogate integer the table
  was born with; the stable name of a place is its OSM type and id. A re-run
  that inserted a second row per place would turn a list she had worked through
  into one she could not trust.
- **A re-run never overwrites her.** `outcome`, `notes` and `last_contacted_at`
  belong to her. The source can update a phone number; it cannot forget that she
  already rang.

`last_contacted_at` follows `applied_on` on the jobs side: stamped the first
time she records reaching them, never rewritten — marking a place "no" a week
later must not move the day she actually called.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

# What can have happened. `no` is an answer, not a failure: it takes a place out
# of the queue for good, which is the whole reason to record it.
VALID_OUTCOMES = ("called", "emailed", "visited", "no")


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


def upsert_contact(
    connection: sqlite3.Connection,
    place,
    *,
    score: float,
    reason: str,
    now: str | None = None,
) -> str:
    """Store or refresh one place; returns 'new' or 'updated'.

    A tag the source has lost since last time does not erase what we hold:
    `COALESCE` keeps the old value when the new one is NULL. OSM data does go
    backwards — a surveyor deletes a phone number — and losing the number she
    was about to ring is worse than holding one that is a month stale.
    """
    existing = contact_by_osm_id(connection, place.contact_id)
    connection.execute(
        """
        INSERT INTO contacts (
            osm_id, name, kind, city, street, phone, email, website,
            back_of_house_score, score_reason, lat, lon, first_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(osm_id) DO UPDATE SET
            name = excluded.name,
            kind = excluded.kind,
            city = excluded.city,
            street = COALESCE(excluded.street, contacts.street),
            phone = COALESCE(excluded.phone, contacts.phone),
            email = COALESCE(excluded.email, contacts.email),
            website = COALESCE(excluded.website, contacts.website),
            back_of_house_score = excluded.back_of_house_score,
            score_reason = excluded.score_reason,
            lat = COALESCE(excluded.lat, contacts.lat),
            lon = COALESCE(excluded.lon, contacts.lon)
        """,
        (
            place.contact_id,
            place.name,
            place.kind,
            place.city,
            place.street,
            place.phone,
            place.email,
            place.website,
            score,
            reason,
            place.lat,
            place.lon,
            now or _utc_now(),
        ),
    )
    connection.commit()  # §9: a kill the next instant keeps this place
    return "updated" if existing is not None else "new"


def contact_by_osm_id(connection: sqlite3.Connection, osm_id: str) -> sqlite3.Row | None:
    return connection.execute("SELECT * FROM contacts WHERE osm_id = ?", (osm_id,)).fetchone()


def _require_known_contact(connection: sqlite3.Connection, osm_id: str) -> None:
    if contact_by_osm_id(connection, osm_id) is None:
        raise ValueError(f"Unknown place '{osm_id}' — it is not in the call-list.")


def set_contact_outcome(
    connection: sqlite3.Connection, osm_id: str, outcome: str, *, now: str | None = None
) -> None:
    """Record what happened, stamping the day of first contact once."""
    if outcome not in VALID_OUTCOMES:
        raise ValueError(
            f"'{outcome}' is not an outcome. Valid outcomes are: {', '.join(VALID_OUTCOMES)}."
        )
    _require_known_contact(connection, osm_id)

    existing = contact_by_osm_id(connection, osm_id)
    last_contacted = existing["last_contacted_at"]
    if outcome != "no" and not last_contacted:
        last_contacted = now or _utc_now()

    connection.execute(
        "UPDATE contacts SET outcome = ?, last_contacted_at = ? WHERE osm_id = ?",
        (outcome, last_contacted, osm_id),
    )
    connection.commit()


def set_contact_notes(connection: sqlite3.Connection, osm_id: str, notes: str) -> None:
    """Save what they said. An empty string clears it."""
    _require_known_contact(connection, osm_id)
    connection.execute("UPDATE contacts SET notes = ? WHERE osm_id = ?", (notes, osm_id))
    connection.commit()


def save_contact_texts(
    connection: sqlite3.Connection, osm_id: str, *, script: str, email_draft: str
) -> None:
    """Store the German phone script and email draft for one place."""
    _require_known_contact(connection, osm_id)
    connection.execute(
        "UPDATE contacts SET script = ?, email_draft = ? WHERE osm_id = ?",
        (script, email_draft, osm_id),
    )
    connection.commit()


def list_contacts(
    connection: sqlite3.Connection,
    *,
    cities: tuple[str, ...] = (),
    pending_only: bool = False,
    reachable_only: bool = False,
) -> list[sqlite3.Row]:
    """The call-list, best first — the order she will work through it.

    `pending_only` hides the places she has already answered for;
    `reachable_only` hides the ones with nothing but a website, which she cannot
    act on until the imprint step has found an address.
    """
    where: list[str] = []
    parameters: list[object] = []
    if cities:
        where.append(f"city IN ({', '.join('?' for _ in cities)})")
        parameters.extend(cities)
    if pending_only:
        where.append("outcome IS NULL")
    if reachable_only:
        where.append("(phone IS NOT NULL OR email IS NOT NULL)")
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    return connection.execute(
        f"SELECT * FROM contacts {clause} ORDER BY back_of_house_score DESC, name COLLATE NOCASE",
        parameters,
    ).fetchall()


def contact_counts(connection: sqlite3.Connection) -> dict[str, int]:
    """What the page and the run summary say about the list.

    `pending` counts only places she can *actually* try — one with no phone and
    no email is not something left to do, it is something waiting on an imprint
    lookup. Counting those together produced "255 places you can reach · 357
    still to try" on her real list, which cannot both be true.
    """
    row = connection.execute(
        "SELECT COUNT(*) AS total,"
        " SUM(CASE WHEN phone IS NOT NULL OR email IS NOT NULL THEN 1 ELSE 0 END) AS reachable,"
        " SUM(CASE WHEN outcome IS NULL AND (phone IS NOT NULL OR email IS NOT NULL)"
        "     THEN 1 ELSE 0 END) AS pending"
        " FROM contacts"
    ).fetchone()
    return {
        "total": int(row["total"] or 0),
        "reachable": int(row["reachable"] or 0),
        "pending": int(row["pending"] or 0),
    }
