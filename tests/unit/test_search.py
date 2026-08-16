"""The search runner — MASTER_PLAN §9's resume contract, in tests.

Whatever kills a run (her Ctrl-C, a dead network, a spent request budget), the
pages already fetched are on disk, the run row says `interrupted` with honest
counts, and `--resume` re-enters at the stored cursor instead of page 1.
"""

from __future__ import annotations

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
    return RawPosting(
        job_id=f"{source}:{n}", source=source, source_id=str(n), title=f"Job {n}", company="ACME"
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
            if isinstance(item, Exception):
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

    def test_failing_source_records_its_error_and_the_run_returns_what_it_has(self, db):
        broken = FakeSource([SourceUnavailable("arbeitnow is down")], source="AN")
        healthy = FakeSource([page(3, page_number=1)], source="BA")
        summary = run_search(db, [broken, healthy], spec())

        assert summary.found == 3  # BA's postings survived AN's failure
        assert summary.new == 3
        assert any("arbeitnow" in error for error in summary.errors)
        assert "AN" in summary.errors[0]  # the error names its source


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
