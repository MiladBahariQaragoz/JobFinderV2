"""Arbeitnow job-board API — free, keyless, Germany-wide.

Facts verified live 2026-08-16 (see the Phase 5 plan): one endpoint,
`?page=N` pagination of 175-entry pages, no server-side filter for city, type
or keyword — everything is filtered client-side on one walk over the pages,
newest postings first. The full adapter lands with its fixture-backed tests;
this module exists so the registry can construct it.
"""

from __future__ import annotations

BASE_URL = "https://www.arbeitnow.com/api/job-board-api"

# `links.last` is null and there is no total, so a full walk is unbounded.
# The cap rides on top of the request budget (§8: request count is the scarce
# resource) and covers the newest ~1 750 postings.
MAX_PAGES = 10


class ArbeitnowApi:
    """SourceAdapter over the job-board API. Source code: `AN`."""

    source = "AN"

    def __init__(self, client):
        self._client = client
