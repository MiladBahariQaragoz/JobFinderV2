"""German phone numbers, in one shape she can tap.

OSM stores whatever the surveyor typed. Measured on the real Neuburg answer:
`'+49 8431 2078'` and `'+4984312079'` sit side by side, and elsewhere the same
field holds two numbers, a note in brackets, or a national `08431/…`. She is
going to be holding a phone while reading this list, so one shape wins: E.164,
no spaces, no punctuation.

Nothing is guessed. A field that does not contain a recognisable number is
dropped rather than half-cleaned into something that dials the wrong place.
"""

from __future__ import annotations

import re

GERMANY = "+49"

# The first number in the field. OSM separates alternates with ';' or ',' and
# often appends a note — "+49 8431 2078 (Küche)" — so the split comes first.
_SEPARATORS = re.compile(r"[;,]|\bor\b|\boder\b")
_KEEP = re.compile(r"[^\d+]")
# A German number is 10-13 digits once the country code is in place. Shorter is
# an extension or a typo; longer is two numbers that were never separated.
_MIN_DIGITS = 9
_MAX_DIGITS = 14


def normalize_phone(raw: str | None, *, country: str = GERMANY) -> str | None:
    """One phone number in E.164, or None when there is nothing dialable."""
    if not raw:
        return None
    first = _SEPARATORS.split(str(raw))[0]
    # Drop a trailing parenthetical note before stripping punctuation, or its
    # digits ("Küche 2") would be pulled into the number.
    first = re.sub(r"\(.*?\)", " ", first)
    cleaned = _KEEP.sub("", first)
    if not cleaned:
        return None

    if cleaned.startswith("+"):
        digits = cleaned[1:]
        if not digits.isdigit():
            return None
        return _bounded(f"+{digits}")
    if cleaned.startswith("00"):
        return _bounded(f"+{cleaned[2:]}")
    if cleaned.startswith("0"):
        # A national number: 08431/2078 is this country's 8431 2078.
        return _bounded(f"{country}{cleaned[1:]}")
    if cleaned.isdigit():
        # No leading zero and no country code: too ambiguous to dial. An area
        # code cannot be recovered from a number that never carried one.
        return None
    return None


def _bounded(candidate: str) -> str | None:
    digits = candidate.lstrip("+")
    if not digits.isdigit():
        return None
    if not _MIN_DIGITS <= len(digits) <= _MAX_DIGITS:
        return None
    return candidate
