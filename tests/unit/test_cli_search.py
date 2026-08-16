"""`jobfinder search` — dry-run shows the exact requests, runs speak her language."""

from __future__ import annotations

import pytest

from jobfinder.cli import main
from jobfinder.search import SearchSummary
from jobfinder.search_spec import SearchSpec


def no_adapters(_settings):
    """A factory that builds no adapters — the fake runner never needs them."""
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


class TestAutoContinue:
    def test_each_leg_gets_a_freshly_built_client(self, tmp_path):
        # A leg only gets a new budget because it gets a new client.
        built = []

        def client_factory(_settings):
            built.append(object())
            return []

        def runner(connection, adapter_factory, spec, **kwargs):
            adapter_factory()
            adapter_factory()
            return summary()

        main(["search", "--root", str(tmp_path)], _client_factory=client_factory, _runner=runner)
        assert len(built) == 2

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
