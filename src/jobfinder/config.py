"""Where everything lives and how the app is configured.

One `Settings` object is built at startup and passed down. Nothing else in the
codebase decides for itself where the database or the CSV exports belong.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path

import yaml
from dotenv import load_dotenv

CONFIG_FILENAME = "config.yaml"
ENV_FILENAME = ".env"


@dataclass(frozen=True)
class Settings:
    """Resolved paths and runtime limits for one run."""

    project_root: Path
    request_budget: int = 200
    llm_budget: int = 500
    enabled_sources: tuple[str, ...] = ("ba",)

    @classmethod
    def load(cls, project_root: Path) -> Settings:
        project_root = Path(project_root)
        # Secrets only ever come from the environment. An already-set variable wins,
        # so a shell export beats a stale .env.
        load_dotenv(project_root / ENV_FILENAME, override=False)
        overrides = cls._read_config_file(project_root / CONFIG_FILENAME)
        if "enabled_sources" in overrides:
            overrides["enabled_sources"] = tuple(overrides["enabled_sources"])
        return cls(project_root=project_root, **overrides)

    @classmethod
    def _read_config_file(cls, path: Path) -> dict:
        if not path.exists():
            return {}
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        allowed = {f.name for f in fields(cls)} - {"project_root"}
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise ValueError(
                f"{path.name}: unknown setting(s) {', '.join(unknown)}. "
                f"Valid settings are: {', '.join(sorted(allowed))}."
            )
        return raw

    @property
    def data_dir(self) -> Path:
        return self.project_root / "data"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "jobfinder.db"

    @property
    def jobs_init_csv(self) -> Path:
        return self.data_dir / "jobs-init.csv"

    @property
    def jobs_enriched_csv(self) -> Path:
        return self.data_dir / "jobs-enriched.csv"

    @property
    def pool_state_path(self) -> Path:
        return self.data_dir / "pool_state.json"
