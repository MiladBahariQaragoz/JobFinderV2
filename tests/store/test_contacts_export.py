"""`contacts.csv` — §5's columns, §5's encoding, §9's atomic replace.

The call-list is the one part of this app she may well use on paper: printed out,
in her hand, beside a phone. So the CSV is not an afterthought here — it is a
delivery format, and Excel has to open it with the umlauts intact on the first
try.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from jobfinder.sources.overpass import Place
from jobfinder.store.contacts import set_contact_notes, set_contact_outcome, upsert_contact
from jobfinder.store.contacts_export import CONTACT_COLUMNS, export_contacts
from jobfinder.store.db import connect, migrate


@pytest.fixture
def db(tmp_path):
    connection = connect(tmp_path / "jobfinder.db")
    migrate(connection)
    yield connection
    connection.close()


def place(osm_id="node/1", name="Bäckerei Müller & Söhne", **overrides) -> Place:
    values = dict(
        contact_id=osm_id,
        name=name,
        kind="bakery",
        city="Neuburg an der Donau",
        street="Färberstraße 12",
        phone="+498431648595",
        email="hallo@baeckerei.example.de",
        website="https://baeckerei.example.de",
        lat=48.7325,
        lon=11.1878,
    )
    values.update(overrides)
    return Place(**values)


def read_csv(path: Path) -> list[list[str]]:
    with open(path, encoding="utf-8-sig", newline="") as handle:
        return list(csv.reader(handle))


class TestTheColumns:
    def test_the_columns_are_the_ones_the_contract_names(self):
        assert CONTACT_COLUMNS == [
            "contact_id",
            "name",
            "kind",
            "city",
            "street",
            "phone",
            "email",
            "website",
            "back_of_house_score",
            "osm_id",
            "first_seen_at",
            "last_contacted_at",
            "outcome",
            "notes",
        ]

    def test_the_export_writes_a_header_and_one_row_per_place(self, db, tmp_path):
        upsert_contact(db, place(), score=85, reason="")
        upsert_contact(db, place(osm_id="node/2", name="Hotel"), score=80, reason="")

        written = export_contacts(db, tmp_path / "contacts.csv")

        rows = read_csv(tmp_path / "contacts.csv")
        assert written == 2
        assert rows[0] == CONTACT_COLUMNS
        assert len(rows) == 3

    def test_the_rows_come_out_best_first(self, db, tmp_path):
        upsert_contact(db, place(osm_id="node/3", name="Bar", kind="bar"), score=20, reason="")
        upsert_contact(db, place(osm_id="node/1", name="Bäckerei"), score=85, reason="")

        export_contacts(db, tmp_path / "contacts.csv")

        rows = read_csv(tmp_path / "contacts.csv")
        assert [row[1] for row in rows[1:]] == ["Bäckerei", "Bar"]


class TestEncoding:
    def test_the_file_is_utf8_with_a_bom(self, db, tmp_path):
        upsert_contact(db, place(), score=85, reason="")

        export_contacts(db, tmp_path / "contacts.csv")

        assert (tmp_path / "contacts.csv").read_bytes().startswith(b"\xef\xbb\xbf")

    def test_umlauts_and_esszet_survive(self, db, tmp_path):
        upsert_contact(db, place(name="Bäckerei Müller & Söhne, Straße"), score=85, reason="")

        export_contacts(db, tmp_path / "contacts.csv")

        rows = read_csv(tmp_path / "contacts.csv")
        assert rows[1][1] == "Bäckerei Müller & Söhne, Straße"

    def test_a_note_with_a_newline_stays_one_row(self, db, tmp_path):
        """`newline=""` is what makes this true on Windows — without it a quoted
        field with a line break becomes two broken rows in Excel."""
        upsert_contact(db, place(), score=85, reason="")
        set_contact_notes(db, "node/1", "Called Tuesday.\nCome by at 9.")

        export_contacts(db, tmp_path / "contacts.csv")

        rows = read_csv(tmp_path / "contacts.csv")
        assert len(rows) == 2
        assert "Come by at 9." in rows[1][-1]


class TestHerColumnsAndAtomicity:
    def test_the_export_carries_her_outcome_and_notes(self, db, tmp_path):
        upsert_contact(db, place(), score=85, reason="")
        set_contact_outcome(db, "node/1", "called", now="2026-08-17 09:00:00")
        set_contact_notes(db, "node/1", "Come by Tuesday")

        export_contacts(db, tmp_path / "contacts.csv")

        row = read_csv(tmp_path / "contacts.csv")[1]
        assert row[CONTACT_COLUMNS.index("outcome")] == "called"
        assert row[CONTACT_COLUMNS.index("notes")] == "Come by Tuesday"
        assert row[CONTACT_COLUMNS.index("last_contacted_at")] == "2026-08-17 09:00:00"

    def test_an_empty_field_is_empty_and_never_the_word_none(self, db, tmp_path):
        upsert_contact(db, place(email=None, website=None), score=85, reason="")

        export_contacts(db, tmp_path / "contacts.csv")

        row = read_csv(tmp_path / "contacts.csv")[1]
        assert row[CONTACT_COLUMNS.index("email")] == ""
        assert "None" not in row

    def test_a_crash_mid_export_leaves_the_previous_file_intact(self, db, tmp_path, monkeypatch):
        upsert_contact(db, place(), score=85, reason="")
        target = tmp_path / "contacts.csv"
        export_contacts(db, target)
        good = target.read_bytes()

        upsert_contact(db, place(osm_id="node/2", name="Zweite"), score=80, reason="")
        import csv as csv_module

        original = csv_module.writer

        def exploding_writer(*args, **kwargs):
            writer = original(*args, **kwargs)

            class Boom:
                def writerow(self, row):
                    if row and row[0] == "contact_id":
                        return writer.writerow(row)
                    raise OSError("disk full")

            return Boom()

        monkeypatch.setattr(csv_module, "writer", exploding_writer)
        with pytest.raises(OSError):
            export_contacts(db, target)

        assert target.read_bytes() == good
        assert not list(tmp_path.glob("*.tmp"))

    def test_an_empty_call_list_writes_a_header_and_nothing_else(self, db, tmp_path):
        written = export_contacts(db, tmp_path / "contacts.csv")

        assert written == 0
        assert read_csv(tmp_path / "contacts.csv") == [CONTACT_COLUMNS]
