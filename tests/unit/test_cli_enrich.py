"""`jobfinder enrich` — the command that turns her store into something readable.

The narration is the feature here as much as the enrichment: §10 says a wait
over a second is narrated with real counts, and §7 says a spent free tier is a
sentence she can act on, never a traceback.
"""

from __future__ import annotations

import csv

import pytest
import yaml
from llmpool import PoolExhausted
from tests.fakes import FakePool

from jobfinder.cli import main
from jobfinder.sources.base import RawPosting
from jobfinder.store.db import connect, migrate
from jobfinder.store.jobs import upsert_job

POOL_YAML = {
    "basics": {
        "name": "Jane Doe",
        "email": "j@example.com",
        "location": "Neuburg an der Donau, Germany",
        "phone": "+49 172 0000000",
    },
    "skills": {"Programming Languages": ["Python", "MATLAB"]},
    "languages": [{"name": "English", "level": "C1"}, {"name": "German", "level": "A2"}],
}


def answer(**overrides) -> dict:
    values = {
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
    values.update(overrides)
    return values


@pytest.fixture
def root(tmp_path):
    """A project root with her pool.yaml and a database holding stored jobs."""
    (tmp_path / "pool.yaml").write_text(
        yaml.safe_dump(POOL_YAML, allow_unicode=True), encoding="utf-8", newline="\n"
    )
    return tmp_path


def store_jobs(root, count: int) -> None:
    connection = connect(root / "data" / "jobfinder.db")
    migrate(connection)
    for index in range(count):
        upsert_job(
            connection,
            RawPosting(
                job_id=f"BA:{index:03d}",
                source="BA",
                source_id=f"{index:03d}",
                title=f"Aushilfe Bäckerei {index} (m/w/d)",
                company="Bäckerei Musterle",
                city="Ingolstadt",
                description=(
                    f"Wir suchen eine Aushilfe für Filiale {index}. "
                    "Gute Deutschkenntnisse in Wort und Schrift sind erforderlich."
                ),
            ),
        )
    connection.close()


def run(root, pool, *extra):
    return main(["enrich", "--root", str(root), *extra], _pool_factory=lambda: pool)


def csv_rows(root):
    path = root / "data" / "jobs-enriched.csv"
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig", newline="") as handle:
        return list(csv.reader(handle))


class TestARun:
    def test_it_enriches_the_stored_jobs_and_says_how_many(self, root, capsys):
        store_jobs(root, 3)

        exit_code = run(root, FakePool([answer()] * 3))

        out = capsys.readouterr().out
        assert exit_code == 0
        assert "3" in out
        assert "explained" in out.lower()

    def test_progress_names_the_job_it_is_working_through(self, root, capsys):
        store_jobs(root, 2)

        run(root, FakePool([answer()] * 2))

        out = capsys.readouterr().out
        assert "1 of 2" in out
        assert "2 of 2" in out
        assert "Aushilfe Bäckerei 0" in out

    def test_it_writes_the_csv_and_says_where_it_is(self, root, capsys):
        store_jobs(root, 2)

        run(root, FakePool([answer()] * 2))

        out = capsys.readouterr().out
        assert "jobs-enriched.csv" in out
        assert len(csv_rows(root)) == 3  # header + two

    def test_the_csv_holds_the_english_summary_she_reads(self, root):
        store_jobs(root, 1)

        run(root, FakePool([answer()]))

        rows = csv_rows(root)
        assert rows[1][rows[0].index("summary_en")] == (
            "A weekend job at a bakery counter in Ingolstadt."
        )


class TestNothingToDo:
    def test_a_second_run_says_everything_is_explained_and_spends_nothing(self, root, capsys):
        store_jobs(root, 2)
        run(root, FakePool([answer()] * 2))
        capsys.readouterr()

        pool = FakePool([])
        exit_code = run(root, pool)

        out = capsys.readouterr().out
        assert exit_code == 0
        assert pool.calls == []
        assert "already explained" in out.lower() or "nothing" in out.lower()

    def test_an_empty_store_says_to_search_first_rather_than_failing(self, root, capsys):
        exit_code = main(["enrich", "--root", str(root)], _pool_factory=lambda: FakePool([]))

        out = capsys.readouterr().out
        assert exit_code == 0
        assert "jobfinder search" in out


class TestLimitsAndForce:
    def test_limit_stops_after_that_many_jobs(self, root, capsys):
        store_jobs(root, 5)

        run(root, FakePool([answer()] * 5), "--limit", "2")

        out = capsys.readouterr().out
        assert len(csv_rows(root)) == 3  # header + two
        assert "3" in out  # and it says how many are still waiting

    def test_force_re_explains_a_job_already_done(self, root, capsys):
        store_jobs(root, 1)
        run(root, FakePool([answer()]))
        capsys.readouterr()

        pool = FakePool([answer(fit_score=91)])
        run(root, pool, "--force")

        rows = csv_rows(root)
        assert len(pool.calls) == 1
        assert rows[1][rows[0].index("fit_score")] == "91"


class TestWhenThingsGoWrong:
    def test_a_spent_quota_is_a_sentence_she_can_act_on(self, root, capsys):
        store_jobs(root, 5)

        exit_code = run(root, FakePool([answer(), PoolExhausted("daily cap reached")]))

        out = capsys.readouterr().out
        assert exit_code == 0  # what it did is hers to keep, not an error
        assert "quota" in out.lower()
        assert "jobfinder enrich" in out  # how to pick up where it stopped
        assert "Traceback" not in out

    def test_the_answers_it_did_get_are_still_on_disk_after_a_spent_quota(self, root):
        store_jobs(root, 5)

        run(root, FakePool([answer(), PoolExhausted("daily cap reached")]))

        assert len(csv_rows(root)) == 2  # header + the one that landed

    def test_a_missing_pool_yaml_is_explained_not_raised(self, tmp_path, capsys):
        store_jobs(tmp_path, 1)

        exit_code = main(["enrich", "--root", str(tmp_path)], _pool_factory=lambda: FakePool([]))

        out = capsys.readouterr().out
        assert exit_code == 1
        assert "pool.yaml" in out
        assert "Traceback" not in out

    def test_a_refused_answer_is_reported_without_ending_the_run(self, root, capsys):
        store_jobs(root, 2)

        exit_code = run(root, FakePool([answer(german_level="B2", german_evidence=""), answer()]))

        out = capsys.readouterr().out
        assert exit_code == 0
        assert len(csv_rows(root)) == 2  # header + the good one
        assert "1" in out


class TestHerPrivacy:
    def test_the_prompt_never_carries_her_address_email_or_phone(self, root):
        store_jobs(root, 1)
        pool = FakePool([answer()])

        run(root, pool)

        for secret in ("j@example.com", "Neuburg an der Donau", "+49 172", "Jane Doe"):
            assert secret not in pool.calls[0]
