"""The German she says on the phone, and the German she sends.

This is the one part of Phase 9 only a model can write, and the one part that
has to be right in a way nothing else here does: she reads these lines aloud to
a stranger, in a language she is at roughly A2 in. Every line therefore carries
an English gloss — she has to know what she just said.

**One text per kind of place, not one per place.** MASTER_PLAN asked for
per-place. Measured against her real Neuburg list that is 34 provider calls to
produce 34 texts differing only in a name; per kind is 8, cached, with the name
and city substituted when the page renders. The cross-cutting free-tier rule is
the whole reason this project exists in the shape it does, and a script that
differs only in a substring is not worth a call.

Nothing identifying is sent. The prompt carries her **first name** and the kind
of business — no surname, no address, no phone, no email. Same line the CV
digest holds.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from jobfinder.llm.cache import LLMCache, cache_key, complete_json_cached, fingerprint
from jobfinder.llm.prompting import load_prompt

if TYPE_CHECKING:
    from jobfinder.config import Settings

# Five lines, in the order she says them. Fewer is not a phone call; more is not
# something she can hold together at A2 with a stranger waiting.
SCRIPT_LINES = 5

# What the business is called and where it is, filled in per place.
PLACE_TOKEN = "{place}"
CITY_TOKEN = "{city}"


class ScriptError(Exception):
    """One actionable sentence about why a script cannot be used."""


@dataclass(frozen=True)
class ScriptLine:
    de: str
    en: str


@dataclass(frozen=True)
class ContactTexts:
    """The script and the email for one kind of place, before substitution."""

    kind: str
    script_lines: tuple[ScriptLine, ...]
    email_subject: str
    email_body: str


def _validate(answer: dict, kind: str) -> ContactTexts:
    """Everything the answer must be before she is asked to say it out loud."""
    raw_lines = answer.get("script_lines")
    if not isinstance(raw_lines, list) or len(raw_lines) != SCRIPT_LINES:
        raise ScriptError(
            f"The script for a {kind} came back with "
            f"{len(raw_lines) if isinstance(raw_lines, list) else 'no'} lines, and it needs "
            f"exactly {SCRIPT_LINES}. Try again — the pool will use another provider."
        )

    lines: list[ScriptLine] = []
    for index, raw in enumerate(raw_lines, start=1):
        german = str((raw or {}).get("de", "")).strip() if isinstance(raw, dict) else ""
        english = str((raw or {}).get("en", "")).strip() if isinstance(raw, dict) else ""
        if not german or not english:
            raise ScriptError(
                f"Line {index} of the {kind} script is missing its "
                f"{'German' if not german else 'English'} half. She has to know what she is "
                "saying, so the script is not usable. Try again."
            )
        lines.append(ScriptLine(de=german, en=english))

    subject = str(answer.get("email_subject", "")).strip()
    body = str(answer.get("email_body", "")).strip()
    if not subject or not body:
        raise ScriptError(f"The {kind} email came back without a subject or a body. Try again.")
    if PLACE_TOKEN not in body:
        raise ScriptError(
            f"The {kind} email has nowhere to put the business's name, so every copy would be "
            "addressed to nobody. Try again."
        )
    return ContactTexts(
        kind=kind,
        script_lines=tuple(lines),
        email_subject=subject,
        email_body=body,
    )


def write_texts_for_kinds(
    settings: Settings,
    pool,
    *,
    kinds: tuple[str, ...],
    first_name: str,
    stop_on_exhausted: bool = False,
) -> dict[str, ContactTexts]:
    """One script and email per kind of place. Cached, so a second pass is free.

    With `stop_on_exhausted`, a spent quota ends the pass and returns whatever
    was already written (§9) rather than losing it.
    """
    from llmpool import PoolExhausted

    spec = load_prompt("contact_script")
    written: dict[str, ContactTexts] = {}

    with LLMCache(settings.llm_cache_path) as cache:
        for kind in kinds:
            prompt = _prompt_for(spec.text, kind=kind, first_name=first_name)
            key = cache_key(
                spec.version,
                hashlib.sha1(f"{kind}\x1f{first_name}".encode()).hexdigest(),
                fingerprint({"lines": SCRIPT_LINES, "tokens": [PLACE_TOKEN, CITY_TOKEN]}),
            )
            try:
                answer = complete_json_cached(pool, cache, prompt=prompt, key=key)
            except PoolExhausted:
                if stop_on_exhausted:
                    return written
                raise
            try:
                written[kind] = _validate(answer, kind)
            except ScriptError:
                # An unusable answer must not sit in the cache pretending to be
                # a script: the next attempt has to reach a provider again.
                cache.delete(key)
                raise
    return written


def _prompt_for(template: str, *, kind: str, first_name: str) -> str:
    readable = kind.replace("_", " ")
    return (
        f"{template}\n\n---\n\n"
        f"THE BUSINESS: a {readable}.\n"
        f"HER FIRST NAME: {first_name}.\n"
        "Write the script and the email for this kind of business."
    )


def render_script(texts: ContactTexts, place) -> str:
    """The script for one place: German line, English gloss underneath.

    It opens with who she is ringing. The German lines themselves do not name the
    business — she is talking *to* them, so saying their name back at them is
    odd — but this list is meant to be printed and held, and a page of five
    German lines with no idea who they are for is no use beside a phone.
    """
    # No ASCII underline: the name is substituted per place *after* this runs, so
    # a rule sized here would be the length of "{place} — {city}" and never match
    # the title above it.
    rendered: list[str] = [f"{place.name} — {place.city}", ""]
    for line in texts.script_lines:
        rendered.append(_fill(line.de, place))
        rendered.append(f"    {_fill(line.en, place)}")
    return "\n".join(rendered)


def render_email(texts: ContactTexts, place) -> tuple[str, str]:
    """`(subject, body)` for one place, ready for her to read and send."""
    return _fill(texts.email_subject, place), _fill(texts.email_body, place)


def _fill(text: str, place) -> str:
    return text.replace(PLACE_TOKEN, place.name).replace(CITY_TOKEN, place.city)
