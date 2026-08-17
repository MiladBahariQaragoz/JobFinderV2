"""Her CV, put in through the browser instead of edited beside the source.

`pool.yaml` is the input to the fit score on every row and to the role
suggestions, and until now it could only be edited as a file next to the code.
Two constraints shape all of this:

- **A bad paste must never destroy the CV she already has.** The upload is
  parsed first and written second, and the file it replaces is kept.
- **Privacy is the constraint, not a footnote.** `pool.yaml` holds her name,
  address, phone and email. It stays on the laptop; only the skills-and-
  education digest ever reaches a provider (tested in Phase 3), and the page
  that confirms the upload does not put her contact details on screen.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jobfinder.config import Settings
from jobfinder.web.app import create_app

TEMPLATE = Path(__file__).resolve().parents[2] / "pool.template.yaml"

# A CV that parses: the minimum `load_profile` accepts, plus the parts the
# summary is supposed to show. Umlauts included — they ride through upload,
# YAML, and the rendered page (§5's encoding rule).
VALID_CV = """
basics:
  name: Maryam Bäcker
  headline: MSc Mechatronics
  email: maryam@example.com
  location: Neuburg an der Donau, Germany
  phone: "+49 151 23456789"
  address: Musterstraße 7, 86633 Neuburg
  languages:
    - { name: Persian, level: "Mother tongue" }
    - { name: German, level: "B1" }
    - { name: English, level: "C1" }
experience:
  - id: shop
    role: Sales Assistant
    org: Bäckerei Müller & Söhne
    start: "2024-03"
    end: "2025-06"
    bullets:
      - Served customers at the counter
education:
  - id: msc
    degree: MSc Mechatronics
    org: TH Ingolstadt
    start: "2025-10"
    end: present
skill_groups:
  Programming Languages: [Python, MATLAB]
  Tools: [Git, Linux]
"""


@pytest.fixture
def app_settings(tmp_path) -> Settings:
    return Settings(project_root=tmp_path)


@pytest.fixture
def client(app_settings) -> TestClient:
    with TestClient(create_app(app_settings)) as test_client:
        yield test_client


def upload(client: TestClient, text: str, filename: str = "pool.yaml"):
    return client.post(
        "/settings/cv",
        files={"cv": (filename, text.encode("utf-8"), "application/yaml")},
        follow_redirects=True,
    )


class TestTheTemplateDownload:
    def test_the_template_is_served_as_a_file_she_can_save(self, client):
        response = client.get("/settings/cv/template")

        assert response.status_code == 200
        assert "attachment" in response.headers["content-disposition"]
        assert "pool.template.yaml" in response.headers["content-disposition"]

    def test_the_template_download_is_the_file_in_the_repo(self, client):
        response = client.get("/settings/cv/template")

        # Byte-for-byte, line endings included: it is served as a file, not
        # re-rendered, so `read_text`'s newline translation is not the standard.
        assert response.content == TEMPLATE.read_bytes()

    def test_the_settings_page_links_to_the_template(self, client):
        assert 'href="/settings/cv/template"' in client.get("/settings").text


class TestUploadingACv:
    def test_a_valid_upload_is_written_to_pool_yaml(self, app_settings, client):
        response = upload(client, VALID_CV)

        assert response.status_code == 200
        assert app_settings.pool_path.exists()
        assert "Maryam Bäcker" in app_settings.pool_path.read_text(encoding="utf-8")

    def test_a_valid_upload_keeps_the_previous_file_as_a_backup(self, app_settings, client):
        app_settings.pool_path.write_text(VALID_CV.replace("Maryam", "Earlier"), encoding="utf-8")

        upload(client, VALID_CV)

        backup = app_settings.pool_path.with_suffix(".yaml.bak")
        assert backup.exists()
        assert "Earlier Bäcker" in backup.read_text(encoding="utf-8")

    def test_an_invalid_upload_leaves_the_existing_file_untouched(self, app_settings, client):
        app_settings.pool_path.write_text(VALID_CV, encoding="utf-8")

        response = upload(client, "basics:\n  name: ''\n")

        assert response.status_code == 200
        assert "Maryam Bäcker" in app_settings.pool_path.read_text(encoding="utf-8")

    def test_an_invalid_upload_shows_the_sentence_naming_the_field(self, client):
        response = upload(client, "basics:\n  name: Maryam\n")

        assert "basics" in response.text
        assert "email" in response.text  # the field that is missing, named
        assert "Traceback" not in response.text

    def test_an_upload_that_is_not_yaml_at_all_is_refused_readably(self, app_settings, client):
        response = upload(client, "this: is: not: valid: yaml:\n\t- broken", "cv.yaml")

        assert response.status_code == 200
        assert "Traceback" not in response.text
        assert not app_settings.pool_path.exists()

    def test_an_empty_upload_is_refused_readably(self, app_settings, client):
        response = upload(client, "")

        assert response.status_code == 200
        assert "empty" in response.text.lower()
        assert not app_settings.pool_path.exists()

    def test_a_valid_upload_survives_its_umlauts(self, app_settings, client):
        upload(client, VALID_CV)

        from jobfinder.profile import load_profile

        resume = load_profile(app_settings.pool_path)
        assert resume.basics["name"] == "Maryam Bäcker"
        assert resume.experience[0].org == "Bäckerei Müller & Söhne"


class TestWhatTheSettingsPageSays:
    def test_settings_says_no_cv_yet_and_offers_the_template(self, client):
        body = client.get("/settings").text

        assert "No CV yet" in body
        assert 'href="/settings/cv/template"' in body

    def test_settings_summarises_the_cv_it_found(self, client):
        upload(client, VALID_CV)

        body = client.get("/settings").text

        assert "Maryam Bäcker" in body  # enough to see the right file landed
        assert "German" in body and "B1" in body
        assert "Programming Languages" in body

    def test_settings_never_renders_her_address_or_phone_number(self, client):
        upload(client, VALID_CV)

        body = client.get("/settings").text

        assert "+49 151 23456789" not in body
        assert "Musterstraße 7" not in body
        assert "maryam@example.com" not in body

    def test_settings_names_the_problem_when_the_cv_will_not_parse(self, app_settings, client):
        # A file already on disk that stopped parsing — she edited it by hand,
        # or an older format. The page has to say which field, not just "error".
        app_settings.pool_path.write_text("basics:\n  name: Maryam\n", encoding="utf-8")

        body = client.get("/settings").text

        assert "email" in body
        assert "Traceback" not in body

    def test_the_unfilled_template_is_not_mistaken_for_her_cv(self, app_settings, client):
        """The template parses — it has a name, an email and a location. Saying
        "CV present" for it would put a fit score on every row computed from
        'Your Full Name', which is worse than saying nothing."""
        app_settings.pool_path.write_bytes(TEMPLATE.read_bytes())

        body = client.get("/settings").text

        assert "still the template" in body
