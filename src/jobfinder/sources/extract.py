"""Readable text and structured data out of an HTML page.

Three layers, used in this order (§Phase 6): schema.org JSON-LD `JobPosting`
blocks — which job boards emit for SEO and which survive redesigns — then CSS
selectors in the adapter, then `extract_readable_text` as the last resort for
pages with no structure at all. A login wall is detected before any of it, so
a walled page is skipped once instead of parsed into nothing three times.
"""

from __future__ import annotations

import html as html_lib
import json
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jobfinder.sources.base import RawPosting

_SCRIPT_OR_STYLE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_LDJSON_BLOCK = re.compile(
    r"<script[^>]*type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)
_ANY_TAG = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")

# Shorter than this is navigation junk or an empty app shell, not an ad.
MIN_TEXT_CHARS = 80

# What a page asks when the content lives behind an account. German first:
# every board she scrapes is German. Matched case-insensitively on the whole
# page, so the list stays specific — "Anmelden"/"login", not "Konto".
_LOGIN_WALL_MARKERS = (
    "bitte melde dich an",
    "bitte logge dich ein",
    "zum fortfahren anmelden",
    "log in to continue",
    "login to view",
    "please log in",
    "sign in to continue",
)
_LOGIN_FORM = re.compile(r"<form[^>]+action=[\"'][^\"']*login", re.IGNORECASE)


def extract_readable_text(markup: str, *, min_chars: int = MIN_TEXT_CHARS) -> str | None:
    """Tag-stripped, entity-decoded page text — or None when there is no real text."""
    without_code = _SCRIPT_OR_STYLE.sub(" ", markup)
    text = html_lib.unescape(_ANY_TAG.sub(" ", without_code))
    collapsed = _WHITESPACE.sub(" ", text).strip()
    if len(collapsed) < min_chars:
        return None
    return collapsed


def html_to_text(markup: str) -> str:
    """Markup from inside a JSON-LD field to plain text — no length gate.

    A `JobPosting.description` is HTML by schema; storing it raw would push
    tags into her CSV and the enrichment prompt.
    """
    text = html_lib.unescape(_ANY_TAG.sub(" ", _SCRIPT_OR_STYLE.sub(" ", markup)))
    return _WHITESPACE.sub(" ", text).strip()


def looks_like_login_wall(markup: str) -> bool:
    """Is this page asking for an account rather than showing the ad?"""
    lowered = markup.lower()
    if any(marker in lowered for marker in _LOGIN_WALL_MARKERS):
        return True
    return _LOGIN_FORM.search(markup) is not None


def jsonld_jobpostings(markup: str) -> list[dict]:
    """Every schema.org JobPosting on the page, from however many blocks.

    Tolerates the three shapes sites actually emit — one object, an array,
    a `@graph` — and skips a corrupt block rather than failing the page: a
    half-broken page with one good block still yields that job.
    """
    postings: list[dict] = []
    for block in _LDJSON_BLOCK.findall(markup):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        postings.extend(_jobpostings_in(data))
    return postings


def _jobpostings_in(data) -> list[dict]:
    if isinstance(data, list):
        return [posting for item in data for posting in _jobpostings_in(item)]
    if not isinstance(data, dict):
        return []
    graph = data.get("@graph")
    if isinstance(graph, list):
        return [posting for item in graph for posting in _jobpostings_in(item)]
    types = data.get("@type")
    types = [types] if isinstance(types, str) else types or []
    if any(t.lower() == "jobposting" for t in types if isinstance(t, str)):
        return [data]
    return []


# -- schema.org field access ----------------------------------------------------
#
# schema.org allows one object or an array for most references, and the sites
# she scrapes genuinely differ (Xing lists `jobLocation`, others don't), so
# every adapter reads these helpers instead of indexing the JSON directly.


def first_of(value):
    """One object out of a schema.org property: `None` when there is none."""
    if isinstance(value, list):
        return value[0] if value else None
    return value


def jobposting_company(posting: dict) -> str | None:
    organization = first_of(posting.get("hiringOrganization"))
    if not isinstance(organization, dict):
        return None
    return organization.get("name")


def jobposting_city(posting: dict) -> str | None:
    location = first_of(posting.get("jobLocation"))
    if not isinstance(location, dict):
        return None
    address = first_of(location.get("address"))
    if not isinstance(address, dict):
        return None
    return address.get("addressLocality")


def jobposting_to_posting(
    data: dict,
    *,
    source: str,
    job_id: str,
    source_id: str,
    source_url: str,
) -> RawPosting | None:
    """One schema.org JobPosting into a RawPosting — the path every board shares.

    Xing, StepStone and Indeed all emit `JobPosting` for SEO; one mapping here
    means a field they add (or rename) is fixed once. Returns None when the
    block has no title, the one field a posting cannot lack.
    """
    from jobfinder.sources.base import RawPosting
    from jobfinder.sources.wording import employment_type_signals

    title = (data.get("title") or "").strip()
    if not title:
        return None
    description = html_to_text(data.get("description") or "") or None
    posted = str(data.get("datePosted") or "")
    signals = employment_type_signals(title, description or "")
    return RawPosting(
        job_id=job_id,
        source=source,
        source_id=source_id,
        title=title,
        company=jobposting_company(data),
        city=jobposting_city(data),
        published_at=posted[:10] or None,
        apply_url=data.get("url") or source_url,
        source_url=source_url,
        description=description,
        is_minijob="minijob" in signals,
        is_parttime="parttime" in signals,
        is_fulltime="fulltime" in signals,
        is_internship="internship" in signals,
        is_werkstudent="werkstudent" in signals,
    )
