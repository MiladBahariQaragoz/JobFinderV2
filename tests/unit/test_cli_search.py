"""`jobfinder search` — dry-run shows the exact requests, runs speak her language."""

from __future__ import annotations

import pytest

from jobfinder.cli import main
from jobfinder.search import SearchSummary
from jobfinder.search_spec import SearchSpec


def no_adapters(_settings):
    """A client factory that is never reached — the fake runner never builds adapters."""
    return []


def summary(**overrides) -> SearchSummary:
    values = dict(
        run_id=1,
        state="done",
        found=120,
        new=30,
        duplicates=90,
        errors=[],
        resumed=False,
    )
    values.update(overrides)
    return SearchSummary(**values)


@pytest.fixture
def no_client():
    """A client factory that must never be reached — dry-run touches nothing."""

    def factory(_settings):
        raise AssertionError("no HTTP client may be built")

    return factory


class TestDryRun:
    def test_prints_the_exact_urls_and_touches_nothing(self, tmp_path, capsys, no_client):
        exit_code = main(
            ["search", "--root", str(tmp_path), "--dry-run", "--cities", "München"],
            _client_factory=no_client,
        )
        out = capsys.readouterr().out
        assert exit_code == 0
        assert "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs" in out
        assert "wo=M%C3%BCnchen" in out  # canonical umlauts, percent-encoded
        assert "umkreis=25" in out
        assert not (tmp_path / "data" / "jobfinder.db").exists()
        assert not (tmp_path / "data" / "jobs-init.csv").exists()

    def test_defaults_are_her_three_cities_and_three_types(self, tmp_path, capsys, no_client):
        main(["search", "--root", str(tmp_path), "--dry-run"], _client_factory=no_client)
        out = capsys.readouterr().out
        for city in ("Neuburg+an+der+Donau", "Ingolstadt", "M%C3%BCnchen"):
            assert city in out
        assert "Werkstudent" in out  # types default includes werkstudent → travels in `was`
        assert "arbeitszeit=mj" in out  # minijob
        assert "arbeitszeit=tz" in out  # parttime

    def test_keywords_and_radius_are_applied(self, tmp_path, capsys, no_client):
        main(
            [
                "search",
                "--root",
                str(tmp_path),
                "--dry-run",
                "--cities",
                "Ingolstadt",
                "--keywords",
                "Küche",
                "--radius",
                "40",
            ],
            _client_factory=no_client,
        )
        out = capsys.readouterr().out
        assert "was=K%C3%BCche" in out
        assert "umkreis=40" in out


class TestRun:
    def test_normal_run_prints_her_counts_and_exits_zero(self, tmp_path, capsys):
        def runner(connection, adapters, spec, **kwargs):
            return summary(found=120, new=30, duplicates=90)

        exit_code = main(
            ["search", "--root", str(tmp_path)], _client_factory=no_adapters, _runner=runner
        )
        out = capsys.readouterr().out
        assert exit_code == 0
        assert "120" in out and "30" in out and "90" in out
        assert "new" in out.casefold()
        assert "already" in out  # duplicates in her words, not jargon

    def test_runner_receives_the_spec_and_the_resume_flag(self, tmp_path, capsys):
        seen = {}

        def runner(connection, adapters, spec, **kwargs):
            seen["spec"] = spec
            seen["resume"] = kwargs.get("resume")
            seen["csv_path"] = kwargs.get("csv_path")
            return summary()

        main(
            ["search", "--root", str(tmp_path), "--resume"],
            _client_factory=no_adapters,
            _runner=runner,
        )
        assert isinstance(seen["spec"], SearchSpec)
        assert seen["spec"].cities[0].name == "Neuburg an der Donau"  # her default cities
        assert len(seen["spec"].cities) == 3
        assert seen["resume"] is True
        assert seen["csv_path"] is not None  # the export runs at the end of a run

    def test_interrupted_run_says_what_was_kept_and_how_to_continue(self, tmp_path, capsys):
        def runner(connection, adapters, spec, **kwargs):
            return summary(state="interrupted", found=84, new=12, duplicates=72, resumed=False)

        exit_code = main(
            ["search", "--root", str(tmp_path)], _client_factory=no_adapters, _runner=runner
        )
        out = capsys.readouterr().out
        assert exit_code == 0  # interrupted is resumable, not a failure
        assert "84" in out and "12" in out
        assert "--resume" in out  # the exact next step

    def test_source_errors_are_listed_in_her_summary(self, tmp_path, capsys):
        def runner(connection, adapters, spec, **kwargs):
            return summary(errors=["AN: SourceUnavailable: arbeitnow is down"])

        exit_code = main(
            ["search", "--root", str(tmp_path)], _client_factory=no_adapters, _runner=runner
        )
        out = capsys.readouterr().out
        assert exit_code == 0
        assert "arbeitnow is down" in out

    def test_each_source_gets_its_own_line_in_her_words(self, tmp_path, capsys):
        from jobfinder.search import SourceCounts

        def runner(connection, adapters, spec, **kwargs):
            return summary(
                per_source={
                    "BA": SourceCounts(found=42, new=7, duplicates=35),
                    "AN": SourceCounts(found=3, new=1, duplicates=2),
                }
            )

        main(["search", "--root", str(tmp_path)], _client_factory=no_adapters, _runner=runner)
        out = capsys.readouterr().out
        assert "Bundesagentur — 42 found, 7 new" in out
        assert "Arbeitnow — 3 found, 1 new" in out

    def test_a_skipped_source_says_why(self, tmp_path, capsys, monkeypatch):
        monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
        monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)

        def runner(connection, adapters, spec, **kwargs):
            return summary()

        main(["search", "--root", str(tmp_path)], _client_factory=no_adapters, _runner=runner)
        out = capsys.readouterr().out
        assert "Adzuna — skipped (disabled in config.yaml)" in out


