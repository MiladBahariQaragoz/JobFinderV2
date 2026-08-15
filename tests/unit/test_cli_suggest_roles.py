"""`jobfinder suggest-roles` — a table she can read, cached answers she doesn't pay for."""

from __future__ import annotations

import json

from jobfinder.cli import main

STORED = {
    "prompt_version": "v1",
    "created_at": "2026-08-15T10:00:00+00:00",
    "roles": [
        {
            "title_de": "Werkstudent Datenanalyse",
            "title_en": "Working student, data analysis",
            "why": "Her Python and emissions work fits.",
            "search_keywords": ["werkstudent datenanalyse", "datenanalyse"],
            "typical_employment_types": ["werkstudent", "parttime"],
            "german_level_typical": "B1",
            "confidence": 0.8,
        },
        {
            "title_de": "Umweltingenieur:in",
            "title_en": "Environmental engineer",
            "why": "Direct use of her degree.",
            "search_keywords": ["umweltingenieur"],
            "typical_employment_types": ["fulltime"],
            "german_level_typical": "B2",
            "confidence": 0.6,
        },
    ],
}


def seed(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "suggested_roles.json").write_text(json.dumps(STORED), encoding="utf-8", newline="\n")
    return tmp_path


def failing_pool_factory(settings):
    raise AssertionError("the pool must not be built when stored suggestions exist")


def test_suggest_roles_cli_renders_a_table_from_stored_suggestions(tmp_path, capsys):
    root = seed(tmp_path)

    exit_code = main(["suggest-roles", "--root", str(root)], _pool_factory=failing_pool_factory)

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Werkstudent Datenanalyse" in out
    assert "Working student, data analysis" in out
    assert "B1" in out
    assert "werkstudent datenanalyse" in out
    assert "cached" in out  # says where the answer came from


def test_suggest_roles_top_n_limits_the_table(tmp_path, capsys):
    root = seed(tmp_path)

    exit_code = main(
        ["suggest-roles", "--root", str(root), "--top", "1"],
        _pool_factory=failing_pool_factory,
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Werkstudent Datenanalyse" in out
    assert "Umweltingenieur" not in out


def test_suggest_roles_json_prints_parseable_json(tmp_path, capsys):
    root = seed(tmp_path)

    exit_code = main(
        ["suggest-roles", "--root", str(root), "--json"],
        _pool_factory=failing_pool_factory,
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload[0]["title_de"] == "Werkstudent Datenanalyse"
