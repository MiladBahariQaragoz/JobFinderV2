"""The BA contract, probed live — shape only, never counts.

These tests ask the service to keep its promises: v6 answers 200, entries
still carry `referenznummer` and `stellenangebotsTitel`, `size=50` is
accepted, and the details endpoint still returns the description. Whether
there are 200 or 20 000 jobs is not a promise — counts are never asserted.
Run with `pytest -m live`.
"""

from __future__ import annotations

import pytest

from jobfinder.sources.ba import API_HEADERS, SEARCH_URL, detail_url, parse_page
from jobfinder.sources.http import PoliteClient

WO = "Ingolstadt"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    """One polite client for the whole module — the live service is not ours to hammer."""
    cache_dir = tmp_path_factory.mktemp("ba-live-cache")
    return PoliteClient(cache_dir=cache_dir, budget=6)


@pytest.mark.live
def test_v6_search_answers_200_with_the_expected_entry_shape(client):
    payload = client.get_json(
        SEARCH_URL,
        params={"wo": WO, "umkreis": 25, "angebotsart": 1, "page": 1, "size": 50},
        headers=API_HEADERS,
    )
    entries = payload.get("ergebnisliste") or []
    assert entries, "no entries at all — the shape cannot be checked"
    first = entries[0]
    assert first.get("referenznummer"), "referenznummer missing from entries"
    assert first.get("stellenangebotsTitel"), "stellenangebotsTitel missing from entries"
    # If this parse ever breaks, the adapter is parsing a changed service.
    postings = parse_page(payload)
    assert postings and postings[0].job_id.startswith("BA:")


@pytest.mark.live
def test_size_50_is_accepted_otherwise_the_adapter_must_drop_to_20(client):
    payload = client.get_json(
        SEARCH_URL,
        params={"wo": WO, "umkreis": 25, "angebotsart": 1, "page": 1, "size": 50},
        headers=API_HEADERS,
    )
    entries = payload.get("ergebnisliste") or []
    total = int(payload.get("maxErgebnisse", 0))
    if total >= 50:
        assert len(entries) == 50, "size=50 silently ignored — PAGE_SIZE must fall back to 20"


@pytest.mark.live
def test_details_endpoint_answers_200_with_a_description(client):
    search = client.get_json(
        SEARCH_URL,
        params={"wo": WO, "umkreis": 25, "angebotsart": 1, "page": 1, "size": 20},
        headers=API_HEADERS,
    )
    reference = search["ergebnisliste"][0]["referenznummer"]
    details = client.get_json(detail_url(reference), headers=API_HEADERS)
    assert "stellenangebotsBeschreibung" in details, (
        "details endpoint changed shape — the description fill and the external-URL "
        "fallback both depend on it"
    )