class TestAutoContinue:
    def test_every_leg_and_source_gets_its_own_fresh_client(self, tmp_path):
        # A leg gets a new budget because it gets a new client — and each
        # source gets its own client too, so one source cannot spend another's
        # politeness budget.
        built = []

        def client_factory(_settings):
            marker = object()
            built.append(marker)
            return marker

        def runner(connection, adapter_factory, spec, **kwargs):
            adapter_factory()
            adapter_factory()
            return summary()

        main(["search", "--root", str(tmp_path)], _client_factory=client_factory, _runner=runner)
        assert len(built) == 4  # 2 legs × 2 default sources

    def test_the_leg_cap_comes_from_settings(self, tmp_path):
        seen = {}

        def runner(connection, adapter_factory, spec, **kwargs):
            seen.update(kwargs)
            return summary()

        main(["search", "--root", str(tmp_path)], _client_factory=no_adapters, _runner=runner)
        assert seen["max_legs"] == 6

    def test_summary_says_how_many_rounds_it_took(self, tmp_path, capsys):
        def runner(connection, adapter_factory, spec, **kwargs):
            return summary(legs=3)

        main(["search", "--root", str(tmp_path)], _client_factory=no_adapters, _runner=runner)
        assert "3 rounds" in capsys.readouterr().out

    def test_a_single_round_is_not_worth_mentioning(self, tmp_path, capsys):
        def runner(connection, adapter_factory, spec, **kwargs):
            return summary(legs=1)

        main(["search", "--root", str(tmp_path)], _client_factory=no_adapters, _runner=runner)
        assert "rounds" not in capsys.readouterr().out


class TestNarration:
    """§10's panic rule: a cold run must never sit silent for minutes.

    The full progress surface belongs to Phase 8; on the command line one
    plain line per stored page is what stands between her and a dead screen.
    """

    def page(self, source="BA", number=1, count=50):
        from jobfinder.sources.base import PageResult, RawPosting

        postings = [
            RawPosting(job_id=f"{source}:{i}", source=source, source_id=str(i), title=f"Job {i}")
            for i in range(count)
        ]
        return PageResult(source=source, query_index=0, page=number, postings=postings)

    def runner_calling_on_page(self, *calls):
        def runner(connection, adapter_factory, spec, **kwargs):
            on_page = kwargs.get("on_page")
            assert on_page is not None, "the CLI must hand the runner a page printer"
            for page, found, new, duplicates in calls:
                on_page(page, found, new, duplicates)
            return summary()

        return runner

    def test_every_stored_page_prints_a_line_as_it_lands(self, tmp_path, capsys):
        runner = self.runner_calling_on_page(
            (self.page(number=1), 50, 50, 0),
            (self.page(number=2), 100, 73, 27),
        )
        main(["search", "--root", str(tmp_path)], _client_factory=no_adapters, _runner=runner)
        out = capsys.readouterr().out

        assert "Bundesagentur, page 1 — 50 found, 50 new" in out
        assert "Bundesagentur, page 2 — 100 found, 73 new, 27 already known" in out

    def test_the_page_line_names_the_source_she_would_recognise(self, tmp_path, capsys):
        runner = self.runner_calling_on_page((self.page(source="AN", number=4), 12, 3, 9))
        main(["search", "--root", str(tmp_path)], _client_factory=no_adapters, _runner=runner)
        assert "Arbeitnow, page 4" in capsys.readouterr().out

    def test_page_lines_are_flushed_so_the_screen_moves_during_the_run(self, tmp_path, monkeypatch):
        import io
        import sys

        class Recorder(io.StringIO):
            flushes = 0

            def flush(self):
                Recorder.flushes += 1

        monkeypatch.setattr(sys, "stdout", Recorder())
        runner = self.runner_calling_on_page((self.page(), 50, 50, 0))
        main(["search", "--root", str(tmp_path)], _client_factory=no_adapters, _runner=runner)

        assert Recorder.flushes > 0  # buffered output would look frozen

    def test_a_continued_leg_says_the_search_is_carrying_on(self, tmp_path, capsys):
        def runner(connection, adapter_factory, spec, **kwargs):
            on_leg = kwargs.get("on_leg")
            assert on_leg is not None, "the CLI must hand the runner a leg printer"
            on_leg(1, summary(state="interrupted", budget_exhausted=True, found=800), summary())
            return summary(legs=2)

        main(["search", "--root", str(tmp_path)], _client_factory=no_adapters, _runner=runner)
        out = capsys.readouterr().out
        assert "budget" in out.casefold()
        assert "continuing" in out.casefold()

    def test_a_finished_leg_announces_nothing(self, tmp_path, capsys):
        def runner(connection, adapter_factory, spec, **kwargs):
            kwargs["on_leg"](1, summary(state="done"), summary())
            return summary()

        main(["search", "--root", str(tmp_path)], _client_factory=no_adapters, _runner=runner)
        assert "continuing" not in capsys.readouterr().out.casefold()


