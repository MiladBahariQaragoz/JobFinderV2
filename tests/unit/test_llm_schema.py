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


# --- Phase 7: the enrichment answer ------------------------------------------


def enrichment_answer(**overrides) -> dict:
    """A well-formed answer, as the model is asked to produce it."""
    answer = {
        "category": "retail",
        "seniority": "entry",
        "skills_required": ["customer service", "German A2"],
        "skills_nice": ["cash handling"],
        "german_level": "B1",
        "german_evidence": "Gute Deutschkenntnisse in Wort und Schrift",
        "english_sufficient": False,
        "employment_type_norm": "minijob",
        "hours_per_week": 10,
        "duties_en": ["Serve customers at the counter", "Refill shelves"],
        "requirements_en": ["Reliable", "Weekend availability"],
        "summary_en": "A small weekend job at a bakery counter in Ingolstadt.",
        "fit_score": 62,
        "fit_reasons": ["Her retail experience matches"],
        "missing_for_fit": ["Stronger spoken German"],
        "red_flags": [],
        "application_method": "email",
        "contact_email": "jobs@example.de",
        "contact_phone": "",
        "deadline": "",
    }
    answer.update(overrides)
    return answer


def check(answer) -> tuple[bool, str]:
    from jobfinder.llm.schema import enrichment_answer_validator

    return enrichment_answer_validator(answer)


class TestEnrichmentContract:
    def test_a_well_formed_answer_is_accepted(self):
        assert check(enrichment_answer())[0] is True

    def test_a_missing_key_is_named(self):
        answer = enrichment_answer()
        del answer["summary_en"]
        ok, reason = check(answer)
        assert ok is False
        assert "summary_en" in reason

    def test_a_german_level_outside_the_enum_is_rejected(self):
        ok, reason = check(enrichment_answer(german_level="fluent"))
        assert ok is False
        assert "fluent" in reason

    def test_a_german_level_without_evidence_is_rejected(self):
        # §5: the level must be backed by the phrase in the ad that justifies
        # it. A third of her store is teaser-only, so the temptation to guess
        # is the danger this rule exists for.
        ok, reason = check(enrichment_answer(german_evidence=""))
        assert ok is False
        assert "german_evidence" in reason

    def test_unclear_is_the_honest_answer_and_needs_no_evidence(self):
        assert check(enrichment_answer(german_level="unclear", german_evidence=""))[0] is True

    def test_an_answer_written_in_german_is_rejected(self):
        ok, reason = check(
            enrichment_answer(
                summary_en=(
                    "Eine kleine Aushilfe an der Theke einer Bäckerei, und die "
                    "Arbeitszeiten sind am Wochenende mit flexiblen Schichten."
                )
            )
        )
        assert ok is False
        assert "English" in reason

    def test_a_german_job_title_inside_an_english_sentence_is_fine(self):
        # She needs the German words that name things — Werkstudent, Minijob —
        # and a language check that forbade them would be useless.
        assert (
            check(
                enrichment_answer(
                    summary_en="A Werkstudent role at Bäckerei Müller, paid as a Minijob."
                )
            )[0]
            is True
        )

    def test_a_fit_score_outside_zero_to_a_hundred_is_rejected(self):
        assert check(enrichment_answer(fit_score=140))[0] is False
        assert check(enrichment_answer(fit_score=-1))[0] is False

    def test_a_list_field_sent_as_a_string_is_rejected(self):
        ok, reason = check(enrichment_answer(duties_en="Serve customers"))
        assert ok is False
        assert "duties_en" in reason

    def test_english_sufficient_must_be_a_boolean(self):
        ok, reason = check(enrichment_answer(english_sufficient="maybe"))
        assert ok is False
        assert "english_sufficient" in reason

    def test_an_empty_red_flags_list_is_allowed(self):
        assert check(enrichment_answer(red_flags=[]))[0] is True

    def test_prose_instead_of_an_object_is_rejected(self):
        assert check("Here is the enrichment you asked for")[0] is False
