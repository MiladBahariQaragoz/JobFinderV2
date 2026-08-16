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
from jobfinder.sources.indeed import IndeedScraper
from jobfinder.sources.kleinanzeigen import KleinanzeigenScraper
from jobfinder.sources.stepstone import StepStoneScraper
from jobfinder.sources.xing import XingScraper

# The order results are searched in. Fixed on purpose: the backbone first,
# then the other APIs, then the scraped sites.
KNOWN_SOURCES = ("ba", "arbeitnow", "adzuna", "kleinanzeigen", "xing", "stepstone", "indeed")

# What kind of host each source talks to, which is what decides its pacing
# (§8 rule 1): a documented API gets the 1 s gap, a scraped site the careful
# 3 s one.
SOURCE_KINDS = {
    "ba": "api",
    "arbeitnow": "api",
    "adzuna": "api",
    "kleinanzeigen": "scraper",
    "xing": "scraper",
    "stepstone": "scraper",
    "indeed": "scraper",
}

# Both boards refused this project's politely-identified client during Phase 6
# recon, so they ship off. Enabling them costs a run minutes of timeouts and
# earns nothing until their fixtures can be recorded from a network they
# answer on — the skip line says so rather than leaving her guessing.
BLOCKED_BY_DEFAULT = {
    "stepstone": "blocked this client in testing — enable once it answers again",
    "indeed": "blocked this client in testing — enable once it answers again",
}

# What she sees, not what the adapter calls itself. Keys are both the config
# name and the adapter's source code, because summaries carry either.
SOURCE_LABELS = {
    "ba": "Bundesagentur",
    "BA": "Bundesagentur",
    "arbeitnow": "Arbeitnow",
    "AN": "Arbeitnow",
    "adzuna": "Adzuna",
    "AZ": "Adzuna",
    "kleinanzeigen": "Kleinanzeigen",
    "KA": "Kleinanzeigen",
    "xing": "Xing",
    "XI": "Xing",
    "stepstone": "StepStone",
    "SS": "StepStone",
    "indeed": "Indeed",
    "ID": "Indeed",
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
            skipped.append((name, BLOCKED_BY_DEFAULT.get(name, "disabled in config.yaml")))
        elif name == "adzuna" and not adzuna_keys_present():
            skipped.append((name, "no API key in .env"))
    return tuple(skipped)


def delay_for_kind(settings: Settings, kind: str) -> float:
    """The §8 gap between two requests to one host of this kind."""
    return settings.scraper_delay_seconds if kind == "scraper" else settings.api_delay_seconds


def build_adapters(
    settings: Settings, client_factory: Callable[[Settings, float], object]
) -> RegistryBuild:
    """Build one adapter per enabled source, each with a fresh client.

    The client is built with the pacing its source's host deserves — the
    registry is the only place that knows which sources are scraped.
    """
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
        delay = delay_for_kind(settings, SOURCE_KINDS[name])
        adapters.append(_ADAPTERS_FOR[name](client_factory(settings, delay)))
    return RegistryBuild(adapters=adapters, skipped=skipped_sources(settings))


# Each entry builds its adapter around the client it is given.
_ADAPTERS_FOR = {
    "ba": lambda client: BAApi(client),
    "arbeitnow": lambda client: ArbeitnowApi(client),
    "adzuna": lambda client: _adzuna_adapter(client),
    "kleinanzeigen": lambda client: KleinanzeigenScraper(client),
    "xing": lambda client: XingScraper(client),
    "stepstone": lambda client: StepStoneScraper(client),
    "indeed": lambda client: IndeedScraper(client),
}


def _adzuna_adapter(client):
    from jobfinder.sources.adzuna import AdzunaApi

    return AdzunaApi(client)
