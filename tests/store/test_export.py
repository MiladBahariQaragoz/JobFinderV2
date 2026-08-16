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
