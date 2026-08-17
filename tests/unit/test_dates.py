"""One comparable date out of every shape a source reports.

Measured on her real store: `published_at` is present on all 859 jobs, in three
shapes — `2026-07-01` (Bundesagentur, Kleinanzeigen, Xing),
`2026-06-20T12:20:44Z` (Adzuna) and `2026-08-16T02:09:29+00:00` (Arbeitnow).

A string comparison across those is wrong, and not only at the boundary:
`'2026-08-16' < '2026-08-16T02:09:29Z'` is true, so "posted today" would drop
every plain-date ad posted today. Hence one derived value, `YYYY-MM-DD`, made
once on the way in.
"""

from __future__ import annotations

import pytest

from jobfinder.dates import published_on
from jobfinder.sources.base import RawPosting


class TestEveryShapeHerStoreHolds:
    def test_a_plain_date_is_already_comparable(self):
        assert published_on("2026-07-01") == "2026-07-01"

    def test_a_zulu_timestamp_becomes_its_date(self):
        assert published_on("2026-06-20T12:20:44Z") == "2026-06-20"

    def test_an_offset_timestamp_becomes_its_date(self):
        assert published_on("2026-08-16T02:09:29+00:00") == "2026-08-16"

    def test_a_space_separated_timestamp_becomes_its_date(self):
        assert published_on("2026-08-16 02:09:29") == "2026-08-16"

    def test_a_local_offset_is_converted_before_the_date_is_taken(self):
        """22:30 in Berlin on the 16th is 20:30 UTC on the 16th — same day. But
        00:30 on the 17th in Berlin is 22:30 UTC on the *16th*, and a filter
        that says "today" has to agree with itself about which day that is."""
        assert published_on("2026-08-17T00:30:00+02:00") == "2026-08-16"
        assert published_on("2026-08-16T22:30:00+02:00") == "2026-08-16"

    def test_a_date_with_a_time_but_no_zone_is_taken_as_written(self):
        assert published_on("2026-08-16T23:59:00") == "2026-08-16"


class TestWhatIsNotADate:
    @pytest.mark.parametrize(
        "raw",
        [None, "", "   ", "not a date", "2026", "2026-13-45", "YYYY-MM-DD", "0000-00-00"],
    )
    def test_junk_becomes_none_rather_than_raising(self, raw):
        assert published_on(raw) is None

    def test_a_date_out_of_range_is_refused_rather_than_clamped(self):
        # A source that reports the year 12 has a bug; storing it would put an
        # ad at the top of "newest first" forever.
        assert published_on("0012-05-06") is None


class TestRawPostingCarriesIt:
    def test_a_posting_derives_the_comparable_date_from_its_raw_one(self):
        posting = RawPosting(
            job_id="AZ:1",
            source="AZ",
            source_id="1",
            title="Aushilfe",
            published_at="2026-06-20T12:20:44Z",
        )

        assert posting.published_on == "2026-06-20"

    def test_a_posting_with_no_date_has_no_comparable_date(self):
        posting = RawPosting(job_id="BA:1", source="BA", source_id="1", title="Aushilfe")

        assert posting.published_on is None

    def test_the_raw_value_is_never_rewritten(self):
        """The job page shows what the source said; only the derived value is
        normalised, so nothing she reads is silently reworded."""
        posting = RawPosting(
            job_id="AN:1",
            source="AN",
            source_id="1",
            title="Retail Assistant",
            published_at="2026-08-16T02:09:29+00:00",
        )

        assert posting.published_at == "2026-08-16T02:09:29+00:00"
        assert posting.published_on == "2026-08-16"