class TestResumeMessages:
    """`--resume` has to say what it actually did, not report an empty search."""

    def runner_returning(self, **overrides):
        def runner(connection, adapter_factory, spec, **kwargs):
            return summary(**overrides)

        return runner

    def test_resume_after_a_finished_search_says_there_was_nothing_left(self, tmp_path, capsys):
        # The cursor from the finished run points past the last query, so the
        # run is correct at 0 found — the sentence was the lie.
        runner = self.runner_returning(found=0, new=0, duplicates=0, resumed=True)
        main(
            ["search", "--root", str(tmp_path), "--resume"],
            _client_factory=no_adapters,
            _runner=runner,
        )
        out = capsys.readouterr().out

        assert "already finished" in out.casefold()
        assert "Search finished: 0 jobs found" not in out

    def test_resume_with_nothing_interrupted_says_a_fresh_search_ran(self, tmp_path, capsys):
        runner = self.runner_returning(found=12, new=12, duplicates=0, resumed=False)
        main(
            ["search", "--root", str(tmp_path), "--resume"],
            _client_factory=no_adapters,
            _runner=runner,
        )
        out = capsys.readouterr().out

        assert "nothing was interrupted" in out.casefold()
        assert "12" in out  # and the fresh search still reports what it found

    def test_a_resumed_run_that_found_more_reports_the_counts_as_usual(self, tmp_path, capsys):
        runner = self.runner_returning(found=12, new=4, duplicates=8, resumed=True)
        main(
            ["search", "--root", str(tmp_path), "--resume"],
            _client_factory=no_adapters,
            _runner=runner,
        )
        out = capsys.readouterr().out

        assert "Search finished: 12 jobs found" in out
        assert "already finished" not in out.casefold()

    def test_a_fresh_search_that_found_nothing_is_not_called_already_finished(
        self, tmp_path, capsys
    ):
        runner = self.runner_returning(found=0, new=0, duplicates=0, resumed=False)
        main(["search", "--root", str(tmp_path)], _client_factory=no_adapters, _runner=runner)
        out = capsys.readouterr().out

        assert "already finished" not in out.casefold()
        assert "Search finished: 0 jobs found" in out

    def test_an_interrupted_resume_still_offers_to_continue(self, tmp_path, capsys):
        runner = self.runner_returning(state="interrupted", found=0, new=0, resumed=True)
        main(
            ["search", "--root", str(tmp_path), "--resume"],
            _client_factory=no_adapters,
            _runner=runner,
        )
        out = capsys.readouterr().out

        assert "already finished" not in out.casefold()  # it did not finish
        assert "--resume" in out


class TestValidation:
    def test_unknown_city_is_one_sentence_and_no_traceback(self, tmp_path, capsys):
        exit_code = main(
            ["search", "--root", str(tmp_path), "--dry-run", "--cities", "Atlantis"],
            _client_factory=no_adapters,
        )
        out = capsys.readouterr().out
        assert exit_code == 1
        assert "Atlantis" in out
        assert "Traceback" not in out

    def test_unknown_type_is_rejected_before_any_request(self, tmp_path, capsys):
        exit_code = main(
            [
                "search",
                "--root",
                str(tmp_path),
                "--dry-run",
                "--types",
                "nightshift",
            ],
            _client_factory=no_adapters,
        )
        out = capsys.readouterr().out
        assert exit_code == 1
        assert "nightshift" in out
        assert "Traceback" not in out
