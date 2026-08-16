"""A validated answer becomes one `jobs-enriched.csv` row. Pure mapping, no I/O.

§5 fixes the column order and two rules that a CSV round trip would otherwise
break: list fields are pipe-separated because her skills and duties contain
commas, and an absent field is an empty cell — never the string "None", which
she would read as a value.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# §5's `jobs-enriched.csv` line, in order. The first four are ours (which job,
# when, which prompt, who answered); the rest come from the model.
ENRICHED_COLUMNS = [
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

# Everything the model returns as a list. Joined with a pipe (§5).
LIST_FIELDS = frozenset(
    {
        "skills_required",
        "skills_nice",
        "duties_en",
        "requirements_en",
        "fit_reasons",
        "missing_for_fit",
        "red_flags",
    }
)

# The columns this module supplies rather than reads out of the answer.
_OURS = ("job_id", "enriched_at", "prompt_version", "provider_used")

SEPARATOR = "|"
# A pipe inside one item would read back as two items. Replacing it costs one
# punctuation mark; keeping it costs her a duty that never existed.
_SEPARATOR_REPLACEMENT = "/"


def enriched_row(
    answer: Mapping[str, Any],
    *,
    job_id: str,
    prompt_version: str,
    provider_used: str = "",
    enriched_at: str,
) -> list[Any]:
    """One row of `jobs-enriched.csv`, in `ENRICHED_COLUMNS` order."""
    ours = {
        "job_id": job_id,
        "enriched_at": enriched_at,
        "prompt_version": prompt_version,
        "provider_used": provider_used,
    }
    return [
        ours[column] if column in _OURS else _cell(column, answer.get(column))
        for column in ENRICHED_COLUMNS
    ]


def _cell(column: str, value: Any) -> Any:
    """One value in the shape a spreadsheet should show it."""
    if value is None:
        return ""
    if column in LIST_FIELDS:
        return _join(value)
    if isinstance(value, bool):
        # "True"/"False" is a Python repr; she reads this file in Excel.
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return value  # stays numeric so a spreadsheet can sort and filter it
    return str(value)


def _join(value: Any) -> str:
    """Pipe-join a list; a stray string is passed through rather than exploded."""
    if isinstance(value, str):
        return value
    if not isinstance(value, (list, tuple)):
        return str(value)
    return SEPARATOR.join(
        str(item).replace(SEPARATOR, _SEPARATOR_REPLACEMENT).strip() for item in value
    )
