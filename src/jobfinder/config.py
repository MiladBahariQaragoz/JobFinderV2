"""Where everything lives and how the app is configured.

One `Settings` object is built at startup and passed down. Nothing else in the
codebase decides for itself where the database or the CSV exports belong.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    """Resolved paths and runtime limits for one run."""

    project_root: Path

    @classmethod
    def load(cls, project_root: Path) -> Settings:
        return cls(project_root=Path(project_root))

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
