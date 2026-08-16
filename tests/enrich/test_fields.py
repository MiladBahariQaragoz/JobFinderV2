"""An enrichment answer becomes one `jobs-enriched.csv` row — §5's columns, in order.

Pure mapping, no I/O. The rules that matter here are the ones a CSV round trip
would otherwise break: list fields are pipe-separated (§5 — never commas, her
skills contain commas), and a field the model left out becomes an empty cell,
never the string "None".
"""

from __future__ import annotations

import csv
import io

from jobfinder.enrich.fields import ENRICHED_COLUMNS, enriched_row

ANSWER = {
    "category": "retail",
    "seniority": "entry",
    "skills_required": ["customer service", "cash handling"],
    "skills_nice": ["barista experience"],
    "german_level": "B1",
    "german_evidence": "Gute Deutschkenntnisse in Wort und Schrift",
    "english_sufficient": False,
    "employment_type_norm": "minijob",
    "hours_per_week": 10,
    "duties_en": ["Serve customers at the counter", "Refill the shelves"],
    "requirements_en": ["Reliable", "Available on Saturdays"],
    "summary_en": "A weekend job at a bakery counter in Ingolstadt.",
    "fit_score": 62,
    "fit_reasons": ["Her retail experience matches"],
    "missing_for_fit": ["Stronger spoken German"],
    "red_flags": [],
    "application_method": "email",
    "contact_email": "jobs@example.de",
    "contact_phone": "",
    "deadline": "",
}


def row(answer=None, **overrides):
    fields = {
        "job_id": "ba-4913285274",
        "prompt_version": "v1",
        "provider_used": "groq/llama-3.3-70b",
        "enriched_at": "2026-08-16 09:30:00",
    }
    fields.update(overrides)
    return enriched_row(answer if answer is not None else ANSWER, **fields)


def as_dict(values) -> dict:
    return dict(zip(ENRICHED_COLUMNS, values, strict=True))


def test_the_column_order_is_the_contract_in_section_five():
    assert ENRICHED_COLUMNS == [
        "job_id",
        "enriched_at",
        "prompt_version",
        "provider_used",
        "category",
        "seniority",
        "skills_required",
        "skills_nice",
        "german_level",
        "german_evidence",
        "english_sufficient",
        "employment_type_norm",
        "hours_per_week",
        "duties_en",
        "requirements_en",
        "summary_en",
        "fit_score",
        "fit_reasons",
        "missing_for_fit",
        "red_flags",
        "application_method",
        "contact_email",
        "contact_phone",
        "deadline",
    ]


def test_fake_answer_maps_onto_every_enriched_csv_column():
    values = as_dict(row())

    assert values["job_id"] == "ba-4913285274"
    assert values["enriched_at"] == "2026-08-16 09:30:00"
    assert values["prompt_version"] == "v1"
    assert values["provider_used"] == "groq/llama-3.3-70b"
    assert values["category"] == "retail"
    assert values["german_level"] == "B1"
    assert values["german_evidence"] == "Gute Deutschkenntnisse in Wort und Schrift"
    assert values["summary_en"] == "A weekend job at a bakery counter in Ingolstadt."
    assert values["fit_score"] == 62
    assert values["application_method"] == "email"
    assert values["contact_email"] == "jobs@example.de"


def test_list_fields_are_pipe_separated_never_comma_separated():
    values = as_dict(row())

    assert values["skills_required"] == "customer service|cash handling"
    assert values["duties_en"] == "Serve customers at the counter|Refill the shelves"


def test_pipe_separated_list_fields_survive_a_csv_round_trip():
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(ENRICHED_COLUMNS)
    writer.writerow(row())

    buffer.seek(0)
    read_back = list(csv.DictReader(buffer))[0]

    assert read_back["skills_required"].split("|") == ["customer service", "cash handling"]
    assert read_back["duties_en"].split("|") == [
        "Serve customers at the counter",
        "Refill the shelves",
    ]


def test_an_empty_list_becomes_an_empty_cell():
    assert as_dict(row())["red_flags"] == ""


def test_a_missing_optional_field_becomes_empty_not_the_string_none():
    answer = {key: value for key, value in ANSWER.items() if key != "hours_per_week"}
    answer.pop("deadline")

    values = as_dict(row(answer))

    assert values["hours_per_week"] == ""
    assert values["deadline"] == ""
    assert "None" not in [str(value) for value in values.values()]


def test_a_boolean_is_written_as_true_or_false_not_as_a_python_repr():
    assert as_dict(row())["english_sufficient"] == "false"
    assert as_dict(row(dict(ANSWER, english_sufficient=True)))["english_sufficient"] == "true"


def test_a_list_field_sent_as_a_string_is_still_written_readably():
    # The validator rejects this shape, but a cached answer from an older run
    # must not crash the export it lands in.
    values = as_dict(row(dict(ANSWER, skills_required="customer service")))

    assert values["skills_required"] == "customer service"


def test_a_pipe_inside_a_list_item_does_not_invent_a_second_item():
    # The separator has to survive the data. One duty containing a pipe would
    # otherwise read back as two duties on her screen.
    values = as_dict(row(dict(ANSWER, duties_en=["Serve customers | clean up", "Close the till"])))

    assert values["duties_en"].split("|") == ["Serve customers / clean up", "Close the till"]
