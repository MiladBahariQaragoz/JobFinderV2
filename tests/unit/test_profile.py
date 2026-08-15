"""pool.yaml parsing — every failure must be one sentence a non-programmer can act on."""

from __future__ import annotations

from pathlib import Path

import pytest

from jobfinder.profile import (
    ProfileError,
    load_profile,
    normalize_language_level,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATE = PROJECT_ROOT / "pool.template.yaml"


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "pool.yaml"
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def test_parses_the_blank_template_without_crashing():
    resume = load_profile(TEMPLATE)

    assert resume.basics["name"]
    assert resume.skill_groups  # template ships example groups
    assert resume.languages


def test_missing_basics_section_is_named_with_a_fix(tmp_path):
    with pytest.raises(ProfileError) as exc:
        load_profile(write(tmp_path, "experience: []"))

    assert "basics" in str(exc.value)
    assert "pool.template.yaml" in str(exc.value)


def test_missing_required_basics_names_the_field_and_the_line(tmp_path):
    # 'basics:' deliberately on line 3 so the assertion is about position, not luck
    text = (
        "# a comment\n# another comment\nbasics:\n  name: Jane Doe\n  location: Munich, Germany\n"
    )
    with pytest.raises(ProfileError) as exc:
        load_profile(write(tmp_path, text))

    message = str(exc.value)
    assert "email" in message
    assert "line 3" in message


def test_language_levels_parse_including_mother_tongue(tmp_path):
    text = (
        "basics:\n"
        "  name: Jane Doe\n"
        "  email: j@example.com\n"
        "  location: Munich, Germany\n"
        "languages:\n"
        "  - { name: Persian, level: Mother tongue }\n"
        "  - { name: English, level: Fluent }\n"
        "  - { name: German, level: Basic }\n"
        "  - { name: French, level: B1 }\n"
    )
    resume = load_profile(write(tmp_path, text))

    normalized = {lang.name: lang.normalized for lang in resume.languages}
    assert normalized == {
        "Persian": "C2",
        "English": "C1",
        "German": "A2",
        "French": "B1",
    }


def test_experience_dates_accept_yyyy_mm_and_present(tmp_path):
    text = (
        "basics:\n"
        "  name: Jane Doe\n"
        "  email: j@example.com\n"
        "  location: Munich, Germany\n"
        "experience:\n"
        "  - id: current-job\n"
        "    role: PPC Expert\n"
        "    org: Airline\n"
        "    start: 2024-10\n"
        "    end: present\n"
        "  - id: old-job\n"
        "    role: Consultant\n"
        "    org: Startup\n"
        "    start: 2023-10\n"
        "    end: 2024-09\n"
    )
    resume = load_profile(write(tmp_path, text))

    current, old = resume.experience
    assert current.start_date == (2024, 10)
    assert current.end == "present"
    assert old.start_date == (2023, 10)
    assert old.end_date == (2024, 9)


def test_invalid_date_reports_the_entry_id_not_a_stack_trace(tmp_path):
    text = (
        "basics:\n"
        "  name: Jane Doe\n"
        "  email: j@example.com\n"
        "  location: Munich, Germany\n"
        "experience:\n"
        "  - id: bad-job\n"
        "    role: PPC Expert\n"
        "    org: Airline\n"
        "    start: 2024-13\n"
        "    end: present\n"
    )
    with pytest.raises(ProfileError) as exc:
        load_profile(write(tmp_path, text))

    message = str(exc.value)
    assert "bad-job" in message
    assert "2024-13" in message
    assert "YYYY-MM" in message


def test_years_of_experience_spans_earliest_start_to_latest_end(tmp_path):
    text = (
        "basics:\n"
        "  name: Jane Doe\n"
        "  email: j@example.com\n"
        "  location: Munich, Germany\n"
        "experience:\n"
        "  - id: a\n"
        "    role: One\n"
        "    org: O\n"
        "    start: 2022-06\n"
        "    end: 2023-06\n"
        "  - id: b\n"
        "    role: Two\n"
        "    org: O\n"
        "    start: 2024-01\n"
        "    end: 2024-07\n"
    )
    resume = load_profile(write(tmp_path, text))

    assert resume.years_of_experience() == pytest.approx(2.1, abs=0.05)


def test_missing_file_says_how_to_start(tmp_path):
    with pytest.raises(ProfileError) as exc:
        load_profile(tmp_path / "nowhere.yaml")

    assert "pool.template.yaml" in str(exc.value)


def test_normalize_language_level_passes_cefr_through():
    for level in ("A1", "A2", "B1", "B2", "C1", "C2"):
        assert normalize_language_level(level) == level
