"""The source registry — adapters exist only for sources she has enabled.

Adapters each get their own HTTP client, and therefore their own request
budget (Phase 4 audit: a source's budget is spent per leg, per source). A
source that cannot run — Adzuna without keys — is reported as skipped, never
as an error, and a configured-but-off source says so too.
"""

from __future__ import annotations

import pytest

from jobfinder.config import Settings
from jobfinder.sources.ba import BAApi
from jobfinder.sources.registry import KNOWN_SOURCES, build_adapters


class FakeAdapter:
    def __init__(self, client, source):
        self._client = client
        self.source = source


@pytest.fixture
def no_adzuna_keys(monkeypatch):
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)


@pytest.fixture
def adzuna_keys(monkeypatch):
    monkeypatch.setenv("ADZUNA_APP_ID", "test-id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "test-key")


def clients_tracker():
    """A client factory that hands out a fresh marker per call and records it."""
    made = []

    def factory(_settings):
        marker = object()
        made.append(marker)
        return marker

    return factory, made


class TestBuildAdapters:
    def test_every_enabled_source_gets_an_adapter_with_its_own_client(
        self, tmp_path, no_adzuna_keys
    ):
        settings = Settings(project_root=tmp_path, enabled_sources=("ba", "arbeitnow"))
        factory, made = clients_tracker()

        built = build_adapters(settings, factory)

        assert [adapter.source for adapter in built.adapters] == ["BA", "AN"]
        assert len(made) == 2  # one client per adapter — one budget per source
        assert built.adapters[0]._client is not built.adapters[1]._client

    def test_order_is_fixed_regardless_of_settings_order(self, tmp_path, no_adzuna_keys):
        settings = Settings(project_root=tmp_path, enabled_sources=("arbeitnow", "ba"))
        built = build_adapters(settings, lambda _s: object())
        assert [adapter.source for adapter in built.adapters] == ["BA", "AN"]

    def test_registry_runs_only_enabled_sources(self, tmp_path, no_adzuna_keys):
        settings = Settings(project_root=tmp_path, enabled_sources=("ba",))
        built = build_adapters(settings, lambda _s: object())
        assert [adapter.source for adapter in built.adapters] == ["BA"]
        assert isinstance(built.adapters[0], BAApi)

    def test_adzuna_without_keys_is_skipped_not_an_error(self, tmp_path, no_adzuna_keys):
        settings = Settings(project_root=tmp_path, enabled_sources=("ba", "adzuna"))
        built = build_adapters(settings, lambda _s: object())
        assert [adapter.source for adapter in built.adapters] == ["BA"]
        assert built.skipped == (
            ("arbeitnow", "disabled in config.yaml"),
            ("adzuna", "no API key in .env"),
        )

    def test_adzuna_with_keys_runs_and_gets_its_own_client(self, tmp_path, adzuna_keys):
        settings = Settings(project_root=tmp_path, enabled_sources=("ba", "adzuna"))
        factory, made = clients_tracker()
        built = build_adapters(settings, factory)
        assert [adapter.source for adapter in built.adapters] == ["BA", "AZ"]
        assert len(made) == 2

    def test_a_known_source_left_out_of_settings_is_reported_disabled(
        self, tmp_path, no_adzuna_keys
    ):
        settings = Settings(project_root=tmp_path, enabled_sources=("ba",))
        built = build_adapters(settings, lambda _s: object())
        assert built.skipped == (
            ("arbeitnow", "disabled in config.yaml"),
            ("adzuna", "disabled in config.yaml"),
        )

    def test_unknown_source_name_names_the_valid_ones(self, tmp_path, no_adzuna_keys):
        settings = Settings(project_root=tmp_path, enabled_sources=("ba", "linkedin"))
        with pytest.raises(ValueError) as excinfo:
            build_adapters(settings, lambda _s: object())
        message = str(excinfo.value)
        assert "linkedin" in message
        for known in KNOWN_SOURCES:
            assert known in message


class TestDefaults:
    def test_default_enabled_sources_are_the_free_apis(self, tmp_path):
        settings = Settings(project_root=tmp_path)
        assert settings.enabled_sources == ("ba", "arbeitnow")

    def test_a_fresh_project_builds_both_adapters_by_default(self, tmp_path, no_adzuna_keys):
        built = build_adapters(Settings(project_root=tmp_path), lambda _s: object())
        assert [adapter.source for adapter in built.adapters] == ["BA", "AN"]
