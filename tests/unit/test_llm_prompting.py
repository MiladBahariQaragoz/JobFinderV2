"""Prompt files — one Markdown file per prompt, filename carries the version."""

from __future__ import annotations

import pytest

from jobfinder.llm.prompting import load_prompt


def test_load_prompt_returns_text_and_version():
    spec = load_prompt("roles")

    assert spec.version == "v1"
    assert spec.name == "roles"
    assert "JSON" in spec.text  # the prompt asks for structured output


def test_latest_version_wins_when_several_exist(tmp_path, monkeypatch):
    from jobfinder.llm import prompting

    (tmp_path / "roles.v1.md").write_text("one", encoding="utf-8")
    (tmp_path / "roles.v2.md").write_text("two", encoding="utf-8")
    monkeypatch.setattr(prompting, "PROMPTS_DIR", tmp_path)

    spec = load_prompt("roles")

    assert spec.version == "v2"
    assert spec.text == "two"


def test_unknown_prompt_names_valid_ones():
    with pytest.raises(ValueError) as exc:
        load_prompt("nonexistent")

    assert "nonexistent" in str(exc.value)


# --- Phase 7: the enrichment prompt ------------------------------------------


AD_TEXT = (
    "Wir suchen ab sofort eine Aushilfe für unsere Bäckereifiliale in "
    "Ingolstadt. Gute Deutschkenntnisse in Wort und Schrift sind erforderlich. "
    "Bewerbungen bitte an jobs@example.de."
)


def sample_job() -> dict:
    return {
        "job_id": "ba-4913285274",
        "title": "Aushilfe Bäckereifiliale (m/w/d)",
        "company": "Bäckerei Musterle GmbH",
        "city": "Ingolstadt",
        "employment_type_raw": "Minijob",
        "is_minijob": 1,
        "is_parttime": 0,
        "is_fulltime": 0,
        "is_internship": 0,
        "is_werkstudent": 0,
        "homeoffice": 0,
        "apply_url": "",
        "source_url": "https://example.de/ad/1",
    }


def render(**overrides) -> str:
    from jobfinder.llm.prompting import render_enrichment_prompt

    fields = {
        "job": sample_job(),
        "description": AD_TEXT,
        "cv_digest": "# Skills\n- Programming Languages: Python, MATLAB",
    }
    fields.update(overrides)
    return render_enrichment_prompt(load_prompt("enrich").text, **fields)


def test_enrichment_prompt_includes_the_full_description_and_her_cv_digest():
    prompt = render()

    assert AD_TEXT in prompt, "the ad she cannot read is the whole input"
    assert "Python, MATLAB" in prompt, "fit_score is meaningless without her CV"


def test_enrichment_prompt_never_carries_her_address_email_or_phone():
    # The digest is already stripped (test_cv_digest_excludes_address_email_and_phone);
    # this holds the line on the text that is actually sent to a provider.
    prompt = render(cv_digest="# Skills\n- Programming Languages: Python")

    for secret in ("j@example.com", "Neuburg an der Donau", "+49 172"):
        assert secret not in prompt, f"the enrichment prompt leaks {secret!r}"


def test_enrichment_prompt_states_the_job_facts_the_ad_text_may_omit():
    prompt = render()

    for fact in ("Aushilfe Bäckereifiliale (m/w/d)", "Bäckerei Musterle GmbH", "Ingolstadt"):
        assert fact in prompt


def test_enrichment_prompt_names_every_field_the_validator_demands():
    from jobfinder.llm.schema import ENRICHMENT_SPEC

    prompt = render()

    missing = sorted(name for name in ENRICHMENT_SPEC if name not in prompt)
    assert not missing, f"the prompt never asks for: {missing}"


def test_enrichment_prompt_demands_evidence_or_unclear_for_the_german_level():
    prompt = render()

    assert "unclear" in prompt
    assert "german_evidence" in prompt
