"""Role suggestions — CV digest in, German job titles worth searching out."""

from __future__ import annotations

import json

import pytest
from tests.fakes import FakePool

from jobfinder.config import Settings
from jobfinder.llm.schema import roles_answer_validator
from jobfinder.profile import Education, Experience, Resume
from jobfinder.roles import Role, RolesError, build_cv_digest, suggest_roles


def sample_resume() -> Resume:
    return Resume(
        basics={
            "name": "Jane Doe",
            "email": "j@example.com",
            "location": "Neuburg an der Donau, Germany",
            "phone": "+49 172 0000000",
        },
        languages=(),
        experience=(),
        education=(),
        skill_groups={"Programming Languages": ("Python", "MATLAB", "C")},
    )


WELL_FORMED_ANSWER = {
    "roles": [
        {
            "title_de": "Werkstudent Datenanalyse",
            "title_en": "Working student, data analysis",
            "why": "Her Python and emissions work fits.",
            "search_keywords": ["Werkstudent Datenanalyse", "datenanalyse"],
            "typical_employment_types": ["werkstudent", "parttime"],
            "german_level_typical": "B1",
            "confidence": 0.8,
        }
    ]
}


def test_cv_digest_excludes_address_email_and_phone():
    digest = build_cv_digest(sample_resume())

    for secret in ("j@example.com", "Neuburg", "+49", "Jane Doe"):
        assert secret not in digest, f"digest leaks {secret!r}"


def test_cv_digest_includes_skill_groups_and_education_level():
    resume = Resume(
        basics={},
        education=(),
        experience=(),
        projects=(),
        skill_groups={"Sustainability & Environment": ("LCA", "Circular Economy")},
    )

    digest = build_cv_digest(resume)

    assert "LCA" in digest
    assert "Circular Economy" in digest


def test_cv_digest_includes_education_and_experience():
    resume = Resume(
        basics={},
        education=(
            Education(
                org="TH Ingolstadt",
                degree="M.Sc. Sustainability Management and Technology",
                start="2025-10",
                end="present",
            ),
        ),
        experience=(
            Experience(
                id="medemic",
                role="Environmental Engineering Consultant",
                org="Medemic",
                start="2023-10",
                end="2024-09",
                skills=("Shell Scripting",),
            ),
        ),
        skill_groups={},
    )

    digest = build_cv_digest(resume)

    assert "M.Sc. Sustainability Management and Technology" in digest
    assert "Environmental Engineering Consultant" in digest
    assert "Shell Scripting" in digest


def test_role_without_german_title_is_rejected_by_the_validator():
    complete = WELL_FORMED_ANSWER["roles"][0]
    broken = {"roles": [{k: v for k, v in complete.items() if k != "title_de"}]}

    ok, reason = roles_answer_validator(broken)

    assert not ok
    assert "title_de" in reason


def test_roles_parsed_from_fake_answer_into_objects(tmp_path):
    settings = Settings.load(tmp_path)
    pool = FakePool([WELL_FORMED_ANSWER])

    roles, fresh = suggest_roles(settings, sample_resume(), pool)

    assert fresh
    assert isinstance(roles[0], Role)
    assert roles[0].title_de == "Werkstudent Datenanalyse"
    assert roles[0].confidence == 0.8
    # stored for the next run and for Phase 4's search presets
    stored = json.loads(settings.suggested_roles_path.read_text(encoding="utf-8"))
    assert stored["prompt_version"] == "v1"
    assert stored["roles"][0]["title_de"] == "Werkstudent Datenanalyse"
    assert stored["roles"][0]["search_keywords"] == list(roles[0].search_keywords)
    assert stored["roles"][0]["confidence"] == 0.8


def test_search_keywords_are_deduplicated_and_lowercased(tmp_path):
    settings = Settings.load(tmp_path)
    answer = json.loads(json.dumps(WELL_FORMED_ANSWER))
    answer["roles"][0]["search_keywords"] = [
        "Datenanalyse",
        "datenanalyse",
        " WERKSTUDENT Datenanalyse ",
    ]
    pool = FakePool([answer])

    roles, _ = suggest_roles(settings, sample_resume(), pool)

    assert roles[0].search_keywords == ("datenanalyse", "werkstudent datenanalyse")


def test_suggestions_are_cached_and_second_run_makes_no_call(tmp_path):
    settings = Settings.load(tmp_path)
    pool = FakePool([WELL_FORMED_ANSWER])

    suggest_roles(settings, sample_resume(), pool)
    assert len(pool.calls) == 1

    roles, fresh = suggest_roles(settings, sample_resume(), pool)
    assert not fresh and len(pool.calls) == 1  # stored suggestions, no provider call

    # even with the stored file gone, the LLM cache answers without the pool
    settings.suggested_roles_path.unlink()
    roles, fresh = suggest_roles(settings, sample_resume(), pool)
    assert len(pool.calls) == 1
    assert not fresh
    assert settings.suggested_roles_path.exists()  # re-stored from the cache
    assert roles[0].title_de == "Werkstudent Datenanalyse"


def test_empty_cv_produces_a_helpful_message_not_an_empty_table(tmp_path):
    settings = Settings.load(tmp_path)
    pool = FakePool([])  # would raise AssertionError if ever called

    with pytest.raises(RolesError) as exc:
        suggest_roles(settings, Resume(basics={}), pool)

    assert "skills" in str(exc.value)
    assert len(pool.calls) == 0
