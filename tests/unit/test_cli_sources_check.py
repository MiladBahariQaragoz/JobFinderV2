"""`jobfinder sources check` — does each site still answer this laptop?

Scrapers break when sites redesign and boards block clients without warning.
The honest way to ask is to ask: one small query per source, one plain-English
verdict each. It never stores anything and never fails the command — a "no"
is the answer, not an error.
"""

from __future__ import annotations

import pytest

from jobfinder.cli import main
from jobfinder.sources.base import PageResult, RawPosting
from jobfinder.sources.http import SourceUnavailable


def posting(n: int, source: str) -> RawPosting:
    return RawPosting(job_id=f"{source}:{n}", source=source, source_id=str(n), title=f"Job {n}")


class Answering:
    def __init__(self, source: str, count: int = 3):
        self.source = source
        self.count = count

    def search_pages(self, spec, *, start_query_index=0, start_page=1):
        yield PageResult(
            source=self.source,
            query_index=0,
            page=1,
            postings=[posting(i, self.source) for i in range(self.count)],
        )


class Refusing:
    def __init__(self, source: str, error: Exception):
        self.source = source
        self.error = error

    def search_pages(self, spec, *, start_query_index=0, start_page=1):
        raise self.error
        yield  # pragma: no cover — generator, never reached


@pytest.fixture
def no_adzuna_keys(monkeypatch):
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)


def check(tmp_path, adapters, skipped=()):
    """Run the command with a fixed set of adapters and capture nothing."""
    return main(
        ["sources", "check", "--root", str(tmp_path)],
        _client_factory=lambda _s, _delay=None: object(),
        _sources=(adapters, skipped),
    )


class TestVerdicts:
    def test_a_source_that_answers_says_how_many_it_found(self, tmp_path, capsys):
        code = check(tmp_path, [Answering("BA", count=42)])
        out = capsys.readouterr().out

        assert code == 0
        assert "Bundesagentur — answers, 42 jobs on the first page" in out

    def test_a_source_that_answers_with_nothing_names_both_possibilities(self, tmp_path, capsys):
        # Zero postings means one of two things and the check cannot tell them
        # apart: the site listed nothing for that query, or the adapter has
        # drifted. Live proof it matters — Arbeitnow really has no Ingolstadt
        # minijobs, and calling that a broken parser sends her fixing nothing.
        check(tmp_path, [Answering("KA", count=0)])
        out = capsys.readouterr().out

        assert "Kleinanzeigen — answers, no jobs matched" in out
        assert "nothing is listed" in out and "drifted" in out

    def test_a_blocked_source_says_so_in_her_words(self, tmp_path, capsys):
        check(tmp_path, [Refusing("SS", SourceUnavailable("www.stepstone.de kept refusing"))])
        out = capsys.readouterr().out

        assert "StepStone — no answer" in out
        assert "refusing" in out

    def test_an_unexpected_break_is_reported_not_raised(self, tmp_path, capsys):
        code = check(tmp_path, [Refusing("XI", ValueError("selector gone"))])
        out = capsys.readouterr().out

        assert code == 0  # a report, not a failure
        assert "Xing — broken" in out
        assert "selector gone" in out
        assert "Traceback" not in out

    def test_a_source_that_is_off_says_why_without_being_asked(self, tmp_path, capsys):
        check(tmp_path, [Answering("BA")], skipped=(("adzuna", "no API key in .env"),))
        out = capsys.readouterr().out

        assert "Adzuna — off (no API key in .env)" in out

    def test_every_source_is_reported_even_when_one_dies(self, tmp_path, capsys):
        check(
            tmp_path,
            [
                Refusing("SS", SourceUnavailable("blocked")),
                Answering("BA", count=5),
                Refusing("ID", SourceUnavailable("403")),
            ],
        )
        out = capsys.readouterr().out

        assert "StepStone — no answer" in out
        assert "Bundesagentur — answers, 5 jobs" in out
        assert "Indeed — no answer" in out

    def test_nothing_is_stored_by_a_check(self, tmp_path):
        check(tmp_path, [Answering("BA", count=3)])
        assert not (tmp_path / "data" / "jobfinder.db").exists()
