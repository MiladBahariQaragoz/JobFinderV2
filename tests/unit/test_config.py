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

    assert settings.request_budget == 200
    assert settings.llm_budget == 500
    assert settings.enabled_sources == ("ba",)


def test_settings_override_from_config_yaml(tmp_path):
    (tmp_path / "config.yaml").write_text(
        "request_budget: 40\nllm_budget: 25\nenabled_sources: [ba, arbeitnow]\n",
        encoding="utf-8",
    )

    settings = Settings.load(project_root=tmp_path)

    assert settings.request_budget == 40
    assert settings.llm_budget == 25
    assert settings.enabled_sources == ("ba", "arbeitnow")


def test_unknown_config_key_names_itself_and_the_valid_keys(tmp_path):
    (tmp_path / "config.yaml").write_text("reqeust_budget: 40\n", encoding="utf-8")

    with pytest.raises(ValueError) as excinfo:
        Settings.load(project_root=tmp_path)

    message = str(excinfo.value)
    assert "reqeust_budget" in message
    assert "request_budget" in message
