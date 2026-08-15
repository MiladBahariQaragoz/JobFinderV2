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
            if not isinstance(value, str) or not value.strip():
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
