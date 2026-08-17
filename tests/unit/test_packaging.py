"""What has to be inside `JobFinder.exe` for it to work on a laptop with no Python.

PyInstaller finds imports by reading the code, which means it finds none of the
things this app reaches for by name at runtime: the Jinja templates, the local
htmx and fonts, the prompt files, uvicorn's protocol implementations. Every one
of those is a blank page or a crash on her machine and works perfectly here.

A `.spec` file cannot be tested, so the lists live in `packaging.py` and the
spec is four lines that import them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jobfinder.packaging import (
    BUNDLED_DATA,
    HIDDEN_IMPORTS,
    UpdateRefused,
    apply_update,
    bundled_pairs,
    stage_install,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def bundled_sources() -> list[Path]:
    return [source for source, _destination in bundled_pairs()]


def test_the_bundle_includes_every_template():
    templates = sorted((REPO_ROOT / "src" / "jobfinder" / "web" / "templates").glob("*.html"))
    bundled = bundled_sources()

    assert templates, "no templates found at all — the path in this test is wrong"
    for template in templates:
        assert any(template == source or source in template.parents for source in bundled), (
            f"{template.name} would be missing from the exe"
        )


def test_the_bundle_includes_the_static_files_the_app_serves_offline():
    """htmx and both fonts are local files precisely so the exe works with no
    internet — bundling the templates and forgetting these gives her an
    unstyled page that does not react to a click."""
    static = REPO_ROOT / "src" / "jobfinder" / "web" / "static"
    bundled = bundled_sources()

    for needed in (static / "app.css", static / "vendor" / "htmx.min.js"):
        assert needed.exists(), f"{needed} is not in the repo — this test is out of date"
        assert any(needed == source or source in needed.parents for source in bundled)


def test_the_bundle_includes_the_prompt_files():
    """The prompts are read from disk by name at runtime (`load_prompt`), so
    nothing in the import graph points at them."""
    prompts = list((REPO_ROOT / "src" / "jobfinder").rglob("*.md"))
    bundled = bundled_sources()

    assert prompts, "no prompt files found — this test is out of date"
    for prompt in prompts:
        assert any(prompt == source or source in prompt.parents for source in bundled)


def test_the_bundle_names_the_hidden_imports_uvicorn_needs():
    for needed in ("uvicorn.protocols.http.h11_impl", "uvicorn.lifespan.on"):
        assert needed in HIDDEN_IMPORTS


def test_every_bundled_path_exists():
    for source, _destination in bundled_pairs():
        assert source.exists(), f"{source} is listed for the bundle and is not there"


def test_the_destinations_keep_the_package_layout():
    """A template bundled to the wrong folder is found by nothing."""
    destinations = {destination for _source, destination in bundled_pairs()}

    assert "jobfinder/web/templates" in destinations
    assert "jobfinder/web/static" in destinations


def test_the_declared_data_is_relative_to_the_package():
    """Absolute paths from this machine would be baked into the spec and mean
    nothing on hers."""
    for source, destination in BUNDLED_DATA:
        assert not Path(source).is_absolute()
        assert not Path(destination).is_absolute()


def test_the_spec_file_reads_its_lists_from_the_packaging_module():
    spec = (REPO_ROOT / "JobFinder.spec").read_text(encoding="utf-8")

    assert "from jobfinder.packaging import" in spec
    assert "HIDDEN_IMPORTS" in spec
    # The whole point: no literal file lists in a file no test can run.
    assert "templates" not in spec


# -- updating an install -------------------------------------------------------


class TestApplyUpdate:
    """An update replaces one file. Everything she owns is left alone."""

    def installed(self, tmp_path):
        install = tmp_path / "JobFinder"
        (install / "data").mkdir(parents=True)
        (install / "JobFinder.exe").write_bytes(b"the old build")
        (install / "data" / "jobfinder.db").write_bytes(b"her 859 jobs")
        (install / "pool.yaml").write_text("basics: {}\n", encoding="utf-8")
        (install / ".env").write_text("GROQ_API_KEY=hers\n", encoding="utf-8")
        return install

    def test_an_update_replaces_the_exe(self, tmp_path):
        install = self.installed(tmp_path)
        new = tmp_path / "JobFinder.exe"
        new.write_bytes(b"the new build")

        target = apply_update(new, install)

        assert target.read_bytes() == b"the new build"

    def test_an_update_keeps_the_previous_exe_as_a_rollback(self, tmp_path):
        install = self.installed(tmp_path)
        new = tmp_path / "JobFinder.exe"
        new.write_bytes(b"the new build")

        apply_update(new, install)

        assert (install / "JobFinder.exe.previous").read_bytes() == b"the old build"

    def test_an_update_leaves_her_data_untouched(self, tmp_path):
        install = self.installed(tmp_path)
        new = tmp_path / "JobFinder.exe"
        new.write_bytes(b"the new build")

        apply_update(new, install)

        assert (install / "data" / "jobfinder.db").read_bytes() == b"her 859 jobs"
        assert (install / "pool.yaml").exists()
        assert (install / ".env").read_text(encoding="utf-8") == "GROQ_API_KEY=hers\n"

    def test_an_update_refuses_something_that_is_not_a_program(self, tmp_path):
        install = self.installed(tmp_path)
        not_a_build = tmp_path / "JobFinder.zip"
        not_a_build.write_bytes(b"PK")

        with pytest.raises(UpdateRefused) as refused:
            apply_update(not_a_build, install)

        assert "JobFinder.zip" in str(refused.value)
        assert (install / "JobFinder.exe").read_bytes() == b"the old build"

    def test_an_update_refuses_a_file_that_is_not_there(self, tmp_path):
        install = self.installed(tmp_path)

        with pytest.raises(UpdateRefused):
            apply_update(tmp_path / "nowhere.exe", install)

    def test_installing_where_nothing_is_installed_yet_just_works(self, tmp_path):
        install = tmp_path / "fresh"
        install.mkdir()
        new = tmp_path / "JobFinder.exe"
        new.write_bytes(b"the first build")

        target = apply_update(new, install)

        assert target.read_bytes() == b"the first build"
        assert not (install / "JobFinder.exe.previous").exists()

    def test_a_locked_exe_is_refused_readably(self, tmp_path, monkeypatch):
        """Not the running-app case — that one works, measured against a live
        install on 2026-08-17. This is a file something else is holding: an
        antivirus scan mid-copy, or a folder she cannot write to."""
        install = self.installed(tmp_path)
        new = tmp_path / "JobFinder.exe"
        new.write_bytes(b"the new build")

        def locked(*args, **kwargs):
            raise OSError(32, "The process cannot access the file")

        monkeypatch.setattr(Path, "rename", locked)

        with pytest.raises(UpdateRefused) as refused:
            apply_update(new, install)

        assert "could not be replaced" in str(refused.value)


def test_the_bundle_includes_the_llmpool_catalog():
    """Found by building the exe and pressing nothing at all: `/setup` was a
    500 because `llmpool.load_catalog()` reads `catalog.yaml` off disk by name,
    and a dependency's data file is as invisible to PyInstaller as our own.
    """
    import llmpool

    catalog = Path(llmpool.__file__).resolve().parent / "catalog.yaml"
    bundled = bundled_sources()

    assert catalog.exists(), "llmpool has no catalog.yaml — this test is out of date"
    assert any(catalog == source or source in catalog.parents for source in bundled)


class TestStagingAnInstall:
    """Handing it over means a folder, not a file.

    The person this is built for has no provider accounts and cannot sign up for
    any, so the keys travel with the app — as a `.env` beside the exe, which is
    what `Settings.load` already reads. Never baked into the binary: a key
    inside a 19 MB program cannot be rotated, cannot be seen, and goes wherever
    that program goes.
    """

    def test_the_folder_gets_the_exe(self, tmp_path):
        exe = tmp_path / "JobFinder.exe"
        exe.write_bytes(b"the build")

        target = stage_install(exe, tmp_path / "handover")

        assert (target / "JobFinder.exe").read_bytes() == b"the build"

    def test_the_keys_travel_beside_it(self, tmp_path):
        exe = tmp_path / "JobFinder.exe"
        exe.write_bytes(b"the build")
        env = tmp_path / ".env"
        env.write_text("GROQ_API_KEY=hers\n", encoding="utf-8")

        target = stage_install(exe, tmp_path / "handover", env_file=env)

        assert (target / ".env").read_text(encoding="utf-8") == "GROQ_API_KEY=hers\n"

    def test_only_the_keys_travel_and_not_the_rest_of_the_env(self, tmp_path):
        """A developer `.env` collects things that are nobody else's business.
        Only the variables a provider or a source needs are copied."""
        exe = tmp_path / "JobFinder.exe"
        exe.write_bytes(b"the build")
        env = tmp_path / ".env"
        env.write_text(
            "GROQ_API_KEY=hers\nADZUNA_APP_ID=123\nSOME_PERSONAL_TOKEN=nope\n", encoding="utf-8"
        )

        target = stage_install(exe, tmp_path / "handover", env_file=env)

        written = (target / ".env").read_text(encoding="utf-8")
        assert "GROQ_API_KEY" in written
        assert "ADZUNA_APP_ID" in written
        assert "SOME_PERSONAL_TOKEN" not in written

    def test_a_folder_with_her_data_in_it_is_not_overwritten(self, tmp_path):
        """Staging over an install she has been using must not touch her work."""
        exe = tmp_path / "JobFinder.exe"
        exe.write_bytes(b"the new build")
        target = tmp_path / "handover"
        (target / "data").mkdir(parents=True)
        (target / "data" / "jobfinder.db").write_bytes(b"her jobs")
        (target / "config.yaml").write_text("cities: [Ingolstadt]\n", encoding="utf-8")

        stage_install(exe, target)

        assert (target / "data" / "jobfinder.db").read_bytes() == b"her jobs"
        assert (target / "config.yaml").exists()

    def test_it_says_what_it_put_there(self, tmp_path):
        exe = tmp_path / "JobFinder.exe"
        exe.write_bytes(b"the build")
        env = tmp_path / ".env"
        env.write_text("GROQ_API_KEY=hers\n", encoding="utf-8")

        target = stage_install(exe, tmp_path / "handover", env_file=env)

        assert target.name == "handover"

    def test_no_env_file_means_no_env_file(self, tmp_path):
        exe = tmp_path / "JobFinder.exe"
        exe.write_bytes(b"the build")

        target = stage_install(exe, tmp_path / "handover")

        assert not (target / ".env").exists()


class TestSeedingHerInstall:
    """Handing over the work already done, not an empty app.

    860 jobs, 46 of them explained at the cost of real free-tier calls, 357
    places to ring with a German script each, and the two she has already
    handled. None of it can be recreated by pressing Search — the postings that
    have since expired are gone, and the explanations would cost the quota
    again — so it travels with the exe.
    """

    def built(self, tmp_path):
        exe = tmp_path / "JobFinder.exe"
        exe.write_bytes(b"the build")
        return exe

    def a_used_data_dir(self, tmp_path):
        data = tmp_path / "data"
        (data / "http-cache").mkdir(parents=True)
        (data / "http-cache" / "abc.json").write_text("{}", encoding="utf-8")
        (data / "backups" / "2026-08-17T10-00-00Z").mkdir(parents=True)
        (data / "jobfinder.db").write_bytes(b"860 jobs")
        (data / "jobs-init.csv").write_text("job_id\n", encoding="utf-8-sig")
        (data / "contacts.csv").write_text("contact_id\n", encoding="utf-8-sig")
        (data / "llm-cache.db").write_bytes(b"54 answers already paid for")
        return data

    def test_the_seed_brings_the_database_and_the_csvs(self, tmp_path):
        target = stage_install(
            self.built(tmp_path), tmp_path / "handover", seed_from=self.a_used_data_dir(tmp_path)
        )

        assert (target / "data" / "jobfinder.db").read_bytes() == b"860 jobs"
        assert (target / "data" / "jobs-init.csv").exists()
        assert (target / "data" / "contacts.csv").exists()
        assert (target / "data" / "llm-cache.db").exists()

    def test_the_seed_leaves_the_caches_and_the_old_backups_behind(self, tmp_path):
        """63 MB of pages any run can fetch again, and backups of a machine that
        is not hers."""
        target = stage_install(
            self.built(tmp_path), tmp_path / "handover", seed_from=self.a_used_data_dir(tmp_path)
        )

        assert not (target / "data" / "http-cache").exists()
        assert not (target / "data" / "backups").exists()

    def test_a_store_already_there_is_never_replaced(self, tmp_path):
        """Seeding twice, or seeding over an install she has been using, must
        not throw away the jobs she has marked since."""
        target = tmp_path / "handover"
        (target / "data").mkdir(parents=True)
        (target / "data" / "jobfinder.db").write_bytes(b"her own work since")

        stage_install(self.built(tmp_path), target, seed_from=self.a_used_data_dir(tmp_path))

        assert (target / "data" / "jobfinder.db").read_bytes() == b"her own work since"

    def test_her_cv_travels_when_it_is_handed_over(self, tmp_path):
        cv = tmp_path / "pool.yaml"
        cv.write_text("basics:\n  name: Her\n", encoding="utf-8")

        target = stage_install(self.built(tmp_path), tmp_path / "handover", cv=cv)

        assert (target / "pool.yaml").read_text(encoding="utf-8") == "basics:\n  name: Her\n"

    def test_a_cv_already_there_is_not_overwritten(self, tmp_path):
        cv = tmp_path / "pool.yaml"
        cv.write_text("basics:\n  name: Old\n", encoding="utf-8")
        target = tmp_path / "handover"
        target.mkdir()
        (target / "pool.yaml").write_text("basics:\n  name: Newer\n", encoding="utf-8")

        stage_install(self.built(tmp_path), target, cv=cv)

        assert "Newer" in (target / "pool.yaml").read_text(encoding="utf-8")

    def test_seeding_nothing_is_not_an_error(self, tmp_path):
        target = stage_install(self.built(tmp_path), tmp_path / "handover", seed_from=None)

        assert (target / "JobFinder.exe").exists()
