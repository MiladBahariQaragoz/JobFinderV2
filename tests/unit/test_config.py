from jobfinder.config import Settings


def test_settings_defaults_point_into_data_dir(tmp_path):
    settings = Settings.load(project_root=tmp_path)

    assert settings.data_dir == tmp_path / "data"
    assert settings.db_path == tmp_path / "data" / "jobfinder.db"
    assert settings.jobs_init_csv == tmp_path / "data" / "jobs-init.csv"
    assert settings.jobs_enriched_csv == tmp_path / "data" / "jobs-enriched.csv"
    assert settings.pool_state_path == tmp_path / "data" / "pool_state.json"
