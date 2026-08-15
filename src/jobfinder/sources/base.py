"""The one interface every source implements and the store consumes.

Nothing downstream of this file is allowed to know whether a job came from a
government API or a scraped page — that is the rule that keeps sources cheap
to add and cheap to drop.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from jobfinder.search_spec import SearchSpec

# Gender markers German job ads carry: (m/w/d), (m/f/d), (w/m), (M/W/D)…
_GENDER_MARKER = re.compile(r"\(\s*[mwdf](?:\s*/\s*[mwdf])*\s*\)", re.IGNORECASE)
_WHITESPACE = re.compile(r"\s+")
# One site writes "Verkäufer", the next "Verkaeufer" — hash the romanisation.
_UMLAUTS = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}


def normalize_for_dedupe(text: str | None) -> str:
    """Fold a title or company name so the same job matches across sources."""
    if not text:
        return ""
    without_markers = _GENDER_MARKER.sub("", text)
    for umlaut, spelled in _UMLAUTS.items():
        without_markers = without_markers.replace(umlaut, spelled)
    return _WHITESPACE.sub(" ", without_markers).strip().casefold()


def make_dedupe_key(*, title: str | None, company: str | None, plz: str | None) -> str:
    """sha1 over the normalised identity — catches one ad listed on three sites."""
    parts = "|".join(normalize_for_dedupe(part) for part in (title, company, (plz or "").strip()))
    return hashlib.sha1(parts.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RawPosting:
    """One job as a source reported it — raw facts, never LLM output."""

    job_id: str
    source: str
    source_id: str
    title: str
    company: str | None = None
    city: str | None = None
    plz: str | None = None
    lat: float | None = None
    lon: float | None = None
    employment_type_raw: str | None = None
    is_minijob: bool = False
    is_parttime: bool = False
    is_fulltime: bool = False
    is_internship: bool = False
    is_werkstudent: bool = False
    homeoffice: bool = False
    published_at: str | None = None
    apply_url: str | None = None
    source_url: str | None = None
    description: str | None = None

    @property
    def has_description(self) -> bool:
        return bool(self.description and self.description.strip())

    @property
    def content_hash(self) -> str | None:
        """sha1 of the ad text — changes only when the ad changes."""
        if not self.has_description:
            return None
        return hashlib.sha1(self.description.encode("utf-8")).hexdigest()


class SourceAdapter(Protocol):
    """What every source — API or scraper — must provide."""

    source: str

    def search(self, spec: SearchSpec) -> Iterable[RawPosting]:
        """Yield postings for the spec, page by page as they are fetched."""
        ...

    def fetch_detail(self, posting: RawPosting) -> RawPosting:
        """Return the posting with its full description where the source offers one."""
        ...
