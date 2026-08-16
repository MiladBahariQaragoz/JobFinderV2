"""`jobs-init.csv` — the file she opens in Excel every morning.

§5 fixes the encoding rules (utf-8-sig, `newline=""`), §9 the atomicity (tmp +
os.replace). Both are tests here because they fail silently otherwise: Excel
mangles umlauts, and a crash mid-export would leave a half file.
"""

from __future__ import annotations

import csv

import pytest

from jobfinder.sources.base import RawPosting
from jobfinder.store.db import connect, migrate
from jobfinder.store.export import COLUMNS, export_jobs_init
from jobfinder.store.jobs import upsert_job


@pytest.fixture
def db(tmp_path):
    connection = connect(tmp_path / "jobfinder.db")
    migrate(connection)
    yield connection
    connection.close()


def seed(connection, **overrides) -> RawPosting:
    values = dict(
        job_id="BA:11119-4913285274-S",
        source="BA",
        source_id="11119-4913285274-S",
        title="Küchenhilfe (m/w/d)",
        company="Bäckerei Müller & Söhne",
        city="Ingolstadt",
        plz="85051",
        description="Wir suchen eine Kraft für das Wochenende an unserer Theke.",
    )
    values.update(overrides)
    posting = RawPosting(**values)
    upsert_job(connection, posting, now="2026-08-16 08:00:00")
    return posting


def read_rows(path):
    with open(path, encoding="utf-8-sig", newline="") as handle:
        return list(csv.reader(handle))


class TestEncoding:
    def test_file_starts_with_the_bom(self, db, tmp_path):
        seed(db)
        target = tmp_path / "jobs-init.csv"
        export_jobs_init(db, target)
        assert target.read_bytes().startswith(b"\xef\xbb\xbf")

    def test_umlauts_and_ampersand_survive_a_round_trip(self, db, tmp_path):
        seed(db)
        target = tmp_path / "jobs-init.csv"
        export_jobs_init(db, target)
        rows = read_rows(target)
        header = rows[0]
        assert rows[1][header.index("company")] == "Bäckerei Müller & Söhne"
        assert rows[1][header.index("title")] == "Küchenhilfe (m/w/d)"

    def test_no_blank_lines_on_windows(self, db, tmp_path):
        seed(db, job_id="BA:a", source_id="a", company="Bäckerei Eins")
        seed(db, job_id="BA:b", source_id="b", company="Bäckerei Zwei")
        seed(db, job_id="BA:c", source_id="c", company="Bäckerei Drei")
        target = tmp_path / "jobs-init.csv"
        export_jobs_init(db, target)

        raw = target.read_bytes().decode("utf-8-sig")
        assert raw.endswith("\r\n")  # csv's Windows line ending, once
        lines = raw.split("\r\n")
        assert lines[-1] == ""  # the single trailing newline, nothing more
        assert "" not in lines[:-1]  # no blank line between rows


