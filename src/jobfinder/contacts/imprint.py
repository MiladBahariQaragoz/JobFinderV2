"""One fetch per website, to turn "cannot reach them" into "can write to them".

Ten of Neuburg's places carry a website and no phone or email. German law (§5
TMG) requires a business site to publish contact details on an *Impressum* page,
so this is the one place in the app where fetching a page nobody linked to is
both legal and likely to work.

Etiquette (§8) sets the limits: a small fixed list of paths, tried once per site,
and a site that does not answer costs that place and nothing else. There is no
crawling — one page, then stop.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from jobfinder.sources.http import RequestBudgetExhausted, SourceUnavailable

# Where German businesses put it, most common first. Kept short on purpose: each
# entry is a request to someone's server for a page that may not be there.
IMPRINT_PATHS = ("/impressum", "/kontakt", "/impressum.html", "/contact")

# A plain address. The trailing character class excludes a dot so "info@x.de."
# at the end of a sentence does not keep the full stop.
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", re.UNICODE)

# `info (at) example (dot) de`, `info [at] example.de` — the spam dodges that
# are still readable to a person, and therefore still worth reading.
_OBFUSCATED_AT = re.compile(r"\s*[\[(]\s*(?:at|ät)\s*[\])]\s*", re.IGNORECASE)
_OBFUSCATED_DOT = re.compile(r"\s*[\[(]\s*(?:dot|punkt)\s*[\])]\s*", re.IGNORECASE)

# Addresses that belong to whoever built the site, not to the business. Imprint
# pages routinely end with "Umsetzung: agentur@…", and using that would have her
# write to a web designer about a job in a bakery.
_NOT_THE_BUSINESS = ("webdesign", "webagentur", "agentur", "hosting", "noreply", "no-reply")

# Extensions that turn up in `src="logo@2x.png"` and are never addresses.
_FILE_ENDINGS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js")


def find_email(html: str) -> str | None:
    """The business's own email address in a page, or None.

    A `mailto:` link is trusted first — it is the one place on a page where an
    address is unambiguously an address.
    """
    if not html:
        return None

    for candidate in re.findall(r'mailto:([^"\'>?\s]+)', html, flags=re.IGNORECASE):
        if _plausible(candidate):
            return candidate.lower() if candidate.isascii() else candidate

    text = _OBFUSCATED_DOT.sub(".", _OBFUSCATED_AT.sub("@", html))
    for match in _EMAIL.finditer(text):
        candidate = match.group(0).rstrip(".")
        if _plausible(candidate):
            return candidate.lower() if candidate.isascii() else candidate
    return None


def _plausible(candidate: str) -> bool:
    lowered = candidate.lower()
    if any(lowered.endswith(ending) for ending in _FILE_ENDINGS):
        return False
    if any(word in lowered for word in _NOT_THE_BUSINESS):
        return False
    return "@" in candidate and "." in candidate.split("@")[-1]


def imprint_email(client, place) -> str | None:
    """Fetch a place's imprint page once and return the email it publishes.

    Returns None — never raises — when there is nothing to fetch, nothing to
    find, or the site does not answer: one unreachable website must cost one
    place, not the run.
    """
    if place.email or not place.website or not str(place.website).strip():
        return None

    root = _root(str(place.website))
    if root is None:
        return None

    for path in IMPRINT_PATHS:
        try:
            response = client.get(f"{root}{path}")
        except SourceUnavailable:
            continue
        except RequestBudgetExhausted:
            raise  # the run's own limit: that is not this place's problem
        except Exception:
            continue  # a broken site is one missing place, not a failed run
        if getattr(response, "status", 200) != 200:
            continue
        found = find_email(_decode(response))
        if found:
            return found
        # The page answered and published no address: one page per site (§8).
        return None
    return None


def _root(website: str) -> str | None:
    """`https://host` from whatever OSM's `website` tag happens to hold."""
    candidate = website.strip()
    if not candidate:
        return None
    if "//" not in candidate:
        candidate = f"https://{candidate}"
    parts = urlsplit(candidate)
    if not parts.netloc:
        return None
    return f"{parts.scheme or 'https'}://{parts.netloc}"


def _decode(response) -> str:
    body = getattr(response, "body", b"") or b""
    if isinstance(body, str):
        return body
    return body.decode("utf-8", errors="replace")
