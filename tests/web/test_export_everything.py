"""One button that writes every CSV, for the day she wants her work elsewhere.

The three exports already exist and each runs at the end of its own kind of run.
What she has no way to say today is "write all of it out now" — which is what
someone wants when they are about to email a spreadsheet to a friend, or when a
run was interrupted and the file on disk is a page behind the database.
"""

from __future__ import annotations

import csv
import re

from tests.web.conftest import store_job

from jobfinder.store.db import connect, migrate


def read_rows(path):
    with open(path, encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def text_of(html: str) -> str:
    """What the sentence reads like once the markup is gone.

    Numbers live in their own `<span class="num">` (§10's monospace rule), so
    "4 jobs" is four tags apart in the source and one phrase on the screen.
    """
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


def test_export_everything_writes_all_three_csvs(client, seeded):
    response = client.post("/settings/export")

    assert response.status_code == 200
    assert seeded.jobs_init_csv.exists()
    assert seeded.jobs_enriched_csv.exists()
    assert seeded.contacts_csv.exists()


def test_export_everything_reports_what_it_wrote(client, seeded):
    """Five jobs are stored, four of them explained. The fifth is one she
    deleted, and `jobs-init.csv` has always held it — that file is the record of
    what the search found, not of what she kept."""
    body = text_of(client.post("/settings/export").text)

    assert "5 jobs" in body
    assert "4 explained" in body
    assert str(seeded.jobs_init_csv) in body


def test_exporting_an_empty_store_writes_headers_and_says_so(settings, tmp_path):
    from fastapi.testclient import TestClient

    from jobfinder.web.app import create_app

    with TestClient(create_app(settings)) as empty_client:
        body = text_of(empty_client.post("/settings/export").text)

    assert "0 jobs" in body
    assert read_rows(settings.jobs_init_csv) == []


def test_the_export_names_the_folder_she_can_open(client, seeded):
    body = text_of(client.post("/settings/export").text)

    assert str(seeded.data_dir) in body


def test_the_settings_page_offers_the_export(client):
    body = client.get("/settings").text

    assert "/settings/export" in body
    assert "Export everything" in body


def test_the_export_includes_the_call_list(client, seeded):
    """The three CSVs are not all written by the same kind of run, so a store
    with places in it must still get a contacts.csv out of one press."""
    from jobfinder.sources.overpass import Place
    from jobfinder.store.contacts import upsert_contact

    connection = connect(seeded.db_path)
    try:
        migrate(connection)
        upsert_contact(
            connection,
            Place(
                contact_id="node/1",
                name="Bäckerei Müller & Söhne",
                kind="bakery",
                city="Ingolstadt",
                phone="+4984112345",
            ),
            score=90,
            reason="a bakery",
        )
    finally:
        connection.close()

    body = text_of(client.post("/settings/export").text)

    assert "1 place" in body
    assert read_rows(seeded.contacts_csv)[0]["name"] == "Bäckerei Müller & Söhne"


def test_a_job_stored_after_the_last_run_reaches_the_csv(client, seeded):
    connection = connect(seeded.db_path)
    try:
        migrate(connection)
        store_job(connection, job_id="BA:99", title="Späte Aushilfe")
    finally:
        connection.close()

    client.post("/settings/export")

    assert any(row["job_id"] == "BA:99" for row in read_rows(seeded.jobs_init_csv))
