"""Adzuna jobs API — optional, enabled only when she has registered a key.

No `ADZUNA_APP_ID`/`ADZUNA_APP_KEY` existed as of 2026-08-16, so nothing here
is verified live: this module carries the skip logic and the query builder,
and its parsing code waits for a key (MASTER_PLAN §6: absent keys mean
skipped, never an error). Parameter values are Adzuna's documented ones,
recorded for live verification the day a key is registered — the query
builder's tests pin them so drift is caught then, not guessed at now.
"""

from __future__ import annotations

import os
import urllib.parse
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jobfinder.search_spec import SearchSpec

BASE_URL = "https://api.adzuna.com/v1/api/jobs/de/search"

PAGE_SIZE = 50  # Adzuna's documented maximum

# Her types that map onto an Adzuna boolean flag. One flag per query — the
# flags AND together server-side, and her types are alternatives (Phase 4
# audit). Types without a flag travel as `what` search terms.
FLAG_FOR_TYPE = {
    "parttime": "part_time",
    "fulltime": "full_time",
}
KEYWORD_FOR_TYPE = {
    "werkstudent": "Werkstudent",
    "internship": "Praktikum",
}


class AdzunaNotConfigured(Exception):
    """No API key in the environment — Adzuna is off, which is normal."""


@dataclass(frozen=True)
class AdzunaQuery:
    """One page request to the search endpoint."""

    page: int
    app_id: str
    app_key: str
    what: str | None = None
    where: str | None = None
    distance: int | None = None
    part_time: int = 0
    full_time: int = 0
    size: int = PAGE_SIZE

    def params(self) -> dict:
        params: dict = {"app_id": self.app_id, "app_key": self.app_key}
        if self.size:
            params["results_per_page"] = self.size
        for name, value in (
            ("what", self.what),
            ("where", self.where),
            ("distance", self.distance),
        ):
            if value is not None:
                params[name] = value
        for flag in ("part_time", "full_time"):
            if getattr(self, flag):
                params[flag] = 1
        return params

    def url(self) -> str:
        return f"{BASE_URL}/{self.page}?{urllib.parse.urlencode(self.params())}"


def build_queries(spec: SearchSpec, *, app_id: str, app_key: str) -> list[AdzunaQuery]:
    """One query per keyword per city per employment type — alternatives, never stacked."""
    bases = [keyword.strip() for keyword in spec.keywords if keyword.strip()] or [""]
    queries: list[AdzunaQuery] = []
    for base in bases:
        for city in spec.cities:
            for employment_type in spec.employment_types or [""]:
                flag = FLAG_FOR_TYPE.get(employment_type)
                term = KEYWORD_FOR_TYPE.get(employment_type)
                what = " ".join(part for part in (base, term) if part) or None
                queries.append(
                    AdzunaQuery(
                        page=1,
                        app_id=app_id,
                        app_key=app_key,
                        what=what,
                        where=city.name,
                        distance=city.radius_km,
                        **({flag: 1} if flag else {}),
                    )
                )
    return queries


class AdzunaApi:
    """SourceAdapter over the Adzuna search endpoint. Source code: `AZ`."""

    source = "AZ"

    def __init__(self, client):
        self._client = client

    def _credentials(self) -> tuple[str, str]:
        app_id = os.environ.get("ADZUNA_APP_ID")
        app_key = os.environ.get("ADZUNA_APP_KEY")
        if not app_id or not app_key:
            raise AdzunaNotConfigured(
                "Adzuna has no API key — add ADZUNA_APP_ID and ADZUNA_APP_KEY to .env, "
                "or remove adzuna from enabled_sources."
            )
        return app_id, app_key

    def search_pages(self, spec: SearchSpec, *, start_query_index: int = 0, start_page: int = 1):
        """Yield pages — parsing lands with the first recorded fixture (needs a key)."""
        self._credentials()  # fail readably before the first request, not during
        raise NotImplementedError(
            "Adzuna parsing waits for a recorded fixture — register a key first."
        )

    def search(self, spec: SearchSpec):
        yield from self.search_pages(spec)