class TestColumns:
    def test_header_is_exactly_the_section_5_column_set(self, db, tmp_path):
        seed(db)
        target = tmp_path / "jobs-init.csv"
        export_jobs_init(db, target)
        assert read_rows(target)[0] == COLUMNS

    def test_status_column_comes_from_the_status_table(self, db, tmp_path):
        kept = seed(db)
        seed(db, job_id="BA:rejected-1", source_id="rejected-1", company="Anderer Laden")
        db.execute("UPDATE status SET status = 'rejected' WHERE job_id = 'BA:rejected-1'")
        db.commit()

        target = tmp_path / "jobs-init.csv"
        export_jobs_init(db, target)
        header, *body = read_rows(target)
        by_job = {row[header.index("job_id")]: row for row in body}

        assert by_job[kept.job_id][header.index("status")] == "new"
        assert by_job["BA:rejected-1"][header.index("status")] == "rejected"

    def test_every_job_row_is_exported_sorted_by_job_id(self, db, tmp_path):
        seed(db, job_id="BA:c", source_id="c", company="Bäckerei Drei")
        seed(db, job_id="BA:a", source_id="a", company="Bäckerei Eins")
        seed(db, job_id="BA:b", source_id="b", company="Bäckerei Zwei")
        target = tmp_path / "jobs-init.csv"
        written = export_jobs_init(db, target)
        assert written == 3
        header, *body = read_rows(target)
        assert [row[header.index("job_id")] for row in body] == ["BA:a", "BA:b", "BA:c"]

    def test_also_seen_on_is_exported_after_source_url(self, db, tmp_path):
        seed(db)
        seed(
            db,
            job_id="AN:werkstudent-kueche-1",
            source="AN",
            source_id="werkstudent-kueche-1",
            title="Küchenhilfe (m/f/d)",  # same normalised identity → merge
        )
        target = tmp_path / "jobs-init.csv"
        export_jobs_init(db, target)
        header, *body = read_rows(target)
        assert header[header.index("source_url") + 1] == "also_seen_on"
        assert body[0][header.index("also_seen_on")] == "AN"
        assert body[0][header.index("source")] == "BA"


class TestAtomicity:
    def test_crash_mid_export_leaves_the_previous_csv_intact(self, db, tmp_path, monkeypatch):
        from jobfinder.store import export as export_module

        seed(db, job_id="BA:safe-1", source_id="safe-1")
        target = tmp_path / "jobs-init.csv"
        export_jobs_init(db, target)
        good_bytes = target.read_bytes()

        seed(db, job_id="BA:late-1", source_id="late-1")

        class Exploder:
            """csv.writer stand-in that dies on the second data row."""

            calls = 0

            def __init__(self, handle, **kwargs):
                self._handle = handle

            def writerow(self, row):
                type(self).calls += 1
                if type(self).calls >= 3:  # header + first row written
                    raise RuntimeError("laptop lid closed mid-export")
                csv.writer(self._handle).writerow(row)

        monkeypatch.setattr(export_module.csv, "writer", Exploder)

        with pytest.raises(RuntimeError, match="laptop lid"):
            export_jobs_init(db, target)

        assert target.read_bytes() == good_bytes  # the old file, unharmed
        assert not list(tmp_path.glob("*.tmp"))  # and no half-written leftovers


# --- Phase 7: jobs-enriched.csv ----------------------------------------------


