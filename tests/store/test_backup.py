"""A copy of what cannot be re-fetched, taken before every run.

Measured on her real `data/` (2026-08-17): 66 MB in the directory, 63 MB of it
`http-cache/` — pages any run can fetch again. The database and the CSVs are
3.5 MB and are the only things a bad run could cost her, so those are what a
backup holds. Copying the directory would be nineteen times the bytes for the
same protection, five times over.
"""

from __future__ import annotations

from jobfinder.backup import BACKUPS_KEPT, back_up_data, backup_dir
from jobfinder.config import Settings


def _data_dir_with_everything(settings: Settings) -> None:
    """A `data/` the way a used app leaves it — a real database, because the
    runs in this file open the file the backup copies."""
    from jobfinder.store.db import connect, migrate

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    connection = connect(settings.db_path)
    try:
        migrate(connection)
    finally:
        connection.close()
    settings.jobs_init_csv.write_text("job_id\nBA:1\n", encoding="utf-8-sig")
    settings.jobs_enriched_csv.write_text("job_id\nBA:1\n", encoding="utf-8-sig")
    settings.contacts_csv.write_text("contact_id\nnode/1\n", encoding="utf-8-sig")
    settings.llm_cache_path.write_bytes(b"answers already paid for")
    cache = settings.data_dir / "http-cache"
    cache.mkdir(exist_ok=True)
    (cache / "abc123.json").write_text("{}", encoding="utf-8")


def test_a_backup_copies_the_database_and_the_csvs(tmp_path):
    settings = Settings(project_root=tmp_path)
    _data_dir_with_everything(settings)

    written = back_up_data(settings)

    assert (written / "jobfinder.db").read_bytes() == settings.db_path.read_bytes()
    assert (written / "jobs-init.csv").exists()
    assert (written / "jobs-enriched.csv").exists()
    assert (written / "contacts.csv").exists()
    assert (written / "llm-cache.db").exists()


def test_a_backup_leaves_the_http_cache_alone(tmp_path):
    settings = Settings(project_root=tmp_path)
    _data_dir_with_everything(settings)

    written = back_up_data(settings)

    assert not (written / "http-cache").exists()


def test_backup_rotation_keeps_five_and_deletes_the_sixth(tmp_path):
    settings = Settings(project_root=tmp_path)
    _data_dir_with_everything(settings)

    made = [back_up_data(settings, stamp=f"2026-08-17T10-0{n}-00Z") for n in range(6)]

    kept = sorted(path.name for path in backup_dir(settings).iterdir())
    assert len(kept) == BACKUPS_KEPT == 5
    assert made[0].name not in kept, "the oldest backup should have been dropped"
    assert made[-1].name in kept


def test_a_first_run_with_nothing_to_copy_is_not_an_error(tmp_path):
    settings = Settings(project_root=tmp_path)

    written = back_up_data(settings)

    assert written is None, "there was nothing worth copying, and that is not a failure"


def test_a_backup_that_cannot_be_written_never_fails_the_run(tmp_path, monkeypatch):
    settings = Settings(project_root=tmp_path)
    _data_dir_with_everything(settings)

    def refuse(*args, **kwargs):
        raise OSError("the disk is full")

    monkeypatch.setattr("shutil.copy2", refuse)

    assert back_up_data(settings) is None


def test_a_search_started_from_the_browser_backs_up_first(tmp_path):
    """The rule is "before every run", and a run she starts herself is the one
    that most needs it — she is about to change eight hundred stored rows."""
    from jobfinder.sources.base import PageResult, RawPosting
    from jobfinder.web.runs import RunManager

    settings = Settings(project_root=tmp_path)
    _data_dir_with_everything(settings)

    class OneQuietPage:
        source = "BA"

        def search_pages(self, spec, *, start_query_index=0, start_page=1):
            yield PageResult(
                source="BA",
                query_index=0,
                page=1,
                postings=[RawPosting(job_id="BA:1", source="BA", source_id="1", title="Job")],
            )

    manager = RunManager(settings, adapter_factory=lambda: [OneQuietPage()])
    manager.start()
    manager.wait(timeout=10)

    taken = sorted(backup_dir(settings).iterdir())
    assert len(taken) == 1
    assert (taken[0] / "jobfinder.db").exists()


