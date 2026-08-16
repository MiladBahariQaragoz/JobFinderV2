"""One page per job — everything Phase 7 promised her, and her decisions on it.

The page is the product: the English answer, the evidence for the German
level, the fit with its reasons and gaps, how to apply, the original German
behind a collapse, and buttons that survive a restart.
"""

from __future__ import annotations

from tests.web.conftest import enrichment_answer, store_job

from jobfinder.sources.base import RawPosting
from jobfinder.store.db import connect
from jobfinder.store.jobs import upsert_job


class TestThePage:
    def test_job_page_renders_every_enriched_field_present_in_the_row(self, settings, client):
        answer = enrichment_answer(
            category="gastronomy",
            seniority="entry",
            skills_required=["knife skills", "hygiene certificate"],
            skills_nice=["POS tills"],
            german_level="B2",
            german_evidence="Sie sprechen fliessend Deutsch",
            english_sufficient=True,
            employment_type_norm="part-time",
            hours_per_week=20,
            duties_en=["Prep vegetables", "Keep the line clean"],
            requirements_en=["Two evenings a week"],
            summary_en="Kitchen prep at a gastro pub in Ingolstadt, evenings.",
            fit_score=72,
            fit_reasons=["Worked a summer in a kitchen"],
            missing_for_fit=["A hygiene certificate"],
            red_flags=["Unpaid trial day"],
            application_method="portal",
            contact_email="kueche@gastropub.example.de",
            contact_phone="+49 841 555123",
            deadline="2026-09-01",
        )
        connection = connect(settings.db_path)
        try:
            store_job(
                connection,
                job_id="BA:77",
                title="Küchenhilfe Abend",
                description="Sie sprechen fliessend Deutsch. Wir suchen Sie abends.",
                answer=answer,
            )
        finally:
            connection.close()

        body = client.get("/jobs/BA%3A77").text
        for value in (
            "Kitchen prep at a gastro pub in Ingolstadt, evenings.",
            "Prep vegetables",
            "Keep the line clean",
            "Two evenings a week",
            "knife skills",
            "hygiene certificate",
            "POS tills",
            "B2",
            "Sie sprechen fliessend Deutsch",
            "part-time",
            "20",
            "72",
            "Worked a summer in a kitchen",
            "A hygiene certificate",
            "Unpaid trial day",
            "kueche@gastropub.example.de",
            "+49 841 555123",
            "2026-09-01",
            "gastronomy",
            "entry",
        ):
            assert value in body, f"missing on the job page: {value!r}"

    def test_job_page_renders_when_enrichment_is_missing(self, settings, client):
        connection = connect(settings.db_path)
        try:
            store_job(
                connection,
                job_id="BA:88",
                title="Noch nicht erklaert",
                description="Einjob ohne Antwort.",
            )
        finally:
            connection.close()

        response = client.get("/jobs/BA%3A88")
        assert response.status_code == 200  # never a 500 on a fresh job
        assert "Noch nicht erklaert" in response.text
        assert "Not explained yet" in response.text
        assert "jobfinder enrich" in response.text  # the one thing to do next

    def test_unknown_job_is_a_readable_404(self, client):
        response = client.get("/jobs/BA%3Anope")
        assert response.status_code == 404
        assert "No job" in response.text

    def test_german_original_is_present_but_collapsed(self, settings, client):
        connection = connect(settings.db_path)
        try:
            store_job(
                connection,
                job_id="BA:99",
                title="Original dabei",
                description="Bäckerei Müller & Söhne sucht eine Aushilfe mit Geduld.",
            )
        finally:
            connection.close()

        body = client.get("/jobs/BA%3A99").text
        # the text is there — the ampersand arrives HTML-escaped
        assert "Bäckerei Müller" in body
        assert "sucht eine Aushilfe mit Geduld" in body
        assert "<details" in body  # ...inside a collapsed block, not the flow


class TestHerActions:
    def post_status(self, client, job_id: str, status: str):
        return client.post(f"/jobs/{job_id}/status", data={"status": status}, follow_redirects=True)

    def test_mark_applied_persists_and_sets_applied_on_date(self, settings, client):
        response = self.post_status(client, "BA:1", "applied")
        assert response.status_code == 200
        assert "applied" in response.text

        connection = connect(settings.db_path)
        try:
            row = connection.execute(
                "SELECT status, applied_on FROM status WHERE job_id = 'BA:1'"
            ).fetchone()
        finally:
            connection.close()
        assert row["status"] == "applied"
        assert row["applied_on"]  # the date she sent it — the page reads it back

        assert "applied on" in client.get("/jobs/BA%3A1").text

    def test_delete_soft_deletes_and_survives_a_new_search_run(self, settings, client):
        self.post_status(client, "BA:1", "deleted")
        assert "Gelöscht hier" not in client.get("/").text  # gone from the list
        assert "Aushilfe Verkauf Minijob" not in client.get("/").text

        # A later search finds the same job again: the re-run rule moves
        # last_seen_at and nothing else — her 'deleted' must survive it.
        connection = connect(settings.db_path)
        try:
            upsert_job(
                connection,
                RawPosting(
                    job_id="BA:1",
                    source="BA",
                    source_id="1",
                    title="Aushilfe Verkauf Minijob",
                ),
            )
            status_row = connection.execute(
                "SELECT status FROM status WHERE job_id = 'BA:1'"
            ).fetchone()
        finally:
            connection.close()
        assert status_row["status"] == "deleted"

    def test_notes_are_saved_and_shown_after_reload(self, settings, client):
        client.post(
            "/jobs/BA:1/notes",
            data={"notes": "Called — come by Tuesday with a printed CV"},
            follow_redirects=True,
        )

        body = client.get("/jobs/BA%3A1").text
        assert "Called — come by Tuesday with a printed CV" in body

    def test_every_button_the_page_promises_exists(self, client):
        body = client.get("/jobs/BA%3A1").text
        for label in ("Applied", "Interested", "Not for me", "Delete"):
            assert label in body

    def test_an_invalid_status_is_rejected_with_the_valid_ones(self, client):
        response = client.post(
            "/jobs/BA:1/status", data={"status": "maybe"}, follow_redirects=False
        )
        assert response.status_code in (303, 400)
        connection = connect(client.app.state.settings.db_path)
        try:
            status = connection.execute(
                "SELECT status FROM status WHERE job_id = 'BA:1'"
            ).fetchone()["status"]
        finally:
            connection.close()
        assert status != "maybe"
