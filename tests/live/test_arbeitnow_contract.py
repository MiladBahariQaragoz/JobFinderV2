"""The Arbeitnow contract, probed live — shape only, never counts.

These tests ask the service to keep its promises: the endpoint answers, page 1
still carries `slug`/`title`/`location`/`job_types`/`created_at` on its
entries, `links.next` still signals pagination, and the adapter still parses a
real page into `AN:` postings. How many jobs there are is not a promise.
Run with `pytest -m live`.
"""

from __future__ import annotations

import pytest

from jobfinder.sources.arbeitnow import BASE_URL, parse_page
from jobfinder.sources.http import PoliteClient


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    """One polite client for the whole module — the API asks to not be abused."""
    cache_dir = tmp_path_factory.mktemp("arbeitnow-live-cache")
    return PoliteClient(cache_dir=cache_dir, budget=3)


@pytest.mark.live
def test_job_board_answers_with_the_expected_entry_shape(client):
    payload = client.get_json(BASE_URL, params={"page": 1})
    entries = payload.get("data") or []
    assert entries, "no entries at all — the shape cannot be checked"
    first = entries[0]
    assert first.get("slug"), "slug missing from entries"
    assert first.get("title"), "title missing from entries"
    assert "location" in first, "location missing from entries"
    assert "job_types" in first, "job_types missing from entries"
    assert "created_at" in first, "created_at missing from entries"


@pytest.mark.live
def test_links_next_still_signals_pagination(client):
    payload = client.get_json(BASE_URL, params={"page": 1})
    links = payload.get("links") or {}
    assert links.get("next"), "links.next missing on page 1 — the walk would stop after one page"


@pytest.mark.live
def test_the_adapter_parses_a_live_page(client):
    payload = client.get_json(BASE_URL, params={"page": 1})
    postings = parse_page(payload)
    assert postings, "page had entries but none parsed — the adapter drifted from the service"
    assert postings[0].job_id.startswith("AN:")
