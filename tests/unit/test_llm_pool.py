"""build_pool — one Pool per run, wired from Settings, with readable failures."""

from __future__ import annotations

import pytest

from jobfinder.config import Settings
from jobfinder.llm.pool import LLMConfigError, build_pool


class FakeProvider:
    name = "fake"
    rpm = 60


def test_build_pool_raises_a_readable_error_when_no_provider_keys_exist(tmp_path):
    settings = Settings.load(tmp_path)

    with pytest.raises(LLMConfigError) as exc:
        build_pool(settings, providers=[])

    message = str(exc.value)
    assert ".env" in message
    assert "doctor" in message


def test_build_pool_wires_settings_validator_and_state(tmp_path):
    settings = Settings.load(tmp_path)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    sentinel = lambda answer: (True, "ok")  # noqa: E731 - minimal validator

    pool = build_pool(settings, validator=sentinel, providers=[FakeProvider()])

    assert pool.providers[0].name == "fake"
    assert pool.validator is sentinel
    assert pool.state_path == settings.pool_state_path
    assert pool.max_wait == settings.llm_max_wait_seconds


def test_settings_default_llm_bounds_are_sane(tmp_path):
    settings = Settings.load(tmp_path)

    assert settings.llm_max_wait_seconds > 0
    assert settings.llm_run_deadline_seconds >= settings.llm_max_wait_seconds


def test_llm_bounds_come_from_config_yaml(tmp_path):
    (tmp_path / "config.yaml").write_text(
        "llm_max_wait_seconds: 600\nllm_run_deadline_seconds: 1200\n",
        encoding="utf-8",
    )

    settings = Settings.load(tmp_path)

    assert settings.llm_max_wait_seconds == 600
    assert settings.llm_run_deadline_seconds == 1200
