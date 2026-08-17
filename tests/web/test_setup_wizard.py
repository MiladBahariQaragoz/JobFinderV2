"""The first thing she ever sees: four questions, then the app.

Until this page is finished there is no `config.yaml`, which means no cities, no
employment types, and — most likely — no API key. Every other page in the app
would work, and every one of them would be lying about what it can do, so they
all lead here until it is done.

Nothing in this file may ever assert that a key *value* reached a page. Reading
one back out is the failure it guards against.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from jobfinder.config import Settings
from jobfinder.web.app import create_app

KEY = "sk-test-not-a-real-key-2f9c"


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    """A project root as she first meets it: no config, no .env, no CV."""
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    # The directory's autouse fixture marks an app that is already set up; this
    # file is the one place that needs the opposite.
    (tmp_path / "config.yaml").unlink(missing_ok=True)
    settings = Settings(project_root=tmp_path)
    with TestClient(create_app(settings)) as client:
        yield settings, client


def test_first_run_wizard_appears_when_no_config_exists(fresh):
    _settings, client = fresh

    response = client.get("/setup")

    assert response.status_code == 200
    assert "Welcome" in response.text


def test_every_page_leads_to_the_wizard_until_it_is_finished(fresh):
    _settings, client = fresh

    for path in ("/", "/search", "/enrich", "/contacts", "/settings"):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 303, path
        assert response.headers["location"] == "/setup", path


def test_wizard_is_skipped_on_second_start(tmp_path):
    (tmp_path / "config.yaml").write_text("cities: [Ingolstadt]\n", encoding="utf-8")
    settings = Settings.load(project_root=tmp_path)

    with TestClient(create_app(settings)) as client:
        assert client.get("/", follow_redirects=False).status_code == 200
        # And the wizard itself steps aside rather than asking again.
        assert client.get("/setup", follow_redirects=False).status_code == 303


def test_the_wizard_names_each_provider_and_its_signup_link(fresh):
    _settings, client = fresh

    body = client.get("/setup").text

    assert "GROQ_API_KEY" in body
    assert "https://" in body


def test_wizard_writes_env_and_config_and_never_logs_the_key(fresh, capsys):
    settings, client = fresh

    client.post(
        "/setup",
        data={
            "env_var": "GROQ_API_KEY",
            "api_key": KEY,
            "cities": "Ingolstadt, München",
            "types": "minijob",
        },
        follow_redirects=False,
    )

    env_text = (settings.project_root / ".env").read_text(encoding="utf-8")
    assert f"GROQ_API_KEY={KEY}" in env_text
    config_text = (settings.project_root / "config.yaml").read_text(encoding="utf-8")
    assert "Ingolstadt" in config_text
    assert "minijob" in config_text
    assert KEY not in capsys.readouterr().out


def test_the_key_she_pasted_is_never_rendered_back(fresh):
    _settings, client = fresh

    response = client.post(
        "/setup",
        data={
            "env_var": "GROQ_API_KEY",
            "api_key": KEY,
            "cities": "Ingolstadt",
            "types": "minijob",
        },
    )

    assert KEY not in response.text


def test_a_pasted_key_works_without_restarting_the_app(fresh):
    """Writing the file alone would mean "now restart me", which is a sentence
    she should never have to read."""
    import os

    _settings, client = fresh

    client.post(
        "/setup",
        data={
            "env_var": "GROQ_API_KEY",
            "api_key": KEY,
            "cities": "Ingolstadt",
            "types": "minijob",
        },
    )

    assert os.environ["GROQ_API_KEY"] == KEY


def test_the_wizard_writes_the_cities_and_types_she_picked(fresh):
    settings, client = fresh

    client.post(
        "/setup",
        data={"env_var": "", "api_key": "", "cities": "Augsburg", "types": "werkstudent, minijob"},
    )

    written = Settings.load(project_root=settings.project_root)
    assert written.cities == ("Augsburg",)
    assert written.employment_types == ("werkstudent", "minijob")


def test_the_wizard_can_be_finished_without_a_key(fresh):
    """A search needs no key at all — only the English explanations do. Making
    a key mandatory would lock her out of the working half of the app."""
    settings, client = fresh

    client.post("/setup", data={"env_var": "", "api_key": "", "cities": "", "types": ""})

    assert (settings.project_root / "config.yaml").exists()
    assert not (settings.project_root / ".env").exists()


def test_finishing_the_wizard_lands_her_on_the_search_page(fresh):
    _settings, client = fresh

    response = client.post(
        "/setup",
        data={"env_var": "", "api_key": "", "cities": "Ingolstadt", "types": "minijob"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/search"


def test_an_unknown_city_is_refused_with_the_names_that_work(fresh):
    settings, client = fresh

    response = client.post(
        "/setup", data={"env_var": "", "api_key": "", "cities": "Atlantis", "types": "minijob"}
    )

    assert "Atlantis" in response.text
    assert "Ingolstadt" in response.text  # the list of ones that do work
    assert not (settings.project_root / "config.yaml").exists()


def test_the_static_files_are_served_during_the_wizard(fresh):
    """The redirect must not swallow the stylesheet, or the first page she ever
    sees is unstyled HTML."""
    _settings, client = fresh

    assert client.get("/static/app.css", follow_redirects=False).status_code == 200


def test_the_wizard_keeps_a_key_that_was_already_in_the_env_file(fresh):
    settings, client = fresh
    (settings.project_root / ".env").write_text("OPENROUTER_API_KEY=older\n", encoding="utf-8")

    client.post(
        "/setup",
        data={
            "env_var": "GROQ_API_KEY",
            "api_key": KEY,
            "cities": "Ingolstadt",
            "types": "minijob",
        },
    )

    env_text = (settings.project_root / ".env").read_text(encoding="utf-8")
    assert "OPENROUTER_API_KEY=older" in env_text
    assert f"GROQ_API_KEY={KEY}" in env_text
