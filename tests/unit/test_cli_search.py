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
        # Adzuna is enabled by default; the key is what it is missing.
        assert "Adzuna — skipped (no API key in .env)" in out


class TestAutoContinue:
    def test_every_leg_and_source_gets_its_own_fresh_client(self, tmp_path):
        # A leg gets a new budget because it gets a new client — and each
        # source gets its own client too, so one source cannot spend another's
        # politeness budget.
        built = []

        def client_factory(_settings, _delay_seconds=None):
            marker = object()
            built.append(marker)
            return marker

        def runner(connection, adapter_factory, spec, **kwargs):
            adapter_factory()
            adapter_factory()
            return summary()

        main(["search", "--root", str(tmp_path)], _client_factory=client_factory, _runner=runner)
        assert len(built) == 8  # 2 legs × 4 default sources

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

    def counts(self, found=0, new=0, duplicates=0):
        from jobfinder.search import SourceCounts

        return SourceCounts(found=found, new=new, duplicates=duplicates)

    def runner_calling_on_page(self, *calls):
        def runner(connection, adapter_factory, spec, **kwargs):
            on_page = kwargs.get("on_page")
            assert on_page is not None, "the CLI must hand the runner a page printer"
            for page, page_counts, totals in calls:
                on_page(page, page_counts, totals)
            return summary()

        return runner

    def test_every_stored_page_prints_a_line_as_it_lands(self, tmp_path, capsys):
        runner = self.runner_calling_on_page(
            (self.page(number=1), self.counts(50, 50, 0), self.counts(50, 50, 0)),
            (self.page(number=2), self.counts(50, 23, 27), self.counts(100, 73, 27)),
        )
        main(["search", "--root", str(tmp_path)], _client_factory=no_adapters, _runner=runner)
        out = capsys.readouterr().out

        assert "Bundesagentur, page 1 — 50 found, 50 new" in out
        assert "Bundesagentur, page 2 — 50 found, 23 new, 27 already known" in out
        assert "100 so far" in out  # the run's total belongs at the end of the line

    def test_the_page_line_counts_that_page_not_the_whole_run(self, tmp_path, capsys):
        # The defect this replaced: a page that stored nothing printed the
        # totals of the source that ran before it — "Arbeitnow — 116 found"
        # on a page where Arbeitnow found nothing at all.
        runner = self.runner_calling_on_page(
            (
                self.page(source="AN", number=1, count=0),
                self.counts(0, 0, 0),
                self.counts(116, 115, 1),
            )
        )
        main(["search", "--root", str(tmp_path)], _client_factory=no_adapters, _runner=runner)
        out = capsys.readouterr().out

        assert "Arbeitnow, page 1 — 0 found, 0 new" in out
        assert "116 found" not in out.split("\n")[0]

    def test_the_page_line_names_the_source_she_would_recognise(self, tmp_path, capsys):
        runner = self.runner_calling_on_page(
            (self.page(source="AN", number=4), self.counts(12, 3, 9), self.counts(12, 3, 9))
        )
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
        runner = self.runner_calling_on_page(
            (self.page(), self.counts(50, 50, 0), self.counts(50, 50, 0))
        )
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


class TestParallelRun:
    def test_the_runner_is_told_where_the_database_is_so_it_can_thread(self, tmp_path):
        # Without db_path the runner has no way to give each source its own
        # connection, so it falls back to running them one after another.
        seen = {}

        def runner(connection, adapter_factory, spec, **kwargs):
            seen.update(kwargs)
            return summary()

        main(["search", "--root", str(tmp_path)], _client_factory=no_adapters, _runner=runner)
        assert seen["db_path"] == tmp_path / "data" / "jobfinder.db"


class TestClientPacing:
    def test_the_default_client_is_built_with_the_pace_it_is_given(self, tmp_path):
        from jobfinder.cli import _default_client_factory
        from jobfinder.config import Settings

        client = _default_client_factory(Settings(project_root=tmp_path), 1.0)

        assert client.min_delay == 1.0

    def test_a_real_run_paces_each_source_by_what_it_talks_to(self, tmp_path):
        # End to end through the registry: nothing else in the app decides
        # this, so a scraper paced like an API would show up here.
        paces = []

        def client_factory(settings, delay_seconds):
            paces.append(delay_seconds)
            return object()

        def runner(connection, adapter_factory, spec, **kwargs):
            adapter_factory()
            return summary()

        main(["search", "--root", str(tmp_path)], _client_factory=client_factory, _runner=runner)
        # Bundesagentur, Arbeitnow — then Kleinanzeigen and Xing, scraped.
        assert paces == [1.0, 1.0, 3.0, 3.0]


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


