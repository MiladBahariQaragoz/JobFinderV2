"""Every mapped Kleinanzeigen location id still points at its own city.

The ids were recorded by hand from the site's location picker, and a wrong
one fails silently in the worst way: the search works, returns ads, and they
are 200 km away. MASTER_PLAN §6 calls that out by name — "a wrong id silently
returns jobs in the wrong part of Germany, which is worse than an error".

Slow by design: one request per city at the scraped-site pace. `pytest -m live`.
"""

from __future__ import annotations

import pytest

from jobfinder.cities import (
    CITY_NAMES,
    KLEINANZEIGEN_LOCATIONS,
    KLEINANZEIGEN_PLZ_PREFIXES,
    kleinanzeigen_location,
)
from jobfinder.search_spec import SearchSpec
from jobfinder.sources.http import PoliteClient
from jobfinder.sources.kleinanzeigen import KleinanzeigenScraper

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    return PoliteClient(
        cache_dir=tmp_path_factory.mktemp("kleinanzeigen-ids"),
        budget=len(CITY_NAMES) + 4,
        min_delay=3.0,
    )


def test_every_city_she_can_search_has_an_id():
    """A city added without an id would be skipped at runtime, quietly."""
    missing = [name for name in CITY_NAMES if kleinanzeigen_location(name) is None]
    assert not missing, f"no Kleinanzeigen location id for: {missing}"


@pytest.mark.parametrize("city", sorted(KLEINANZEIGEN_LOCATIONS))
def test_the_id_returns_ads_in_that_city(client, city):
    spec = SearchSpec.build(
        mode="general",
        # Every type, so a quiet city still returns something to look at.
        employment_types=["minijob", "parttime", "fulltime"],
        city_names=[city],
    )
    page = next(iter(KleinanzeigenScraper(client).search_pages(spec)), None)

    assert page is not None, f"{city}: the browse page did not answer"
    if not page.postings:
        pytest.skip(f"{city}: no ads matched today — nothing to check the id against")

    postcodes = [posting.plz for posting in page.postings if posting.plz]
    expected = KLEINANZEIGEN_PLZ_PREFIXES.get(city)

    if expected:
        # Postcodes, not names: a big city labels its ads by borough
        # ("Mitte", "Südstadt"), and a wrong id shows up as a different
        # postcode region entirely.
        assert postcodes, f"{city}: ads parsed but none carried a postcode"
        assert any(code.startswith(expected) for code in postcodes), (
            f"{city}: the mapped id returned postcodes {sorted(set(postcodes))[:5]}, "
            f"expected {expected} — wrong location id"
        )
        return

    located = [posting.city for posting in page.postings if posting.city]
    assert located, f"{city}: ads parsed but none carried a location"
    assert any(city.split()[0].casefold() in place.casefold() for place in located), (
        f"{city}: the mapped id returned ads in {sorted(set(located))[:5]} — wrong location id"
    )
