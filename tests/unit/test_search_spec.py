"""SearchSpec — who she is and what she wants this run, validated at build time."""

from __future__ import annotations

import pytest

from jobfinder.profile import Resume
from jobfinder.search_spec import GERMAN_LEVELS, SearchSpec, SearchSpecError


def make_resume() -> Resume:
    return Resume(
        basics={"name": "Jane Doe", "email": "j@example.com", "location": "Neuburg"},
        languages=(),
    )


def test_search_spec_rejects_empty_employment_types():
    with pytest.raises(SearchSpecError) as exc:
        SearchSpec.build(mode="general", employment_types=[], city_names=["Ingolstadt"])

    message = str(exc.value)
    assert "employment type" in message
    for valid in ("minijob", "werkstudent", "parttime", "fulltime", "internship"):
        assert valid in message


def test_search_spec_rejects_unknown_employment_type():
    with pytest.raises(SearchSpecError) as exc:
        SearchSpec.build(mode="general", employment_types=["volunteer"], city_names=["Ingolstadt"])

    assert "volunteer" in str(exc.value)


def test_general_mode_does_not_require_a_resume():
    spec = SearchSpec.build(
        mode="general",
        employment_types=["minijob"],
        city_names=["Ingolstadt"],
    )

    assert spec.cities[0].name == "Ingolstadt"
    assert spec.mode == "general"


def test_resume_mode_requires_a_readable_pool_yaml():
    with pytest.raises(SearchSpecError) as exc:
        SearchSpec.build(
            mode="resume",
            employment_types=["werkstudent"],
            city_names=["Neuburg an der Donau"],
        )

    assert "pool.yaml" in str(exc.value)
    assert "profile validate" in str(exc.value)


def test_resume_mode_accepts_a_resume():
    spec = SearchSpec.build(
        mode="resume",
        employment_types=["werkstudent", "parttime"],
        city_names=["Neuburg an der Donau", "Ingolstadt"],
        resume=make_resume(),
    )

    assert [city.name for city in spec.cities] == ["Neuburg an der Donau", "Ingolstadt"]


def test_unknown_city_fails_at_build_time_not_search_time():
    with pytest.raises(ValueError) as exc:
        SearchSpec.build(mode="general", employment_types=["minijob"], city_names=["Leipzig"])

    assert "Leipzig" in str(exc.value)


def test_radius_override_applies_only_to_that_city():
    spec = SearchSpec.build(
        mode="general",
        employment_types=["minijob"],
        city_names=["Ingolstadt", "München"],
        radius_km={"München": 50},
    )

    radii = {city.name: city.radius_km for city in spec.cities}
    assert radii == {"Ingolstadt": 25, "München": 50}


def test_german_level_ordering_and_validation():
    assert GERMAN_LEVELS.index("B1") < GERMAN_LEVELS.index("C1")
    with pytest.raises(SearchSpecError):
        SearchSpec.build(
            mode="general",
            employment_types=["minijob"],
            city_names=["Ingolstadt"],
            max_german_level="fluent",
        )
