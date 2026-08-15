"""One Pool per run — the only place llmpool is constructed.

Free-tier pacing, failover and budget handling are llmpool's job; this module's
job is to build it correctly every time: validator injected, state persisted
under ``data/``, and the run bounded by ``max_wait`` / ``run_deadline_seconds``
from Settings.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dotenv import load_dotenv
from llmpool import Pool, build_providers, load_catalog

if TYPE_CHECKING:
    from collections.abc import Callable

    from llmpool import ProviderBase

    from jobfinder.config import Settings


class LLMConfigError(Exception):
    """The pool cannot be built — one sentence naming the fix."""


def build_pool(
    settings: Settings,
    validator: Callable[[object], tuple[bool, str]] | None = None,
    *,
    providers: list[ProviderBase] | None = None,
) -> Pool:
    """Build the run's Pool. ``providers`` is an injection point for tests."""
    if providers is None:
        # The library reads os.environ only; .env was already loaded by
        # Settings.load, but be safe when a caller built Settings directly.
        load_dotenv(settings.project_root / ".env", override=False)
        providers = build_providers(load_catalog())

    if not providers:
        raise LLMConfigError(
            "No LLM provider keys found. Copy .env.example to .env and add at "
            "least one free key — `python -m llmpool doctor` lists where to "
            "get them."
        )

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return Pool(
        providers,
        validator=validator,
        state_path=settings.pool_state_path,
        max_wait=settings.llm_max_wait_seconds,
        run_deadline_seconds=settings.llm_run_deadline_seconds,
    )
