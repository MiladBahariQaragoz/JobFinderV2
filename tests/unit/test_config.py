import pytest

from jobfinder.config import Settings


def test_settings_defaults_point_into_data_dir(tmp_path):
    settings = Settings.load(project_root=tmp_path)

    assert settings.data_dir == tmp_path / "data"
    assert settings.db_path == tmp_path / "data" / "jobfinder.db"
    assert settings.jobs_init_csv == tmp_path / "data" / "jobs-init.csv"
    assert settings.jobs_enriched_csv == tmp_path / "data" / "jobs-enriched.csv"
    assert settings.pool_state_path == tmp_path / "data" / "pool_state.json"


def test_settings_defaults_when_no_config_file_exists(tmp_path):
    settings = Settings.load(project_root=tmp_path)

    # One leg's worth of requests: enough to get through a city at a polite
    # pace, small enough that a runaway stops within the hour.
    assert settings.request_budget == 800
    assert settings.max_search_legs == 6
    assert settings.llm_budget == 500
    # The sources that answer this machine. StepStone and Indeed are known
    # and off by default — they blocked this client in testing.
    assert settings.enabled_sources == ("ba", "arbeitnow", "adzuna", "kleinanzeigen", "xing")


def test_request_pacing_defaults_differ_by_host_kind(tmp_path):
    # §8 rule 1: 3 s keeps a scraped site from blocking her, and a documented
    # API is not a scraped site.
    settings = Settings.load(project_root=tmp_path)

    assert settings.api_delay_seconds == 1.0
    assert settings.scraper_delay_seconds == 3.0


def test_settings_override_from_config_yaml(tmp_path):
    (tmp_path / "config.yaml").write_text(
        "request_budget: 40\nllm_budget: 25\nenabled_sources: [ba, arbeitnow]\n"
        "api_delay_seconds: 2.5\n",
        encoding="utf-8",
    )

    settings = Settings.load(project_root=tmp_path)

    assert settings.request_budget == 40
    assert settings.llm_budget == 25
    assert settings.enabled_sources == ("ba", "arbeitnow")
    assert settings.api_delay_seconds == 2.5  # she can slow it down again


def test_secrets_are_read_from_env_not_config_yaml(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text("groq_api_key: leaked-into-config\n", encoding="utf-8")
    monkeypatch.setenv("GROQ_API_KEY", "from-the-environment")

    with pytest.raises(ValueError, match="groq_api_key"):
        Settings.load(project_root=tmp_path)


def test_env_file_next_to_the_project_is_loaded(tmp_path, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    (tmp_path / ".env").write_text('GROQ_API_KEY="key-from-dotenv"\n', encoding="utf-8")

    Settings.load(project_root=tmp_path)

    import os

    assert os.environ["GROQ_API_KEY"] == "key-from-dotenv"


def test_existing_environment_wins_over_the_env_file(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "already-set")
    (tmp_path / ".env").write_text("GROQ_API_KEY=from-dotenv\n", encoding="utf-8")

    Settings.load(project_root=tmp_path)

    import os

    assert os.environ["GROQ_API_KEY"] == "already-set"


def test_unknown_config_key_names_itself_and_the_valid_keys(tmp_path):
    (tmp_path / "config.yaml").write_text("reqeust_budget: 40\n", encoding="utf-8")

    with pytest.raises(ValueError) as excinfo:
        Settings.load(project_root=tmp_path)

    message = str(excinfo.value)
    assert "reqeust_budget" in message
    assert "request_budget" in message


def test_enrichment_worker_count_has_a_default_and_can_be_tuned(tmp_path):
    """How many jobs are in flight at once. Free tiers are the reason it is low."""
    assert Settings(project_root=tmp_path).llm_workers == 4

    (tmp_path / "config.yaml").write_text("llm_workers: 2\n", encoding="utf-8", newline="\n")

    assert Settings.load(tmp_path).llm_workers == 2
