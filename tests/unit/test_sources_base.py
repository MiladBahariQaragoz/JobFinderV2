"""The source contract every adapter implements and the store consumes."""

from __future__ import annotations

import dataclasses
import hashlib

import pytest

from jobfinder.sources.base import (
    RawPosting,
    make_dedupe_key,
    normalize_for_dedupe,
)


def _posting(**overrides) -> RawPosting:
    base = dict(
        job_id="BA:11119-4913285274-S",
        source="BA",
        source_id="11119-4913285274-S",
        title="Werkstudent (m/w/d)",
        company="DEKRA Arbeit GmbH",
    )
    return RawPosting(**{**base, **overrides})


def test_raw_posting_is_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        _posting().title = "nope"


def test_new_posting_defaults_are_falsy_not_broken():
    posting = _posting()
    assert posting.is_minijob is False
    assert posting.homeoffice is False
    assert posting.published_at is None
    assert posting.description is None
    assert posting.has_description is False


def test_content_hash_is_sha1_of_the_description():
    posting = _posting(description="Küchenhilfe für Bäckerei gesucht")
    assert (
        posting.content_hash
        == hashlib.sha1("Küchenhilfe für Bäckerei gesucht".encode()).hexdigest()
    )


def test_content_hash_is_none_without_a_description():
    assert _posting().content_hash is None


class TestDedupeNormalisation:
    def test_gender_markers_are_ignored(self):
        assert normalize_for_dedupe("Werkstudent (m/w/d)") == normalize_for_dedupe(
            "Werkstudent (m/f/d)"
        )
        assert normalize_for_dedupe("Kellner (m/w/d)") == normalize_for_dedupe("kellner")
        assert normalize_for_dedupe("Verkäufer (w/m/d)") == normalize_for_dedupe("Verkaeufer")

    def test_case_and_inner_whitespace_are_ignored(self):
        assert normalize_for_dedupe("Sachbearbeiter  Umweltschutz") == normalize_for_dedupe(
            "sachbearbeiter umweltschutz"
        )

    def test_normal_text_is_still_distinct(self):
        assert normalize_for_dedupe("Kellner") != normalize_for_dedupe("Köche")


def test_dedupe_key_is_stable_across_sources():
    ba = make_dedupe_key(
        title="Werkstudent (m/w/d)", company="DEKRA Arbeit GmbH", city="Ingolstadt"
    )
    other_site = make_dedupe_key(
        title="werkstudent (m/f/d)", company="dekra arbeit gmbh", city="ingolstadt"
    )
    assert ba == other_site


def test_dedupe_key_is_built_from_the_city_every_source_reports():
    # The BA answers with a postcode, Arbeitnow never does. Keying on the
    # postcode therefore means the same ad on both sites never matches, which
    # is the whole point of the key — so the city carries the location.
    ba = make_dedupe_key(title="Werkstudent Küche", company="Bäckerei Müller", city="Ingolstadt")
    arbeitnow = make_dedupe_key(
        title="Werkstudent Küche", company="Bäckerei Müller", city="Ingolstadt"
    )
    assert ba == arbeitnow


def test_dedupe_key_ignores_the_district_a_source_appends_to_the_city():
    # The BA writes "Ingolstadt, Donau" and "Rohrbach, Ilm"; every other source
    # writes the plain city name.
    assert make_dedupe_key(
        title="Kellner", company="Café Glück", city="Ingolstadt, Donau"
    ) == make_dedupe_key(title="Kellner", company="Café Glück", city="Ingolstadt")


def test_dedupe_key_moves_with_location_or_title():
    base = make_dedupe_key(title="Kellner", company="Café Glück", city="Ingolstadt")
    assert base != make_dedupe_key(title="Kellner", company="Café Glück", city="München")
    assert base != make_dedupe_key(title="Barista", company="Café Glück", city="Ingolstadt")
    assert base != make_dedupe_key(title="Kellner", company="Café Extra", city="Ingolstadt")


def test_dedupe_key_tolerates_missing_fields():
    key = make_dedupe_key(title="Aushilfe", company=None, city=None)
    assert isinstance(key, str) and key
