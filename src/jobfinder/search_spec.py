"""What she is looking for this run — validated before anything slow happens.

A SearchSpec is built once per run and passed to every source. Building it
resolves city names, checks employment types and the German level she is
comfortable with, so a typo fails here — at second zero — not four minutes
into a search.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from jobfinder.cities import City, resolve_city

if TYPE_CHECKING:
    from jobfinder.profile import Resume

EMPLOYMENT_TYPES = ("minijob", "werkstudent", "parttime", "fulltime", "internship")
MODES = ("resume", "general")

# Ordered low to high — used both to validate her comfort level and, later, to
# filter postings by their required German level.
GERMAN_LEVELS = ("none", "A1", "A2", "B1", "B2", "C1", "C2")


class SearchSpecError(Exception):
    """One actionable sentence about what is wrong with the requested search."""


@dataclass(frozen=True)
class SearchSpec:
    mode: str
    employment_types: tuple[str, ...]
    cities: tuple[City, ...]
    keywords: tuple[str, ...] = ()
    max_german_level: str = "B1"

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise SearchSpecError(f"Unknown mode '{self.mode}'. Use one of: {', '.join(MODES)}.")
        if not self.employment_types:
            raise SearchSpecError(
                "Pick at least one employment type. Valid types are: "
                f"{', '.join(EMPLOYMENT_TYPES)}."
            )
        unknown = [t for t in self.employment_types if t not in EMPLOYMENT_TYPES]
        if unknown:
            raise SearchSpecError(
                f"Unknown employment type(s) {', '.join(unknown)}. "
                f"Valid types are: {', '.join(EMPLOYMENT_TYPES)}."
            )
        if not self.cities:
            raise SearchSpecError(
                "Pick at least one city. Valid cities are listed by `jobfinder profile show`."
            )
        if self.max_german_level not in GERMAN_LEVELS:
            raise SearchSpecError(
                f"Unknown German level '{self.max_german_level}'. "
                f"Use one of: {', '.join(GERMAN_LEVELS)}."
            )

    @classmethod
    def build(
        cls,
        *,
        mode: str,
        employment_types: list[str] | tuple[str, ...],
        city_names: list[str] | tuple[str, ...],
        radius_km: dict[str, int] | None = None,
        keywords: list[str] | tuple[str, ...] = (),
        max_german_level: str = "B1",
        resume: Resume | None = None,
    ) -> SearchSpec:
        """Validate everything, resolve city names, demand a resume in resume mode."""
        if mode == "resume" and resume is None:
            raise SearchSpecError(
                "Resume mode needs a readable pool.yaml. "
                "Run `jobfinder profile validate` to see what is missing."
            )
        cities = tuple(resolve_city(name) for name in city_names)
        if radius_km:
            cities = tuple(
                city.with_radius(int(radius_km.get(city.name, city.radius_km))) for city in cities
            )
        return cls(
            mode=mode,
            employment_types=tuple(employment_types),
            cities=cities,
            keywords=tuple(keywords),
            max_german_level=max_german_level,
        )