class TestSearchWithEnrich:
    """§9: `--enrich` runs both, and neither command alone changes because of it."""

    @staticmethod
    def _root(tmp_path):
        import yaml

        (tmp_path / "pool.yaml").write_text(
            yaml.safe_dump(
                {
                    "basics": {
                        "name": "Jane Doe",
                        "email": "j@example.com",
                        "location": "Neuburg an der Donau, Germany",
                    },
                    "skills": {"Programming Languages": ["Python"]},
                },
                allow_unicode=True,
            ),
            encoding="utf-8",
            newline="\n",
        )
        return tmp_path

    @staticmethod
    def _storing_runner(tmp_path, count=2):
        """A fake search that commits jobs, exactly as the real one does."""
        from jobfinder.sources.base import RawPosting
        from jobfinder.store.db import connect, migrate
        from jobfinder.store.jobs import upsert_job

        def runner(connection, adapter_factory, spec, **kwargs):
            worker = connect(tmp_path / "data" / "jobfinder.db")
            migrate(worker)
            for index in range(count):
                upsert_job(
                    worker,
                    RawPosting(
                        job_id=f"BA:{index:03d}",
                        source="BA",
                        source_id=f"{index:03d}",
                        title=f"Aushilfe Bäckerei {index} (m/w/d)",
                        company="Bäckerei Musterle",
                        city="Ingolstadt",
                        description=(
                            f"Wir suchen eine Aushilfe für Filiale {index}. "
                            "Gute Deutschkenntnisse in Wort und Schrift "
                            "sind erforderlich."
                        ),
                    ),
                )
            worker.close()
            return summary(found=count, new=count, duplicates=0)

        return runner

    @staticmethod
    def _answer():
        return {
            "category": "retail",
            "seniority": "entry",
            "skills_required": ["customer service"],
            "skills_nice": [],
            "german_level": "B1",
            "german_evidence": "Gute Deutschkenntnisse in Wort und Schrift",
            "english_sufficient": False,
            "employment_type_norm": "minijob",
            "duties_en": ["Serve customers at the counter"],
            "requirements_en": ["Reliable"],
            "summary_en": "A weekend job at a bakery counter in Ingolstadt.",
            "fit_score": 62,
            "fit_reasons": ["Her retail experience matches"],
            "missing_for_fit": ["Stronger spoken German"],
            "red_flags": [],
            "application_method": "email",
            "contact_email": "jobs@example.de",
            "contact_phone": "",
            "deadline": "",
        }

    def test_the_jobs_a_search_stores_come_back_explained_in_the_same_command(
        self, tmp_path, capsys
    ):
        from tests.fakes import FakePool

        root = self._root(tmp_path)
        pool = FakePool([self._answer()] * 2)

        exit_code = main(
            ["search", "--root", str(root), "--enrich"],
            _client_factory=no_adapters,
            _runner=self._storing_runner(root),
            _pool_factory=lambda: pool,
        )

        out = capsys.readouterr().out
        assert exit_code == 0
        assert len(pool.calls) == 2
        assert "explained" in out.lower()
        assert (root / "data" / "jobs-enriched.csv").exists()

    def test_search_alone_and_enrich_alone_are_unchanged_by_the_combined_command(
        self, tmp_path, capsys
    ):
        from tests.fakes import FakePool

        root = self._root(tmp_path)

        def pool_factory():
            raise AssertionError("a plain search must never build an LLM pool")

        exit_code = main(
            ["search", "--root", str(root)],
            _client_factory=no_adapters,
            _runner=self._storing_runner(root),
            _pool_factory=pool_factory,
        )

        out = capsys.readouterr().out
        assert exit_code == 0
        assert "Search finished" in out
        assert "explained" not in out.lower()
        assert not (root / "data" / "jobs-enriched.csv").exists()

        # And `jobfinder enrich` afterwards behaves exactly as it does alone.
        pool = FakePool([self._answer()] * 2)
        assert main(["enrich", "--root", str(root)], _pool_factory=lambda: pool) == 0
        assert len(pool.calls) == 2

    def test_a_missing_pool_yaml_stops_the_command_before_it_searches(self, tmp_path, capsys):
        def runner(*args, **kwargs):
            raise AssertionError("the search must not start without her CV")

        exit_code = main(
            ["search", "--root", str(tmp_path), "--enrich"],
            _client_factory=no_adapters,
            _runner=runner,
        )

        out = capsys.readouterr().out
        assert exit_code == 1
        assert "pool.yaml" in out
        assert "Traceback" not in out
