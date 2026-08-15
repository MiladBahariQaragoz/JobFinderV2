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
