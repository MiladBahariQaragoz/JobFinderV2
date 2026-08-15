"""`jobfinder llm doctor` — provider health plus our cache, one command."""

from __future__ import annotations

from jobfinder.cli import main
from jobfinder.config import Settings
from jobfinder.llm.cache import LLMCache


def test_llm_doctor_runs_llmpool_doctor_and_reports_the_cache(tmp_path, capsys):
    settings = Settings.load(tmp_path)
    cache = LLMCache(settings.llm_cache_path)
    cache.put("k1", {"a": 1})
    cache.put("k2", {"b": 2})
    cache.close()

    seen: list[str] = []

    def fake_run_doctor(settings: Settings) -> int:
        seen.append(settings.project_root)
        return 0

    exit_code = main(["llm", "doctor", "--root", str(tmp_path)], _run_doctor=fake_run_doctor)

    out = capsys.readouterr().out
    assert exit_code == 0
    assert seen == [tmp_path]
    assert "2" in out
    assert "cached answer" in out


def test_llm_doctor_mentions_missing_cache_without_error(tmp_path, capsys):
    exit_code = main(["llm", "doctor", "--root", str(tmp_path)], _run_doctor=lambda s: 0)

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "no cache yet" in out


def test_llm_doctor_propagates_doctor_failure(tmp_path, capsys):
    exit_code = main(["llm", "doctor", "--root", str(tmp_path)], _run_doctor=lambda s: 1)

    assert exit_code == 1


def test_settings_cache_path_lives_in_data_dir(tmp_path):
    settings = Settings.load(tmp_path)

    assert settings.llm_cache_path == tmp_path / "data" / "llm-cache.db"
