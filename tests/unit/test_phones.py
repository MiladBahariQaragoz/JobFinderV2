"""Phone numbers she can tap, out of whatever a surveyor typed.

Measured in the real Neuburg payload: `'+49 8431 2078'` and `'+4984312079'` in
the same field across neighbouring places. Elsewhere OSM holds two numbers in
one field, a national `08431/…`, or a note in brackets. She will be holding a
phone while reading this list.

The rule that matters most is the last one: a field that is not a recognisable
number is **dropped**, never half-cleaned. A number that dials the wrong place
is worse than a blank.
"""

from __future__ import annotations

import pytest

from jobfinder.phones import normalize_phone


class TestTheShapesOsmActuallyHolds:
    def test_a_spaced_german_number_becomes_e164(self):
        assert normalize_phone("+49 8431 2078") == "+4984312078"

    def test_an_already_e164_number_is_left_alone(self):
        assert normalize_phone("+4984312079") == "+4984312079"

    def test_a_national_number_gains_the_country_code(self):
        assert normalize_phone("08431 648595") == "+498431648595"

    def test_a_slashed_national_number_is_cleaned(self):
        assert normalize_phone("08431/648595") == "+498431648595"

    def test_a_double_zero_prefix_becomes_a_plus(self):
        assert normalize_phone("004984312078") == "+4984312078"

    def test_a_number_with_dashes_and_dots_is_cleaned(self):
        assert normalize_phone("+49-8431-648.595") == "+498431648595"

    def test_a_note_in_brackets_is_not_dialled(self):
        assert normalize_phone("+49 8431 648595 (Küche)") == "+498431648595"

    def test_a_second_number_after_a_semicolon_takes_the_first(self):
        assert normalize_phone("+49 8431 648595; +49 8431 648596") == "+498431648595"

    def test_a_second_number_after_a_comma_takes_the_first(self):
        assert normalize_phone("+49 8431 648595, 08431 648596") == "+498431648595"

    def test_the_german_word_for_or_separates_two_numbers(self):
        assert normalize_phone("08431 648595 oder 08431 648596") == "+498431648595"


class TestWhatIsDropped:
    @pytest.mark.parametrize(
        "raw",
        [None, "", "   ", "keine", "auf Anfrage", "www.example.de", "-", "n/a"],
    )
    def test_something_that_is_not_a_number_is_dropped_not_mangled(self, raw):
        assert normalize_phone(raw) is None

    def test_a_number_too_short_to_dial_is_dropped(self):
        # An extension, or a truncated entry. Prefixing a country code onto it
        # would produce something that rings a stranger.
        assert normalize_phone("2078") is None
        assert normalize_phone("+49 84") is None

    def test_a_number_far_too_long_is_dropped(self):
        # Two numbers typed with no separator at all.
        assert normalize_phone("+4984312078084312079123") is None

    def test_a_bare_local_number_without_a_leading_zero_is_dropped(self):
        """An area code cannot be recovered from a number that never carried
        one, and guessing hers would dial a stranger in her own town."""
        assert normalize_phone("648595") is None


class TestItIsStable:
    def test_normalising_twice_changes_nothing(self):
        once = normalize_phone("+49 8431 2078")
        assert normalize_phone(once) == once

    def test_two_spellings_of_one_number_agree(self):
        """The whole point: these two sit side by side in her real list."""
        assert normalize_phone("+49 8431 20780") == normalize_phone("+4984312 0780")

    def test_another_country_code_is_kept_as_given(self):
        assert normalize_phone("+43 664 1234567") == "+436641234567"
