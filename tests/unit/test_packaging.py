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

    def test_a_running_exe_is_refused_readably(self, tmp_path, monkeypatch):
        """Windows locks a running program's file. She will hit this the first
        time she updates without closing the app."""
        install = self.installed(tmp_path)
        new = tmp_path / "JobFinder.exe"
        new.write_bytes(b"the new build")

        def locked(*args, **kwargs):
            raise OSError(32, "The process cannot access the file")

        monkeypatch.setattr(Path, "rename", locked)

        with pytest.raises(UpdateRefused) as refused:
            apply_update(new, install)

        assert "close its window" in str(refused.value)


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
