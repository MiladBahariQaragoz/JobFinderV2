"""`jobfinder profile validate` / `show` — readable output, actionable failures."""

from __future__ import annotations

from pathlib import Path

from jobfinder.cli import main
from jobfinder.config import Settings

VALID_YAML = """\
basics:
  name: Jane Doe
  email: j@example.com
  location: Neuburg an der Donau
  languages:
    - { name: English, level: Fluent }
    - { name: German, level: Basic }
experience:
  - id: consultant
    role: Environmental Consultant
    org: Medemic
    start: 2023-10
    end: 2024-09
skill_groups:
  Small Group:
    items: [One]
  Programming Languages:
    items: [Python, MATLAB, C]
  Engineering Tools:
    items: [SOLIDWORKS, COMSOL, LaTeX]
  Sustainability:
    items: [LCA, Circular Economy, Emissions Accounting]
"""


def write_valid(tmp_path: Path) -> Path:
    path = tmp_path / "pool.yaml"
    path.write_text(VALID_YAML, encoding="utf-8", newline="\n")
    return path


def test_profile_validate_prints_green_summary(tmp_path, capsys):
    exit_code = main(["profile", "validate", "--path", str(write_valid(tmp_path))])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Jane Doe" in out
    assert "English" in out and "German" in out
    # the three largest skill groups, not the first three listed
    assert "Programming Languages" in out
    assert "Engineering Tools" in out
    assert "Sustainability" in out
    assert "Small Group" not in out
    assert "years" in out


def test_profile_validate_failure_is_one_sentence_and_exit_1(tmp_path, capsys):
    path = tmp_path / "pool.yaml"
    path.write_text("basics:\n  name: Jane Doe\n", encoding="utf-8", newline="\n")

    exit_code = main(["profile", "validate", "--path", str(path)])

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "email" in out
    assert len(out.strip().splitlines()) == 1  # one sentence, not a stack trace
    assert "Traceback" not in out


def test_profile_show_lists_experience_education_and_skills(tmp_path, capsys):
    exit_code = main(["profile", "show", "--path", str(write_valid(tmp_path))])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Environmental Consultant" in out
    assert "Medemic" in out
    assert "SOLIDWORKS" in out
    assert "j@example.com" in out


def test_settings_points_at_pool_yaml_next_to_the_project_root(tmp_path):
    settings = Settings.load(tmp_path)

    assert settings.pool_path == tmp_path / "pool.yaml"
