"""Expected JSON shapes per prompt, and the validators llmpool calls.

The validator is the one project-specific hook the pool has: ``(answer) ->
(ok, reason)``. Unknown keys are tolerated — models add harmless extras — but a
missing or invalid key is rejected with a reason naming it, so the pool can ask
a different provider instead of storing junk.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from jobfinder.search_spec import EMPLOYMENT_TYPES, GERMAN_LEVELS

Validator = Callable[[Any], tuple[bool, str]]


@dataclass(frozen=True)
class FieldRule:
    """How one key of an answer object must look."""

    kind: str = "str"  # "str" | "number" | "list" | "objects"
    enum: tuple[str, ...] = ()
    min_value: float | None = None
    max_value: float | None = None
    item_enum: tuple[str, ...] = ()
    item_spec: dict[str, FieldRule] = field(default_factory=dict)
    item_label: str = "item"
    required: bool = True
    allow_empty: bool = False


def make_validator(spec: dict[str, FieldRule], *, where: str = "answer") -> Validator:
    """Compose field rules into one llmpool-compatible validator."""

    def check_object(obj: Any, spec: dict[str, FieldRule], location: str) -> str | None:
        if not isinstance(obj, dict):
            return f"{location} is not a JSON object"
        for name, rule in spec.items():
            if name not in obj:
                if rule.required:
                    return f"{location} is missing required key '{name}'"
                continue
            problem = _check_value(obj[name], rule, f"{location} key '{name}'")
            if problem:
                return problem
        return None

    def _check_value(value: Any, rule: FieldRule, location: str) -> str | None:
        if rule.kind == "str":
            if not isinstance(value, str):
                return f"{location} must be a string"
            if not value.strip() and not rule.allow_empty:
                return f"{location} must be a non-empty string"
            if rule.enum and value not in rule.enum:
                return f"{location} is '{value}', which is not one of: {', '.join(rule.enum)}"
        elif rule.kind == "number":
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return f"{location} must be a number"
            if rule.min_value is not None and value < rule.min_value:
                return f"{location} is {value}, below the minimum {rule.min_value}"
            if rule.max_value is not None and value > rule.max_value:
                return f"{location} is {value}, above the maximum {rule.max_value}"
        elif rule.kind == "bool":
            if not isinstance(value, bool):
                return f"{location} must be true or false, not {value!r}"
        elif rule.kind == "list":
            if not isinstance(value, list):
                return f"{location} must be a list"
            if not value and not rule.allow_empty:
                return f"{location} must not be empty"
            if rule.item_enum:
                for item in value:
                    if item not in rule.item_enum:
                        return (
                            f"{location} contains '{item}', which is not one of: "
                            f"{', '.join(rule.item_enum)}"
                        )
        elif rule.kind == "objects":
            if not isinstance(value, list):
                return f"{location} must be a list of objects"
            if not value and not rule.allow_empty:
                return f"{location} must contain at least one {rule.item_label}"
            for index, item in enumerate(value, start=1):
                problem = check_object(
                    item, rule.item_spec, f"{location} {rule.item_label} {index}"
                )
                if problem:
                    return problem
        return None

    def validator(answer: Any) -> tuple[bool, str]:
        problem = check_object(answer, spec, where)
        if problem:
            return False, problem
        return True, "ok"

    return validator


# --- The answer shapes this project expects ---------------------------------

ROLE_SPEC: dict[str, FieldRule] = {
    "title_de": FieldRule(kind="str"),
    "title_en": FieldRule(kind="str"),
    "why": FieldRule(kind="str"),
    "search_keywords": FieldRule(kind="list"),
    "typical_employment_types": FieldRule(kind="list", item_enum=EMPLOYMENT_TYPES),
    "german_level_typical": FieldRule(kind="str", enum=GERMAN_LEVELS),
    "confidence": FieldRule(kind="number", min_value=0.0, max_value=1.0),
}

ROLES_SPEC: dict[str, FieldRule] = {
    "roles": FieldRule(kind="objects", item_spec=ROLE_SPEC, item_label="role"),
}

roles_answer_validator: Validator = make_validator(ROLES_SPEC)


# --- The enrichment answer (Phase 7) ----------------------------------------

# §5's list plus the one value the others cannot express. A third of her store
# is teaser-length, and "unclear" is the honest answer for those.
ANSWER_GERMAN_LEVELS = (*GERMAN_LEVELS, "unclear")
ANSWER_EMPLOYMENT_TYPES = (*EMPLOYMENT_TYPES, "unclear")

ENRICHMENT_SPEC: dict[str, FieldRule] = {
    "category": FieldRule(kind="str"),
    "seniority": FieldRule(kind="str"),
    "skills_required": FieldRule(kind="list", allow_empty=True),
    "skills_nice": FieldRule(kind="list", allow_empty=True),
    "german_level": FieldRule(kind="str", enum=ANSWER_GERMAN_LEVELS),
    # Empty is allowed here and forbidden by the cross-field rule below, which
    # can see the level this evidence is supposed to justify.
    "german_evidence": FieldRule(kind="str", required=True, allow_empty=True),
    "english_sufficient": FieldRule(kind="bool"),
    "employment_type_norm": FieldRule(kind="str", enum=ANSWER_EMPLOYMENT_TYPES),
    "hours_per_week": FieldRule(kind="number", min_value=0, max_value=80, required=False),
    "duties_en": FieldRule(kind="list", allow_empty=True),
    "requirements_en": FieldRule(kind="list", allow_empty=True),
    "summary_en": FieldRule(kind="str"),
    "fit_score": FieldRule(kind="number", min_value=0, max_value=100),
    "fit_reasons": FieldRule(kind="list", allow_empty=True),
    "missing_for_fit": FieldRule(kind="list", allow_empty=True),
    "red_flags": FieldRule(kind="list", allow_empty=True),
    "application_method": FieldRule(kind="str"),
    "contact_email": FieldRule(kind="str", required=False, allow_empty=True),
    "contact_phone": FieldRule(kind="str", required=False, allow_empty=True),
    "deadline": FieldRule(kind="str", required=False, allow_empty=True),
}

_ENRICHMENT_FIELDS = make_validator(ENRICHMENT_SPEC, where="enrichment answer")

# The English fields she actually reads. If these come back in German the
# product has failed at the one job it exists for.
ENGLISH_FIELDS = ("summary_en", "duties_en", "requirements_en", "fit_reasons")

# German function words that stay German. A job title in an English sentence
# ("a Werkstudent role, paid as a Minijob") must pass, so one marker proves
# nothing — three of them means the sentence itself is German.
_GERMAN_MARKERS = (
    "und",
    "oder",
    "der",
    "die",
    "das",
    "den",
    "dem",
    "ein",
    "eine",
    "einen",
    "für",
    "mit",
    "nicht",
    "sind",
    "wir",
    "sie",
    "ist",
    "sich",
    "bei",
    "auf",
    "von",
    "zu",
    "im",
    "am",
    "als",
    "auch",
    "werden",
    "haben",
    "wird",
)
_MARKERS_THAT_MEAN_GERMAN = 3


def reads_as_german(text: str) -> bool:
    """True when a sentence is German rather than English with German nouns."""
    words = {word.strip(".,;:!?()[]\"'").casefold() for word in text.split()}
    return len(words & set(_GERMAN_MARKERS)) >= _MARKERS_THAT_MEAN_GERMAN


def enrichment_answer_validator(answer: Any) -> tuple[bool, str]:
    """The field rules, plus the two promises §5 makes to her."""
    ok, reason = _ENRICHMENT_FIELDS(answer)
    if not ok:
        return False, reason

    # A level she can act on has to be quoted from the ad. Anything else is a
    # guess dressed as a fact, and she would plan around it.
    if answer["german_level"] != "unclear" and not answer["german_evidence"].strip():
        return False, (
            f"german_level is '{answer['german_level']}' but german_evidence is empty — "
            "quote the phrase in the ad that shows it, or answer 'unclear'"
        )

    for name in ENGLISH_FIELDS:
        value = answer.get(name)
        parts = value if isinstance(value, list) else [value or ""]
        for part in parts:
            if isinstance(part, str) and reads_as_german(part):
                return False, f"{name} is written in German — every _en field must be English"
    return True, "ok"
