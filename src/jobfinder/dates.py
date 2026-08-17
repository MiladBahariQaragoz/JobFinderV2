"""One comparable date, out of whatever shape a source reported.

Her store holds `published_at` in three shapes at once — a plain date from the
Bundesagentur, Kleinanzeigen and Xing, a `Z` timestamp from Adzuna, and an
offset timestamp from Arbeitnow. Comparing those as strings is wrong even away
from the boundary (`'2026-08-16' < '2026-08-16T02:09:29Z'`), so a "posted within
a week" filter needs one derived value with one shape.

The derivation lives here, alone, and is reached in two places: `RawPosting`,
so every adapter gets it without remembering, and the schema v7 backfill, so
the rows already stored agree with the ones arriving. Two implementations of
this rule would be two answers to "what day was this posted".
"""

from __future__ import annotations

from datetime import UTC, datetime

# A source reporting a year outside this window has a bug, and a bad year is
# worse than a missing one: it parks an ad at one end of "newest first" forever.
_EARLIEST_SANE_YEAR = 1990
_LATEST_SANE_YEAR = 2100


def published_on(raw: str | None) -> str | None:
    """`YYYY-MM-DD` for a posting date, or None when there is nothing usable.

    A timestamp carrying a zone is converted to UTC before its date is taken —
    half an hour after midnight in Berlin is still the previous day in UTC, and
    a filter has to agree with itself about which day it means.
    """
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None

    # `fromisoformat` in 3.11+ takes the whole ISO family, including a trailing
    # Z and a space in place of the T — every shape her store actually holds.
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return _plain_date(text)

    if moment.tzinfo is not None:
        moment = moment.astimezone(UTC)
    if not _EARLIEST_SANE_YEAR <= moment.year <= _LATEST_SANE_YEAR:
        return None
    return moment.date().isoformat()


def _plain_date(text: str) -> str | None:
    """The last resort: a bare `YYYY-MM-DD` that ISO parsing choked on."""
    try:
        parsed = datetime.strptime(text[:10], "%Y-%m-%d")
    except ValueError:
        return None
    if not _EARLIEST_SANE_YEAR <= parsed.year <= _LATEST_SANE_YEAR:
        return None
    return parsed.date().isoformat()
