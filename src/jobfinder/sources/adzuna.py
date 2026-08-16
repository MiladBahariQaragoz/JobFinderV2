"""Adzuna jobs API — optional, enabled only when she has registered a key.

No `ADZUNA_APP_ID`/`ADZUNA_APP_KEY` existed as of 2026-08-16, so nothing here
is verified live: this module carries the skip logic and the query builder,
and its parsing code waits for a key (MASTER_PLAN §6: absent keys mean
skipped, never an error). The registry checks the keys before constructing
the adapter at all.
"""

from __future__ import annotations

BASE_URL = "https://api.adzuna.com/v1/api/jobs/de/search"


class AdzunaApi:
    """SourceAdapter over the Adzuna search endpoint. Source code: `AZ`."""

    source = "AZ"

    def __init__(self, client):
        self._client = client
