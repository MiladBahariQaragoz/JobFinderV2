"""Role suggestions, asked for from the browser.

`jobfinder suggest-roles` has existed since Phase 3 and she has never run it,
because running it means a terminal. The point of putting it on the Settings
page is not the titles themselves — it is that each one carries the German
keywords worth searching for, and those belong in the search form, one click
away.

The cheap path comes first everywhere: stored suggestions answer without a CV,
without a key, and without spending a call.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from tests.fakes import FakePool
from tests.web.test_cv_settings import VALID_CV

from jobfinder.config import Settings
from jobfinder.web.app import create_app

ROLES_ANSWER = {
    "roles": [
        {
            "title_de": "Werkstudent Datenanalyse",
            "title_en": "Working student, data analysis",
            "why": "Her Python and MATLAB work matches entry-level analysis roles.",
            "search_keywords": ["Werkstudent Datenanalyse", "Werkstudent Python"],
            "typical_employment_types": ["werkstudent"],
            "german_level_typical": "B1",
            "confidence": 0.8,
        },
        {
            "title_de": "Aushilfe Verkauf",
            "title_en": "Sales assistant",
            "why": "Her counter experience transfers directly.",
            "search_keywords": ["Aushilfe Verkauf", "Verkäuferin Minijob"],
            "typical_employment_types": ["minijob"],
            "german_level_typical": "A2",
            "confidence": 0.7,
        },
    ]
}


@pytest.fixture
def app_settings(tmp_path) -> Settings:
    return Settings(project_root=tmp_path)


def client_for(settings: Settings, pool=None) -> TestClient:
    app = create_app(settings, roles_pool_factory=(lambda: pool) if pool is not None else None)
    return TestClient(app)


def with_cv(settings: Settings) -> Settings:
    settings.pool_path.write_text(VALID_CV, encoding="utf-8")
    return settings


class TestAskingForSuggestions:
    def test_the_button_appears_once_a_cv_is_present(self, app_settings):
        with client_for(app_settings) as client:
            assert "Suggest roles" not in client.get("/settings").text

        with_cv(app_settings)
        with client_for(app_settings) as client:
            assert "Suggest roles" in client.get("/settings").text

    def test_asking_stores_and_renders_the_titles(self, app_settings):
        with_cv(app_settings)
        pool = FakePool([ROLES_ANSWER])

        with client_for(app_settings, pool) as client:
            body = client.post("/settings/roles", follow_redirects=True).text

        assert "Werkstudent Datenanalyse" in body
        assert "Working student, data analysis" in body  # the English gloss too
        assert app_settings.suggested_roles_path.exists()

    def test_stored_suggestions_are_shown_without_spending_a_call(self, app_settings):
        with_cv(app_settings)
        pool = FakePool([ROLES_ANSWER])
        with client_for(app_settings, pool) as client:
            client.post("/settings/roles", follow_redirects=True)
            assert len(pool.calls) == 1

            body = client.get("/settings").text

        assert "Werkstudent Datenanalyse" in body
        assert len(pool.calls) == 1  # the page itself asked nothing

    def test_a_suggested_role_links_into_the_search_form_as_a_keyword(self, app_settings):
        with_cv(app_settings)
        with client_for(app_settings, FakePool([ROLES_ANSWER])) as client:
            body = client.post("/settings/roles", follow_redirects=True).text

        assert "/search?keywords=Werkstudent+Datenanalyse" in body

    def test_the_keywords_reach_the_search_form_when_that_link_is_followed(self, app_settings):
        with client_for(app_settings) as client:
            body = client.get("/search?keywords=Aushilfe+Verkauf").text

        assert 'value="Aushilfe Verkauf"' in body


class TestWhenItCannotRun:
    def test_asking_without_a_cv_says_so_and_does_not_500(self, app_settings):
        with client_for(app_settings, FakePool([ROLES_ANSWER])) as client:
            response = client.post("/settings/roles", follow_redirects=True)

        assert response.status_code == 200
        assert "No CV" in response.text or "no CV" in response.text
        assert "Traceback" not in response.text

    def test_asking_without_a_key_refuses_with_a_sentence_not_a_500(
        self, app_settings, monkeypatch
    ):
        import llmpool

        with_cv(app_settings)
        for _name, env_var, _url in llmpool.missing_keys(llmpool.load_catalog(), env={}):
            monkeypatch.delenv(env_var, raising=False)

        with client_for(app_settings) as client:  # no injected pool: the real factory refuses
            response = client.post("/settings/roles", follow_redirects=True)

        assert response.status_code == 200
        assert "key" in response.text
        assert "Traceback" not in response.text

    def test_an_unusable_answer_says_to_try_again_rather_than_storing_it(self, app_settings):
        with_cv(app_settings)
        pool = FakePool([{"roles": [{"title_de": "", "why": ""}]}])

        with client_for(app_settings, pool) as client:
            response = client.post("/settings/roles", follow_redirects=True)

        assert response.status_code == 200
        assert "Traceback" not in response.text
        assert not app_settings.suggested_roles_path.exists()

    def test_a_cv_with_no_skills_at_all_is_refused_before_a_call_is_made(self, app_settings):
        app_settings.pool_path.write_text(
            "basics:\n  name: Maryam\n  email: m@example.com\n  location: Neuburg\n",
            encoding="utf-8",
        )
        pool = FakePool([ROLES_ANSWER])

        with client_for(app_settings, pool) as client:
            response = client.post("/settings/roles", follow_redirects=True)

        assert response.status_code == 200
        assert pool.calls == []  # nothing was sent
        assert "Traceback" not in response.text


class TestWhatIsStored:
    def test_the_stored_file_is_the_one_the_cli_reads(self, app_settings):
        with_cv(app_settings)
        with client_for(app_settings, FakePool([ROLES_ANSWER])) as client:
            client.post("/settings/roles", follow_redirects=True)

        from jobfinder.roles import stored_suggestions

        roles = stored_suggestions(app_settings)
        assert [role.title_de for role in roles] == [
            "Werkstudent Datenanalyse",
            "Aushilfe Verkauf",
        ]
        stored = json.loads(app_settings.suggested_roles_path.read_text(encoding="utf-8"))
        assert "roles" in stored
