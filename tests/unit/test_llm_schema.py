"""Validators for LLM answers — the one project-specific hook llmpool calls.

A junk answer costs the provider no cooldown only if the validator catches it,
so the validators themselves are tested against junk: missing keys, wrong enum
values, prose instead of JSON.
"""

from __future__ import annotations

from jobfinder.llm.schema import FieldRule, make_validator, roles_answer_validator

WELL_FORMED_ROLE = {
    "title_de": "Werkstudent Datenanalyse",
    "title_en": "Working student data analysis",
    "why": "Her Python and emissions work fits.",
    "search_keywords": ["werkstudent datenanalyse", "data analysis"],
    "typical_employment_types": ["werkstudent", "parttime"],
    "german_level_typical": "B1",
    "confidence": 0.8,
}


def test_validator_accepts_a_well_formed_answer():
    ok, reason = roles_answer_validator({"roles": [WELL_FORMED_ROLE]})

    assert ok, reason


def test_validator_tolerates_unknown_keys():
    ok, reason = roles_answer_validator({"roles": [dict(WELL_FORMED_ROLE, extra="ignored")]})

    assert ok, reason


def test_validator_rejects_missing_required_key_with_named_reason():
    role = {key: value for key, value in WELL_FORMED_ROLE.items() if key != "title_de"}

    ok, reason = roles_answer_validator({"roles": [role]})

    assert not ok
    assert "title_de" in reason
    assert "role 1" in reason  # which item is broken


def test_validator_rejects_prose_masquerading_as_json():
    for not_an_object in ("Sure! Here are some roles…", ["a", "list"], 42, None):
        ok, reason = roles_answer_validator(not_an_object)

        assert not ok
        assert "JSON object" in reason


def test_validator_rejects_out_of_range_enum_value():
    ok, reason = roles_answer_validator(
        {"roles": [dict(WELL_FORMED_ROLE, german_level_typical="fluent")]}
    )

    assert not ok
    assert "german_level_typical" in reason
    assert "fluent" in reason


def test_validator_rejects_confidence_outside_zero_to_one():
    ok, _ = roles_answer_validator({"roles": [dict(WELL_FORMED_ROLE, confidence=1.5)]})
    assert not ok

    ok, _ = roles_answer_validator({"roles": [dict(WELL_FORMED_ROLE, confidence="high")]})
    assert not ok


def test_validator_rejects_wrong_employment_type():
    ok, reason = roles_answer_validator(
        {"roles": [dict(WELL_FORMED_ROLE, typical_employment_types=["full-time"])]}
    )

    assert not ok
    assert "full-time" in reason


def test_validator_rejects_empty_roles_list():
    ok, reason = roles_answer_validator({"roles": []})

    assert not ok
    assert "at least one role" in reason


def test_make_validator_composes_from_field_rules():
    validator = make_validator(
        {
            "name": FieldRule(kind="str"),
            "count": FieldRule(kind="number", min_value=0, max_value=100, required=False),
        }
    )

    assert validator({"name": "x", "count": 50})[0]
    assert validator({"name": "x"})[0]  # optional key absent is fine
    assert not validator({"name": "x", "count": 500})[0]
    assert not validator({})[0]
