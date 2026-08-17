"""The four answers the app needs before it can do anything, and where they go.

Everything here exists so that she never has to open a text editor beside the
source code. The wizard asks for one free API key, the towns she is willing to
work in, and the kinds of work she can take; this module is what turns those
answers into the two files the rest of the app already reads — `.env` for the
key and `config.yaml` for the rest.

Two rules hold the shape of it:

- **Nothing is written until everything validates.** A typo'd town must not
  leave half a configuration behind.
- **The key is never returned, rendered or logged.** It goes from the form into
  `.env` and into this process's environment, and nothing here hands it back.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jobfinder.config import Settings


class SetupError(Exception):
    """Something she typed cannot be used, said in a sentence she can act on."""


def needs_setup(settings: Settings) -> bool:
    """True until the wizard has been through once.

    `config.yaml` is the marker because it is the file the wizard writes and the
    file the app reads — one truth rather than two that can disagree. Deleting
    it starts the wizard again, which is the documented way back to the
    beginning.
    """
    return not (settings.project_root / "config.yaml").exists()


def _split(raw: str | None) -> list[str]:
    return [part.strip() for part in (raw or "").split(",") if part.strip()]


def _validated(cities: list[str], types: list[str]) -> None:
    """Refuse a town or a kind of work the search could not use.

    Both checks already exist and both answer with the valid names — Phase 1's
    rule that the error message is the feature.
    """
    from jobfinder.search_spec import SearchSpec, SearchSpecError

    try:
        SearchSpec.build(mode="general", employment_types=types, city_names=cities)
    except (SearchSpecError, ValueError) as exc:
        raise SetupError(str(exc)) from exc


def save_setup(
    settings: Settings,
    *,
    env_var: str = "",
    api_key: str = "",
    cities: str = "",
    types: str = "",
) -> None:
    """Write her answers, or raise `SetupError` having written nothing."""
    from jobfinder.config import Settings as SettingsClass

    chosen_cities = _split(cities) or list(SettingsClass.__dataclass_fields__["cities"].default)
    chosen_types = _split(types) or list(
        SettingsClass.__dataclass_fields__["employment_types"].default
    )
    _validated(chosen_cities, chosen_types)

    if api_key.strip() and env_var.strip():
        _write_key(settings.project_root / ".env", env_var.strip(), api_key.strip())
    _write_config(settings.project_root / "config.yaml", chosen_cities, chosen_types)


def _write_key(env_path: Path, name: str, value: str) -> None:
    """Put one key into `.env`, keeping every other line it already had.

    Rewriting the file wholesale would drop the keys she added last month, and
    appending blindly would leave two lines for one provider — the second of
    which silently wins.
    """
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    pattern = re.compile(rf"^\s*{re.escape(name)}\s*=")
    kept = [line for line in lines if not pattern.match(line)]
    kept.append(f"{name}={value}")
    env_path.write_text("\n".join(kept) + "\n", encoding="utf-8")

    # So the key works now rather than after a restart — a sentence she should
    # never have to read.
    os.environ[name] = value


def _write_config(config_path: Path, cities: list[str], types: list[str]) -> None:
    """`config.yaml`, written as she would read it rather than as YAML dumps it.

    `yaml.safe_dump` would fold her umlauts into escapes (`M\\xFCnchen`), which
    is valid YAML and unreadable to the person whose file it is.
    """
    lines = [
        "# Written by JobFinder when you first set it up.",
        "# You can edit this by hand — one item per line, under its heading.",
        "",
        "cities:",
        *(f"  - {city}" for city in cities),
        "",
        "employment_types:",
        *(f"  - {kind}" for kind in types),
        "",
    ]
    config_path.write_text("\n".join(lines), encoding="utf-8")
