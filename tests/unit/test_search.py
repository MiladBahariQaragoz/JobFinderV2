"""The search runner — MASTER_PLAN §9's resume contract, in tests.

Whatever kills a run (her Ctrl-C, a dead network, a spent request budget), the
pages already fetched are on disk, the run row says `interrupted` with honest
counts, and `--resume` re-enters at the stored cursor instead of page 1.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta

import pytest

from jobfinder.search import SearchSummary, run_search
from jobfinder.search_spec import SearchSpec
from jobfinder.sources.base import PageResult, RawPosting
from jobfinder.sources.http import RequestBudgetExhausted, SourceUnavailable
from jobfinder.store.db import connect, migrate


def spec(**overrides) -> SearchSpec:
    parts = dict(mode="general", employment_types=["minijob"], city_names=["Ingolstadt"])
    parts.update(overrides)
    return SearchSpec.build(**parts)


def posting(n: int, source: str = "BA") -> RawPosting:
    # The company varies with the source so postings from different fake
    # sources stay distinct jobs — the merge path has its own store tests.
    return RawPosting(
        job_id=f"{source}:{n}",
        source=source,
        source_id=str(n),
        title=f"Job {n}",
        company=f"{source} ACME",
    )


class FakeSource:
    """Adapter stand-in: serves canned pages, records how it was entered."""

    def __init__(self, pages, source: str = "BA"):
        self.source = source
        self.pages = list(pages)  # PageResult or Exception, consumed in order
        self.entered_at: tuple[int, int] | None = None
        self.entered: list[tuple[int, int]] = []

    def search_pages(self, spec, *, start_query_index: int = 0, start_page: int = 1):
        self.entered_at = (start_query_index, start_page)
        self.entered.append(self.entered_at)
        while self.pages:
            item = self.pages.pop(0)
            if isinstance(item, BaseException):  # KeyboardInterrupt is not an Exception
                raise item
            if self.entered_at == (0, 1):  # a fresh entry re-serves the script
                pass
            yield item

    def fetch_detail(self, posting: RawPosting) -> RawPosting:
        return posting


@pytest.fixture
def db(tmp_path):
    connection = connect(tmp_path / "jobfinder.db")
    migrate(connection)
    yield connection
    connection.close()


def page(n_postings: int, *, query_index: int = 0, page_number: int = 1, source: str = "BA"):
    return PageResult(
        source=source,
        query_index=query_index,
        page=page_number,
        postings=[posting(f"{query_index}-{page_number}-{i}", source) for i in range(n_postings)],
    )


def run_row(connection, run_id: int):
    return connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()


class TestDurability:
    def test_killing_after_two_pages_keeps_both_pages_on_disk(self, db):
        killer = FakeSource(
            [
                page(3, page_number=1),
                page(3, page_number=2),
                KeyboardInterrupt(),  # she hits Ctrl-C while page 3 streams
            ]
        )
        summary = run_search(db, [killer], spec())

        assert summary.state == "interrupted"
        assert summary.found == 6
        stored = db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        assert stored == 6

    def test_interrupted_run_row_carries_honest_counts(self, db):
        killer = FakeSource([page(2, page_number=1), KeyboardInterrupt()])
        summary = run_search(db, [killer], spec())
        row = run_row(db, summary.run_id)
        assert row["state"] == "interrupted"
        assert row["found_count"] == 2
        assert row["new_count"] == 2
        assert row["finished_at"]

    def test_postings_are_written_before_the_next_page_is_fetched(self, db):
        witness = {"checked": False}

        class CarefulSource(FakeSource):
            def search_pages(self, spec, *, start_query_index=0, start_page=1):
                pages = list(self.pages)
                yield pages[0]
                # Before the runner may ask for page 2, page 1 must be stored.
                stored = db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
                witness["checked"] = stored == len(pages[0].postings)
                yield pages[1]

        careful = CarefulSource([page(3, page_number=1), page(3, page_number=2)])
        run_search(db, [careful], spec())
        assert witness["checked"] is True

    def test_completed_run_is_marked_done(self, db):
        source = FakeSource([page(2, page_number=1)])
        summary = run_search(db, [source], spec())
        assert summary.state == "done"
        assert run_row(db, summary.run_id)["state"] == "done"


class TestResume:
    def test_resume_continues_at_the_stored_cursor_not_page_one(self, db):
        first = FakeSource(
            [
                page(2, page_number=1),
                page(2, page_number=2),
                KeyboardInterrupt(),
            ]
        )
        run_search(db, [first], spec())

        second = FakeSource([page(2, query_index=0, page_number=3)])
        summary = run_search(db, [second], spec(), resume=True)

        assert second.entered_at == (0, 3)  # after page 2, not back at page 1
        assert summary.resumed is True

    def test_resume_without_an_interrupted_run_starts_fresh(self, db):
        source = FakeSource([page(1, page_number=1)])
        summary = run_search(db, [source], spec(), resume=True)
        assert source.entered_at == (0, 1)
        assert summary.resumed is False

    def test_cursor_from_a_different_spec_is_ignored(self, db):
        first = FakeSource(
            [
                page(2, page_number=1),
                page(2, page_number=2),
                KeyboardInterrupt(),
            ]
        )
        run_search(db, [first], spec())  # cursor saved for this spec's hash

        other = FakeSource([page(1, page_number=1)])
        run_search(db, [other], spec(city_names=["München"]), resume=True)  # different spec
        assert other.entered_at == (0, 1)


class TestFailures:
    def test_network_error_mid_run_marks_run_interrupted_with_counts(self, db):
        flaky = FakeSource(
            [
                page(2, page_number=1),
                SourceUnavailable("rest.arbeitsagentur.de kept refusing requests"),
            ]
        )
        summary = run_search(db, [flaky], spec())  # no traceback escapes

        assert summary.state == "interrupted"
        assert summary.found == 2
        assert summary.new == 2
        assert any("rest.arbeitsagentur.de" in error for error in summary.errors)

    def test_request_budget_exhaustion_stops_and_is_recorded_in_runs(self, db):
        spent = FakeSource(
            [
                page(2, page_number=1),
                RequestBudgetExhausted("Request budget of 200 spent"),
            ]
        )
        never_asked = FakeSource([page(1, page_number=1)], source="AN")
        summary = run_search(db, [spent, never_asked], spec())

        assert summary.state == "interrupted"
        assert summary.found == 2
        assert never_asked.entered == []  # budget stop halts the whole run
        row = run_row(db, summary.run_id)
        assert "budget" in row["errors"]

    def test_budget_exhaustion_is_flagged_apart_from_other_interruptions(self, db):
        # Only a spent budget is safe to continue automatically — see
        # run_search_until_done. Everything else means "stop and tell her".
        spent = FakeSource([page(2, page_number=1), RequestBudgetExhausted("budget of 200 spent")])
        assert run_search(db, [spent], spec()).budget_exhausted is True

    def test_a_network_failure_is_not_a_budget_stop(self, db):
        flaky = FakeSource([page(1, page_number=1), SourceUnavailable("host refusing")])
        assert run_search(db, [flaky], spec()).budget_exhausted is False

    def test_her_ctrl_c_is_not_a_budget_stop(self, db):
        stopped = FakeSource([page(1, page_number=1), KeyboardInterrupt()])
        assert run_search(db, [stopped], spec()).budget_exhausted is False

    def test_failing_source_records_its_error_and_the_run_returns_what_it_has(self, db):
        broken = FakeSource([SourceUnavailable("arbeitnow is down")], source="AN")
        healthy = FakeSource([page(3, page_number=1)], source="BA")
        summary = run_search(db, [broken, healthy], spec())

        assert summary.found == 3  # BA's postings survived AN's failure
        assert summary.new == 3
        assert any("arbeitnow" in error for error in summary.errors)
        assert "AN" in summary.errors[0]  # the error names its source


class TestAutoContinue:
    """A spent budget pauses a run; it should not need her to restart it by hand.

    Each leg gets a client with a fresh budget, re-enters at the stored cursor,
    and the loop stops the moment continuing would be wrong or pointless.
    """

    def legs(self, *scripts):
        """A factory handing out one scripted adapter per leg, recording each."""
        made: list[FakeSource] = []

        def factory():
            source = FakeSource(scripts[len(made)])
            made.append(source)
            return [source]

        return factory, made

    def test_a_spent_budget_starts_a_fresh_leg_that_resumes_at_the_cursor(self, db):
        from jobfinder.search import run_search_until_done

        factory, made = self.legs(
            [page(2, page_number=1), RequestBudgetExhausted("budget of 200 spent")],
            [page(2, page_number=2)],
        )
        summary = run_search_until_done(db, factory, spec())

        assert len(made) == 2
        assert made[1].entered_at == (0, 2)  # continued after the last completed page
        assert summary.state == "done"

    def test_a_completed_leg_does_not_start_another(self, db):
        from jobfinder.search import run_search_until_done

        factory, made = self.legs([page(2, page_number=1)], [page(2, page_number=2)])
        run_search_until_done(db, factory, spec())

        assert len(made) == 1

    def test_her_ctrl_c_ends_the_loop(self, db):
        from jobfinder.search import run_search_until_done

        factory, made = self.legs(
            [page(1, page_number=1), KeyboardInterrupt()], [page(1, page_number=2)]
        )
        summary = run_search_until_done(db, factory, spec())

        assert len(made) == 1  # she stopped it; it stays stopped
        assert summary.state == "interrupted"

    def test_a_dead_host_ends_the_loop(self, db):
        from jobfinder.search import run_search_until_done

        factory, made = self.legs(
            [page(1, page_number=1), SourceUnavailable("host refusing")], [page(1, page_number=2)]
        )
        run_search_until_done(db, factory, spec())

        assert len(made) == 1  # retrying a refusing host is what §8 forbids

    def test_a_leg_that_stored_nothing_ends_the_loop(self, db):
        from jobfinder.search import run_search_until_done

        factory, made = self.legs(
            [RequestBudgetExhausted("budget of 200 spent")], [page(1, page_number=1)]
        )
        run_search_until_done(db, factory, spec())

        assert len(made) == 1  # a budget spent on no progress would loop forever

    def test_max_legs_bounds_the_loop(self, db):
        from jobfinder.search import run_search_until_done

        scripts = [
            [page(1, page_number=n), RequestBudgetExhausted("budget of 200 spent")]
            for n in range(1, 6)
        ]
        factory, made = self.legs(*scripts)
        summary = run_search_until_done(db, factory, spec(), max_legs=3)

        assert len(made) == 3
        assert summary.state == "interrupted"  # honest: the search is not finished

    def test_counts_add_up_across_legs(self, db):
        from jobfinder.search import run_search_until_done

        factory, _ = self.legs(
            [page(2, page_number=1), RequestBudgetExhausted("budget of 200 spent")],
            [page(3, page_number=2)],
        )
        summary = run_search_until_done(db, factory, spec())

        assert (summary.found, summary.new, summary.legs) == (5, 5, 2)


def seed_running_run(db, last_progress: datetime):
    stamp = last_progress.strftime("%Y-%m-%d %H:%M:%S")
    db.execute(
        "INSERT INTO runs (kind, state, started_at, last_progress_at)"
        " VALUES ('search', 'running', ?, ?)",
        (stamp, stamp),
    )
    db.commit()


class TestStaleRuns:
    def test_stale_running_run_is_marked_interrupted_on_next_start(self, db):
        old = datetime(2026, 8, 15, 6, 0, 0, tzinfo=UTC)
        seed_running_run(db, old)

        now = old + timedelta(hours=2)
        run_search(db, [FakeSource([page(1, page_number=1)])], spec(), now=now)

        states = [row[0] for row in db.execute("SELECT state FROM runs ORDER BY id")]
        assert states == ["interrupted", "done"]  # the stale one closed, ours finished

    def test_a_run_progressing_within_the_heartbeat_is_not_stale(self, db):
        now = datetime(2026, 8, 16, 8, 0, 0, tzinfo=UTC)
        seed_running_run(db, now - timedelta(seconds=30))
        run_search(db, [FakeSource([page(1, page_number=1)])], spec(), now=now)
        states = [row[0] for row in db.execute("SELECT state FROM runs ORDER BY id")]
        assert states == ["running", "done"]  # fresh one untouched, ours finished


class TestPerSourceCounts:
    """One line per source in her summary — so counts must exist per source."""

    def test_each_source_gets_its_own_counts(self, db):
        ba = FakeSource([page(3, page_number=1)], source="BA")
        an = FakeSource([page(2, page_number=1, source="AN")], source="AN")
        summary = run_search(db, [ba, an], spec())

        assert summary.per_source["BA"].found == 3
        assert summary.per_source["BA"].new == 3
        assert summary.per_source["AN"].found == 2
        assert summary.per_source["AN"].new == 2

    def test_a_failing_source_lands_in_its_own_counts_and_the_run_continues(self, db):
        broken = FakeSource([SourceUnavailable("arbeitnow is down")], source="AN")
        healthy = FakeSource([page(2, page_number=1)], source="BA")
        summary = run_search(db, [broken, healthy], spec())

        assert summary.per_source["AN"].found == 0
        assert summary.per_source["AN"].errors  # the failure belongs to AN, not the run
        assert summary.per_source["BA"].found == 2  # and BA still ran

    def test_counts_add_up_across_legs_per_source(self, db):
        from jobfinder.search import run_search_until_done

        made: list[FakeSource] = []

        def factory():
            source = FakeSource(
                [
                    page(2, page_number=len(made) + 1),
                    RequestBudgetExhausted("budget of 200 spent"),
                ]
                if len(made) < 2
                else [page(1, page_number=3)]
            )
            made.append(source)
            return [source]

        summary = run_search_until_done(db, factory, spec())

        assert summary.per_source["BA"].found == 5  # 2 + 2 + 1 across three legs
        assert summary.per_source["BA"].new == 5


class CountingSource(FakeSource):
    """Serves canned pages and counts what its detail fetches would have cost."""

    def __init__(self, pages, source: str = "BA"):
        super().__init__(pages, source)
        self.details = 0

    def fetch_detail(self, posting: RawPosting) -> RawPosting:
        self.details += 1
        return dataclasses.replace(posting, description="Die vollständige Anzeige.")


class TestDetailFetches:
    """A detail fetch is a request at 3–4 s spacing — the dominant cost of a run.

    Re-running a search must not pay it again for jobs already stored: the
    re-run rule only moves `last_seen_at`, so the answer would be thrown away.
    """

    def test_new_postings_get_their_detail_fetched(self, db):
        source = CountingSource([page(3, page_number=1)])
        run_search(db, [source], spec())
        assert source.details == 3

    def test_a_rerun_fetches_no_details_for_jobs_already_known(self, db):
        run_search(db, [CountingSource([page(3, page_number=1)])], spec())

        again = CountingSource([page(3, page_number=1)])
        summary = run_search(db, [again], spec())

        assert again.details == 0  # three requests, and three seconds, saved
        assert summary.duplicates == 3
        assert db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 3

    def test_skipping_the_fetch_still_moves_last_seen_at(self, db):
        from jobfinder.store.jobs import upsert_job

        for known in page(2, page_number=1).postings:
            upsert_job(db, known, now="2026-08-01 00:00:00")

        source = CountingSource([page(2, page_number=1)])
        run_search(db, [source], spec())

        stamps = {row[0] for row in db.execute("SELECT last_seen_at FROM jobs")}
        assert stamps != {"2026-08-01 00:00:00"}  # the re-run rule is unchanged
        assert source.details == 0

    def test_only_the_postings_that_are_new_cost_a_fetch(self, db):
        run_search(db, [CountingSource([page(2, page_number=1)])], spec())

        mixed = CountingSource(
            [
                PageResult(
                    source="BA",
                    query_index=0,
                    page=1,
                    postings=[posting("0-1-0"), posting("fresh")],
                )
            ]
        )
        run_search(db, [mixed], spec())

        assert mixed.details == 1  # only the posting the database had never seen

    def test_a_posting_that_arrives_with_its_text_is_never_fetched(self, db):
        complete = dataclasses.replace(posting(1), description="Schon vollständig.")
        source = CountingSource(
            [PageResult(source="BA", query_index=0, page=1, postings=[complete])]
        )
        run_search(db, [source], spec())
        assert source.details == 0


class TestParallelSources:
    """§8 rule 2: different hosts at the same time, one host never twice at once.

    Four scrapers on four hosts is the case this exists for — serial, that is
    the sum of their pacing; in parallel it is the slowest one.
    """

    class BlockingSource(FakeSource):
        """Waits until released, so overlap can be observed rather than timed."""

        def __init__(self, pages, source, started, release):
            super().__init__(pages, source)
            self._started = started
            self._release = release

        def search_pages(self, spec, *, start_query_index=0, start_page=1):
            self._started.set()
            self._release.wait(timeout=5)
            yield from super().search_pages(
                spec, start_query_index=start_query_index, start_page=start_page
            )

    def test_two_different_hosts_are_fetched_at_the_same_time(self, db, tmp_path):
        import threading

        started_a, started_b = threading.Event(), threading.Event()
        release = threading.Event()
        first = self.BlockingSource([page(1, page_number=1, source="KA")], "KA", started_a, release)
        second = self.BlockingSource(
            [page(1, page_number=1, source="XI")], "XI", started_b, release
        )

        def run():
            # One connection per thread, including this one — the fixture's
            # belongs to the main thread (§8 rule 2).
            own = connect(tmp_path / "jobfinder.db")
            try:
                run_search(own, [first, second], spec(), db_path=tmp_path / "jobfinder.db")
            finally:
                own.close()

        worker = threading.Thread(target=run)
        worker.start()
        try:
            # Serially, the second source could not have started before the
            # first finished — and the first cannot finish until released.
            assert started_a.wait(timeout=5)
            assert started_b.wait(timeout=5), "the second source waited its turn"
        finally:
            release.set()
            worker.join(timeout=10)

    def test_every_posting_still_lands_exactly_once(self, db, tmp_path):
        sources = [
            FakeSource([page(3, page_number=1, source=code)], source=code)
            for code in ("BA", "AN", "KA", "XI")
        ]
        summary = run_search(db, sources, spec(), db_path=tmp_path / "jobfinder.db")

        assert summary.found == 12
        assert db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 12
        for code in ("BA", "AN", "KA", "XI"):
            assert summary.per_source[code].found == 3

    def test_one_source_failing_costs_only_its_own_results(self, db, tmp_path):
        broken = FakeSource([SourceUnavailable("kleinanzeigen is down")], source="KA")
        healthy = FakeSource([page(2, page_number=1)], source="BA")

        summary = run_search(db, [broken, healthy], spec(), db_path=tmp_path / "jobfinder.db")

        assert summary.per_source["BA"].found == 2
        assert summary.per_source["KA"].errors
        assert db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 2


class TestSourceHealth:
    """§8 rule 7: a source that keeps refusing sits the next run out.

    Without this a blocked board costs her minutes of timeouts on every run,
    for nothing, until somebody edits config.yaml.
    """

    def fail_a_source(self, db, times: int, source: str = "SS"):
        for _ in range(times):
            broken = FakeSource([SourceUnavailable(f"{source} kept refusing")], source=source)
            run_search(db, [broken], spec())

    def test_a_failing_source_is_counted_towards_its_health(self, db):
        from jobfinder.store.health import cooling_off

        self.fail_a_source(db, 2)

        assert (
            db.execute(
                "SELECT consecutive_failures FROM source_state WHERE source = 'SS'"
            ).fetchone()[0]
            == 2
        )
        assert cooling_off(db, "SS") is None  # two is not three

    def test_three_consecutive_failures_disable_the_source(self, db):
        from jobfinder.store.health import cooling_off

        self.fail_a_source(db, 3)

        assert cooling_off(db, "SS") is not None

    def test_disabled_source_is_skipped_on_the_next_run_until_reset(self, db):
        self.fail_a_source(db, 3)

        fourth = FakeSource([page(2, page_number=1, source="SS")], source="SS")
        summary = run_search(db, [fourth], spec())

        assert fourth.entered == []  # not asked at all
        assert "paused until" in summary.per_source["SS"].errors[0]

    def test_a_healthy_source_in_the_same_run_is_untouched(self, db):
        self.fail_a_source(db, 3)

        cooling = FakeSource([page(1, page_number=1, source="SS")], source="SS")
        healthy = FakeSource([page(2, page_number=1)], source="BA")
        summary = run_search(db, [cooling, healthy], spec())

        assert cooling.entered == []
        assert summary.per_source["BA"].found == 2

    def test_a_good_page_clears_the_count(self, db):
        self.fail_a_source(db, 2)
        run_search(db, [FakeSource([page(1, page_number=1, source="SS")], source="SS")], spec())

        assert (
            db.execute(
                "SELECT consecutive_failures FROM source_state WHERE source = 'SS'"
            ).fetchone()[0]
            == 0
        )

    def test_her_ctrl_c_is_not_held_against_the_source(self, db):
        # She stopped it. That says nothing about whether the site answers.
        run_search(db, [FakeSource([page(1, page_number=1), KeyboardInterrupt()])], spec())

        row = db.execute(
            "SELECT consecutive_failures FROM source_state WHERE source = 'BA'"
        ).fetchone()
        assert row is None or row[0] == 0


class TestSummaryReconciliation:
    """Her summary lines are only worth reading if they match what was stored.

    The mixed run below is the realistic one: two sources that both find the
    same ad, and a third that is down.
    """

    def twin(self, source: str, n: int) -> RawPosting:
        """One ad as two sites list it — same identity, different job_id."""
        return RawPosting(
            job_id=f"{source}:{n}",
            source=source,
            source_id=str(n),
            title="Aushilfe Verkauf (m/w/d)",
            company="Bäckerei Müller",
            city="Ingolstadt" if source == "AN" else "Ingolstadt, Donau",
        )

    def mixed_run(self, db):
        ba = FakeSource(
            [
                PageResult(
                    source="BA",
                    query_index=0,
                    page=1,
                    postings=[posting(1), self.twin("BA", 7)],
                )
            ],
            source="BA",
        )
        an = FakeSource(
            [
                PageResult(
                    source="AN",
                    query_index=0,
                    page=1,
                    postings=[posting(1, "AN"), self.twin("AN", 9)],
                )
            ],
            source="AN",
        )
        broken = FakeSource([SourceUnavailable("stepstone is down")], source="SS")
        return run_search(db, [ba, an, broken], spec())

    def test_run_summary_counts_match_the_database(self, db):
        summary = self.mixed_run(db)

        stored = {
            row["source"]: row["rows"]
            for row in db.execute("SELECT source, COUNT(*) AS rows FROM jobs GROUP BY source")
        }
        for source, counts in summary.per_source.items():
            assert counts.new == stored.get(source, 0), source

    def test_found_is_new_plus_duplicates_for_every_source(self, db):
        summary = self.mixed_run(db)
        for source, counts in summary.per_source.items():
            assert counts.found == counts.new + counts.duplicates, source

    def test_the_ad_both_sources_found_is_stored_once_and_counted_twice(self, db):
        summary = self.mixed_run(db)

        assert summary.per_source["BA"].new == 2
        assert summary.per_source["AN"].found == 2
        assert summary.per_source["AN"].new == 1  # the twin merged into BA's row
        assert summary.per_source["AN"].duplicates == 1
        assert db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 3

    def test_a_source_that_never_answered_reconciles_at_zero(self, db):
        summary = self.mixed_run(db)

        assert summary.per_source["SS"].found == 0
        assert summary.per_source["SS"].errors
        assert db.execute("SELECT COUNT(*) FROM jobs WHERE source = 'SS'").fetchone()[0] == 0

    def test_the_run_row_totals_match_the_summary(self, db):
        summary = self.mixed_run(db)
        row = run_row(db, summary.run_id)

        assert row["found_count"] == sum(c.found for c in summary.per_source.values())
        assert row["new_count"] == sum(c.new for c in summary.per_source.values())
        assert row["duplicate_count"] == sum(c.duplicates for c in summary.per_source.values())
        assert row["new_count"] == db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]


class TestCounts:
    def test_rerun_counts_duplicates_without_storing_twice(self, db):
        same_page = page(3, page_number=1)
        first = run_search(db, [FakeSource([same_page])], spec())
        again = run_search(db, [FakeSource([page(3, page_number=1)])], spec())

        assert (first.new, first.duplicates) == (3, 0)
        assert (again.new, again.duplicates) == (0, 3)
        assert db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 3

    def test_summary_exposes_the_run_id(self, db):
        summary = run_search(db, [FakeSource([page(1, page_number=1)])], spec())
        assert isinstance(summary, SearchSummary)
        assert run_row(db, summary.run_id) is not None
