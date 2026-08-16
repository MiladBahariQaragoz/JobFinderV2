"""The source registry — the one place that knows which sources exist.

`build_adapters` turns her `enabled_sources` setting into adapter instances,
each with its **own** HTTP client and therefore its own request budget
(Phase 4 audit: a source's budget is spent per leg, per source). A source that
cannot run is reported as skipped with a reason, never raised as an error —
one absent source must not cost her the run.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field

from jobfinder.config import Settings
from jobfinder.sources.arbeitnow import ArbeitnowApi
from jobfinder.sources.ba import BAApi

# The order results are searched in. Fixed on purpose: the backbone first.
KNOWN_SOURCES = ("ba", "arbeitnow", "adzuna")

# What she sees, not what the adapter calls itself. Keys are both the config
# name and the adapter's source code, because summaries carry either.
SOURCE_LABELS = {
    "ba": "Bundesagentur",
    "BA": "Bundesagentur",
    "arbeitnow": "Arbeitnow",
    "AN": "Arbeitnow",
    "adzuna": "Adzuna",
    "AZ": "Adzuna",
}


@dataclass(frozen=True)
class RegistryBuild:
    """What one leg's adapter construction produced."""

    adapters: list = field(default_factory=list)
    # (source name, plain-English reason) for everything configured-but-off.
    skipped: tuple[tuple[str, str], ...] = ()


def adzuna_keys_present() -> bool:
    return bool(os.environ.get("ADZUNA_APP_ID")) and bool(os.environ.get("ADZUNA_APP_KEY"))


def skipped_sources(settings: Settings) -> tuple[tuple[str, str], ...]:
    """Every known source that will not run, and why — no clients built."""
    skipped: list[tuple[str, str]] = []
    for name in KNOWN_SOURCES:
        if name not in settings.enabled_sources:
            skipped.append((name, "disabled in config.yaml"))
        elif name == "adzuna" and not adzuna_keys_present():
            skipped.append((name, "no API key in .env"))
    return tuple(skipped)


def build_adapters(
    settings: Settings, client_factory: Callable[[Settings], object]
) -> RegistryBuild:
    """Build one adapter per enabled source, each with a fresh client."""
    unknown = [name for name in settings.enabled_sources if name not in KNOWN_SOURCES]
    if unknown:
        raise ValueError(
            f"unknown source(s) {', '.join(unknown)} in enabled_sources. "
            f"Valid sources are: {', '.join(KNOWN_SOURCES)}."
        )

    adapters: list = []
    for name in KNOWN_SOURCES:
        if name not in settings.enabled_sources:
            continue  # reported by `skipped_sources`, not rebuilt here
        if name == "adzuna" and not adzuna_keys_present():
            continue
        adapters.append(_ADAPTERS_FOR[name](client_factory(settings)))
    return RegistryBuild(adapters=adapters, skipped=skipped_sources(settings))


# Each entry builds its adapter around the client it is given.
_ADAPTERS_FOR = {
    "ba": lambda client: BAApi(client),
    "arbeitnow": lambda client: ArbeitnowApi(client),
    "adzuna": lambda client: _adzuna_adapter(client),
}


def _adzuna_adapter(client):
    from jobfinder.sources.adzuna import AdzunaApi

    return AdzunaApi(client)
