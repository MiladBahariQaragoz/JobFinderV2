"""Which places to call first — the order she will actually work through.

One town returned 118 places. Nobody rings 118 places, so the order this
computes is the product: the jobs done away from customers come first, because
those are the ones where limited German means following instructions rather than
holding conversations.

Three properties on purpose:

- **Free.** It decides row order and is recomputed on every run; a model call
  here would spend her quota on something arithmetic can do.
- **Predictable.** She can look at a bakery above a bar and see why. A number
  she cannot argue with is a number she will not trust.
- **Bounded 0–100**, like the job `fit_score`, so the two columns read the same
  way even though they measure different things.
"""

from __future__ import annotations

from jobfinder.sources.overpass import Place

# How much back-of-house work the kind of place tends to have, 0–100 before any
# nudges. Ordered by "could she do this on her first week with A2 German":
# a bakery's back room and a hotel's kitchen and housekeeping are the best of
# it; a bar or a pub is almost entirely talking to customers.
KIND_SCORE: dict[str, int] = {
    "bakery": 85,
    "hotel": 80,
    "butcher": 70,
    "restaurant": 65,
    "supermarket": 60,
    "cafe": 45,
    "fast_food": 40,
    "bar": 20,
    "pub": 20,
}

# A kind OSM has and this file has not thought about. Low, so it sits at the
# bottom of the list rather than falling off it.
UNKNOWN_KIND_SCORE = 15

# Reaching them by email instead of by phone removes the hardest part of a cold
# contact for someone at A2 — worth a real nudge, not a token one.
EMAIL_BONUS = 8

# A kitchen where her own language is spoken is a genuine advantage, and never
# enough to lift a bar above a bakery: the kind of work is the question.
LANGUAGE_BONUS = 6

# Cuisine tag values that imply a language, lower-cased. OSM writes several in
# one field, separated by semicolons.
CUISINE_LANGUAGES = {
    "persian": "persian",
    "iranian": "persian",
    "afghan": "persian",
    "german": "german",
    "bavarian": "german",
    "american": "english",
    "english": "english",
    "british": "english",
    "irish": "english",
}

_MAX = 100


def _cuisine_values(place: Place) -> list[str]:
    raw = str(place.tags.get("cuisine") or "")
    return [value.strip().lower() for value in raw.split(";") if value.strip()]


def _language_match(place: Place, languages: tuple[str, ...]) -> str | None:
    """A cuisine tag naming a language she speaks, or None."""
    spoken = {language.strip().lower() for language in languages}
    for value in _cuisine_values(place):
        language = CUISINE_LANGUAGES.get(value)
        if language and language in spoken:
            return language
    return None


def back_of_house_score(place: Place, *, languages: tuple[str, ...] = ()) -> int:
    """0–100: how well this place suits work away from the customers."""
    score = KIND_SCORE.get(place.kind, UNKNOWN_KIND_SCORE)
    if place.email:
        score += EMAIL_BONUS
    if languages and _language_match(place, languages):
        score += LANGUAGE_BONUS
    return max(0, min(_MAX, score))


def score_reason(place: Place, *, languages: tuple[str, ...] = ()) -> str:
    """Why this place is where it is in the list, in one English sentence."""
    known = place.kind in KIND_SCORE
    base = KIND_SCORE.get(place.kind, UNKNOWN_KIND_SCORE)
    if not known:
        parts = [f"A {place.kind.replace('_', ' ')} — not a kind we know much about"]
    elif base >= 70:
        parts = [f"A {place.kind.replace('_', ' ')}: mostly back-of-house work"]
    elif base >= 45:
        parts = [f"A {place.kind.replace('_', ' ')}: some kitchen work, some customer contact"]
    else:
        parts = [f"A {place.kind.replace('_', ' ')}: mostly serving customers"]

    if place.email:
        parts.append("you can write instead of phoning")
    language = _language_match(place, languages) if languages else None
    if language:
        parts.append(f"their kitchen may speak {language.title()}")
    return ", ".join(parts) + "."
