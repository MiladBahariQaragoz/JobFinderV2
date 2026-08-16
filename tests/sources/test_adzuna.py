"""Adzuna adapter — the optional source.

No `ADZUNA_APP_ID`/`ADZUNA_APP_KEY` existed when this was written, so nothing
here touches the network: these tests pin the skip behaviour (absent keys are
a skip, never an error) and the query builder's shape. The parameter values
are Adzuna's documented ones, recorded for live verification the day a key is
registered — parsing code and its fixture tests wait for that day.
"""

from __future__ import annotations

import pytest

from jobfinder.config import Settings
from jobfinder.search_spec import SearchSpec
from jobfinder.sources.registry import build_adapters


def spec(**overrides) -> SearchSpec:
    parts = dict(mode="general", employment_types=["parttime"], city_names=["Ingolstadt"])
    parts.update(overrides)
    return SearchSpec.build(**parts)


@pytest.fixture
def no_keys(monkeypatch):
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv("ADZUNA_APP_ID", "test-id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "test-key")


class TestSkip:
    def test_adzuna_adapter_is_skipped_cleanly_without_keys(self, tmp_path, no_keys):
        settings = Settings(project_root=tmp_path, enabled_sources=("ba", "adzuna"))
        built = build_adapters(settings, lambda _s: object())
        assert [adapter.source for adapter in built.adapters] == ["BA"]  # no AZ, no crash
        assert dict(built.skipped)["adzuna"] == "no API key in .env"

    def test_with_keys_the_adapter_is_built(self, tmp_path, keys):
        settings = Settings(project_root=tmp_path, enabled_sources=("adzuna",))
        built = build_adapters(settings, lambda _s: object())
        assert [adapter.source for adapter in built.adapters] == ["AZ"]

    def test_an_adapter_without_keys_refuses_to_search_readably(self, no_keys):
        from jobfinder.sources.adzuna import AdzunaApi

        api = AdzunaApi(client=None)  # constructed directly, keys vanished since
        with pytest.raises(Exception) as excinfo:
            list(api.search_pages(spec()))
        message = str(excinfo.value)
        assert "ADZUNA_APP_ID" in message and ".env" in message


def queries_for(**overrides):
    from jobfinder.sources.adzuna import build_queries

    return build_queries(spec(**overrides), app_id="test-id", app_key="test-key")


class TestBuildQueries:
    def test_query_carries_keys_city_and_radius(self, keys):
        queries = queries_for()
        assert len(queries) == 1
        params = queries[0].params()
        assert params["app_id"] == "test-id"
        assert params["app_key"] == "test-key"
        assert params["where"] == "Ingolstadt"
        assert params["distance"] == 25  # her default radius, in km
        assert params["results_per_page"] == 50

    def test_one_query_per_employment_type_never_stacked(self, keys):
        # The Phase 4 audit rule: types are alternatives. Adzuna's full_time /
        # part_time flags are combined with AND server-side, so stacking them
        # would ask for a job that is both — one query per type instead.
        queries = queries_for(employment_types=["parttime", "fulltime"])
        assert len(queries) == 2
        flags = [q.params().get("part_time", 0) + q.params().get("full_time", 0) for q in queries]
        assert flags == [1, 1]  # exactly one flag set per query

    def test_werkstudent_and_internship_travel_as_search_terms(self, keys):
        queries = queries_for(employment_types=["werkstudent", "internship"])
        whats = {q.params().get("what") for q in queries}
        assert whats == {"Werkstudent", "Praktikum"}
        for query in queries:
            assert "part_time" not in query.params()
            assert "full_time" not in query.params()

    def test_her_keywords_become_the_what_term(self, keys):
        queries = queries_for(employment_types=["parttime"], keywords=["kellner"])
        assert queries[0].params()["what"] == "kellner"

    def test_the_url_targets_the_german_search_endpoint(self, keys):
        query = queries_for()[0]
        assert query.url().startswith("https://api.adzuna.com/v1/api/jobs/de/search/1?")