ANSWER = {
    "category": "retail",
    "seniority": "entry",
    "skills_required": ["customer service", "cash handling"],
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


def enriched_line(job_id="BA:1", **overrides):
    from jobfinder.enrich.fields import enriched_row

    fields = {
        "job_id": job_id,
        "prompt_version": "v1",
        "provider_used": "groq",
        "enriched_at": "2026-08-16 09:30:00",
    }
    fields.update(overrides)
    return enriched_row(ANSWER, **fields)


class TestAppendingOneEnrichedRow:
    """§9: the CSV grows as each answer lands, not once at the end.

    She can open the file while a run is still going, and an interrupt leaves a
    complete readable file rather than nothing.
    """

    def test_the_first_append_writes_the_header_too(self, tmp_path):
        from jobfinder.enrich.fields import ENRICHED_COLUMNS
        from jobfinder.store.export import append_enriched_row

        target = tmp_path / "jobs-enriched.csv"
        append_enriched_row(target, enriched_line())

        rows = read_rows(target)
        assert rows[0] == ENRICHED_COLUMNS
        assert rows[1][0] == "BA:1"

    def test_a_second_append_does_not_repeat_the_header(self, tmp_path):
        from jobfinder.store.export import append_enriched_row

        target = tmp_path / "jobs-enriched.csv"
        append_enriched_row(target, enriched_line("BA:1"))
        append_enriched_row(target, enriched_line("BA:2"))

        rows = read_rows(target)
        assert len(rows) == 3
        assert [row[0] for row in rows[1:]] == ["BA:1", "BA:2"]

    def test_an_appended_file_carries_the_bom_and_survives_umlauts(self, tmp_path):
        from jobfinder.store.export import append_enriched_row

        target = tmp_path / "jobs-enriched.csv"
        append_enriched_row(target, enriched_line())

        assert target.read_bytes().startswith(b"\xef\xbb\xbf")
        header = read_rows(target)[0]
        assert read_rows(target)[1][header.index("german_evidence")] == (
            "Gute Deutschkenntnisse in Wort und Schrift"
        )

    def test_no_blank_lines_between_appended_rows_on_windows(self, tmp_path):
        from jobfinder.store.export import append_enriched_row

        target = tmp_path / "jobs-enriched.csv"
        for index in range(3):
            append_enriched_row(target, enriched_line(f"BA:{index}"))

        assert b"\r\r\n" not in target.read_bytes()
        assert len(read_rows(target)) == 4


class TestFullEnrichedExport:
    def test_the_export_rewrites_the_file_sorted_and_deduplicated(self, db, tmp_path):
        from jobfinder.store.enrichment import save_enrichment
        from jobfinder.store.export import append_enriched_row, export_jobs_enriched

        seed(db, job_id="BA:b", source_id="b")
        seed(db, job_id="BA:a", source_id="a")
        save_enrichment(db, "BA:b", "v1", "hash-b", ANSWER, provider_used="groq")
        save_enrichment(db, "BA:a", "v1", "hash-a", ANSWER, provider_used="groq")

        target = tmp_path / "jobs-enriched.csv"
        # The appended file holds arrival order, with a duplicate from a re-run.
        for job_id in ("BA:b", "BA:a", "BA:b"):
            append_enriched_row(target, enriched_line(job_id))

        written = export_jobs_enriched(db, target, "v1")

        rows = read_rows(target)
        assert written == 2
        assert [row[0] for row in rows[1:]] == ["BA:a", "BA:b"]

    def test_the_export_carries_the_provider_and_the_stamp_from_the_database(self, db, tmp_path):
        from jobfinder.store.enrichment import save_enrichment
        from jobfinder.store.export import export_jobs_enriched

        seed(db, job_id="BA:a", source_id="a")
        save_enrichment(
            db, "BA:a", "v1", "hash-a", ANSWER, provider_used="cerebras", now="2026-08-16 10:00:00"
        )

        target = tmp_path / "jobs-enriched.csv"
        export_jobs_enriched(db, target, "v1")

        rows = read_rows(target)
        header = rows[0]
        assert rows[1][header.index("provider_used")] == "cerebras"
        assert rows[1][header.index("enriched_at")] == "2026-08-16 10:00:00"

    def test_an_export_with_nothing_enriched_still_writes_the_header(self, db, tmp_path):
        from jobfinder.enrich.fields import ENRICHED_COLUMNS
        from jobfinder.store.export import export_jobs_enriched

        target = tmp_path / "jobs-enriched.csv"
        written = export_jobs_enriched(db, target, "v1")

        assert written == 0
        assert read_rows(target)[0] == ENRICHED_COLUMNS

    def test_a_crash_mid_export_leaves_the_previous_enriched_csv_intact(
        self, db, tmp_path, monkeypatch
    ):
        from jobfinder.store import export as export_module
        from jobfinder.store.enrichment import save_enrichment
        from jobfinder.store.export import export_jobs_enriched

        seed(db, job_id="BA:a", source_id="a")
        save_enrichment(db, "BA:a", "v1", "hash-a", ANSWER)
        target = tmp_path / "jobs-enriched.csv"
        export_jobs_enriched(db, target, "v1")
        before = target.read_bytes()

        def explode(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(export_module.os, "replace", explode)
        with pytest.raises(OSError):
            export_jobs_enriched(db, target, "v1")

        assert target.read_bytes() == before
        assert not list(tmp_path.glob("*.tmp"))