def test_an_explanation_pass_backs_up_first_too(tmp_path):
    """It spends free-tier calls and writes their answers into the same
    database — the same reason, on a smaller run."""
    from jobfinder.web.runs import RunManager

    settings = Settings(project_root=tmp_path)
    _data_dir_with_everything(settings)

    class QuietCompanion:
        def start(self):
            pass

        def finish(self):
            pass

        def cancel(self):
            pass

    manager = RunManager(settings, companion_factory=lambda *, limit=None: QuietCompanion())
    manager.start_enrich(limit=1)
    manager.wait_enrich(timeout=10)

    assert len(list(backup_dir(settings).iterdir())) == 1


def test_a_call_list_run_backs_up_first_too(tmp_path):
    from jobfinder.web.runs import RunManager

    settings = Settings(project_root=tmp_path)
    _data_dir_with_everything(settings)

    manager = RunManager(
        settings,
        contacts_runner=lambda **kwargs: None,
        contacts_source_factory=lambda: object(),
    )
    manager.start_contacts(cities="Ingolstadt")
    manager.wait_contacts(timeout=10)

    assert len(list(backup_dir(settings).iterdir())) == 1


def test_a_search_from_the_command_line_backs_up_too(tmp_path):
    """The CLI is mine, but it writes to the same database hers reads."""
    from jobfinder.cli import main
    from jobfinder.search import SearchSummary

    settings = Settings(project_root=tmp_path)
    _data_dir_with_everything(settings)

    def fake_runner(*args, **kwargs):
        return SearchSummary(
            run_id=1, state="done", found=0, new=0, duplicates=0, errors=[], resumed=False
        )

    exit_code = main(
        ["search", "--root", str(tmp_path), "--cities", "Ingolstadt"],
        _runner=fake_runner,
        _client_factory=lambda _settings: [],
    )

    assert exit_code == 0
    assert len(list(backup_dir(settings).iterdir())) == 1


def test_a_call_list_from_the_command_line_backs_up_too(tmp_path):
    from jobfinder.cli import main

    settings = Settings(project_root=tmp_path)
    _data_dir_with_everything(settings)

    class NoPlaces:
        failures: list[str] = []

        def places_near(self, lat, lon, *, city, radius_km=6):
            return []

    exit_code = main(
        ["contacts", "--root", str(tmp_path), "--cities", "Ingolstadt"],
        _contacts_source=lambda _settings, _client: NoPlaces(),
    )

    assert exit_code == 0
    assert len(list(backup_dir(settings).iterdir())) == 1


def test_an_explanation_pass_from_the_command_line_backs_up_too(tmp_path):
    import yaml
    from tests.fakes import FakePool

    from jobfinder.cli import main

    settings = Settings(project_root=tmp_path)
    _data_dir_with_everything(settings)
    settings.pool_path.write_text(
        yaml.safe_dump(
            {
                "basics": {
                    "name": "Jane Doe",
                    "email": "j@example.com",
                    "location": "Neuburg an der Donau, Germany",
                },
                "skills": {"Office": ["Excel"]},
                "languages": [{"name": "English", "level": "C1"}],
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(
        ["enrich", "--root", str(tmp_path)],
        _pool_factory=lambda _settings, _validator: FakePool([]),
    )

    assert exit_code == 0
    assert len(list(backup_dir(settings).iterdir())) == 1


def test_a_dry_run_backs_up_nothing_because_it_changes_nothing(tmp_path):
    from jobfinder.cli import main

    settings = Settings(project_root=tmp_path)
    _data_dir_with_everything(settings)

    main(
        ["search", "--root", str(tmp_path), "--dry-run", "--cities", "Ingolstadt"],
        _client_factory=lambda _settings: [],
    )

    assert not backup_dir(settings).exists()
