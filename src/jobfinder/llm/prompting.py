"""Prompt loading — one Markdown file per prompt, filename carries the version.

`roles.v1.md` is prompt "roles", version "v1". The version is part of the cache
key and lands in the database, so a rewritten prompt invalidates old answers
without a migration.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

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
