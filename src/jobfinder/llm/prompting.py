"""Prompt loading — one Markdown file per prompt, filename carries the version.

`roles.v1.md` is prompt "roles", version "v1". The version is part of the cache
key and lands in the database, so a rewritten prompt invalidates old answers
without a migration.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROMPTS_DIR = Path(__file__).parent / "prompts"

_VERSION_RE = re.compile(r"\.v(\d+)\.md$")


@dataclass(frozen=True)
class PromptSpec:
    name: str
    version: str
    text: str


def load_prompt(name: str, prompts_dir: Path | None = None) -> PromptSpec:
    """Load the highest-versioned `<name>.vN.md` in the prompts directory."""
    directory = prompts_dir or PROMPTS_DIR
    candidates = sorted(directory.glob(f"{name}.v*.md"))
    if not candidates:
        available = sorted(path.name for path in directory.glob("*.md") if path != directory / name)
        raise ValueError(
            f"No prompt file for '{name}' in {directory}. "
            f"Expected a file like '{name}.v1.md'. "
            f"Present: {', '.join(available) or 'none'}."
        )

    best = max(candidates, key=lambda path: _version_of(path))
    return PromptSpec(
        name=name,
        version=f"v{_version_of(best)}",
        text=best.read_text(encoding="utf-8"),
    )


def _version_of(path: Path) -> int:
    match = _VERSION_RE.search(path.name)
    if not match:
        raise ValueError(f"Prompt file '{path.name}' must carry a version: '{path.stem}.v1.md'.")
    return int(match.group(1))


# The source's own type flags, in the words the prompt asks the model to use.
# The BA answers "Minijob" in `employment_type_raw` and Adzuna answers nothing,
# so these booleans are often the only reliable statement of the contract type.
_TYPE_FLAGS = (
    ("is_minijob", "minijob"),
    ("is_werkstudent", "werkstudent"),
    ("is_parttime", "parttime"),
    ("is_fulltime", "fulltime"),
    ("is_internship", "internship"),
)


def render_enrichment_prompt(
    prompt_text: str,
    *,
    job: Mapping[str, Any],
    description: str,
    cv_digest: str,
) -> str:
    """One German ad plus her CV digest, in the order the prompt file expects.

    ``job`` is a row from `jobs` (a dict or `sqlite3.Row`). Only the facts the
    ad text may omit are passed on — never anything identifying her, which is
    why the digest arrives already stripped (see `roles.build_cv_digest`).
    """
    facts = dict(job)
    lines = [
        f"Title: {facts.get('title') or 'not stated'}",
        f"Company: {facts.get('company') or 'not stated'}",
        f"City: {facts.get('city') or 'not stated'}",
    ]
    if facts.get("employment_type_raw"):
        lines.append(f"Employment type, as the site wrote it: {facts['employment_type_raw']}")
    flags = [label for column, label in _TYPE_FLAGS if facts.get(column)]
    if flags:
        lines.append(f"Type flags from the source: {', '.join(flags)}")
    if facts.get("homeoffice"):
        lines.append("The source marked this job as home-office capable.")
    if facts.get("apply_url"):
        lines.append(f"Application link the site gave: {facts['apply_url']}")

    return (
        f"{prompt_text}\n\n"
        f"---\n\n"
        f"JOB FACTS FROM THE SOURCE:\n\n" + "\n".join(lines) + "\n\n"
        f"---\n\n"
        f"THE ADVERTISEMENT (German, verbatim):\n\n{description.strip()}\n\n"
        f"---\n\n"
        f"HER CV DIGEST:\n\n{cv_digest.strip()}\n"
    )
