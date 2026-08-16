"""The shared scraper vocabulary — one place decides what wording means."""

from __future__ import annotations

import pytest

from jobfinder.sources.wording import (
    employment_type_signals,
    search_term_for,
    slugify,
)


class TestEmploymentTypeSignals:
    def test_every_word_on_the_phase_6_minijob_list_counts(self):
        for wording in ("Minijob", "450 €", "520 €", "Aushilfe", "geringfügig"):
            assert "minijob" in employment_type_signals(wording), wording

    def test_the_spellings_the_sites_actually_use(self):
        assert "minijob" in employment_type_signals("Aushilfe im Verkauf, 450-Basis")
        assert "minijob" in employment_type_signals("Geringfuegige Beschaeftigung")
        assert "werkstudent" in employment_type_signals("Werkstudent/in gesucht")
        assert "internship" in employment_type_signals("Praktikum im Marketing")
        assert "parttime" in employment_type_signals("Teilzeitkraft gesucht")
        assert "fulltime" in employment_type_signals("Vollzeitstelle")

    def test_a_quiet_ad_signals_nothing(self):
        assert employment_type_signals("Produktionsmitarbeiter (m/w/d)") == set()

    def test_signals_read_title_and_description_together(self):
        signals = employment_type_signals(
            "Alltagshelfer gesucht", "Teilzeit oder Minijob – flexible Arbeitszeiten"
        )
        assert signals == {"minijob", "parttime"}


class TestSearchTerm:
    def test_each_type_maps_to_the_german_search_box_word(self):
        assert search_term_for("minijob") == "minijob"
        assert search_term_for("werkstudent") == "werkstudent"
        assert search_term_for("parttime") == "teilzeit"
        assert search_term_for("fulltime") == "vollzeit"
        assert search_term_for("internship") == "praktikum"

    def test_an_unknown_type_names_the_valid_ones(self):
        with pytest.raises(ValueError, match="minijob"):
            search_term_for("sideline")


class TestSlugify:
    def test_umluats_fold_the_way_german_sites_spell_them(self):
        assert slugify("München") == "muenchen"
        assert slugify("Nürnberg") == "nuernberg"
        assert slugify("Würzburg") == "wuerzburg"

    def test_spaces_and_punctuation_become_hyphens(self):
        assert slugify("Neuburg an der Donau") == "neuburg-an-der-donau"
        assert slugify("Aushilfe Küche") == "aushilfe-kueche"
