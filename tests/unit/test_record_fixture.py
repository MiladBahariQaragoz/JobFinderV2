import json

from scripts.record_fixture import save_fixture


def test_json_fixture_is_pretty_printed_under_the_source_directory(tmp_path):
    path = save_fixture(
        source="ba",
        name="jobs_werkstudent.json",
        content=b'{"ergebnisliste":[{"stellenangebotsTitel":"Werkstudent"}]}',
        fixture_root=tmp_path,
    )

    assert path == tmp_path / "ba" / "jobs_werkstudent.json"
    text = path.read_text(encoding="utf-8")
    assert text.count("\n") > 1, "JSON fixtures are re-indented so diffs stay readable"
    assert json.loads(text)["ergebnisliste"][0]["stellenangebotsTitel"] == "Werkstudent"


def test_html_fixture_is_written_verbatim(tmp_path):
    html = b"<html><body><h2>Aushilfe Kuche</h2></body></html>"

    path = save_fixture(
        source="kleinanzeigen", name="jobs_page1.html", content=html, fixture_root=tmp_path
    )

    assert path.read_bytes() == html


def test_german_characters_survive_recording(tmp_path):
    path = save_fixture(
        source="ba",
        name="umlauts.json",
        content='{"firma":"Bäckerei Müller & Söhne","ort":"Nürnberg"}'.encode(),
        fixture_root=tmp_path,
    )

    assert json.loads(path.read_text(encoding="utf-8"))["firma"] == "Bäckerei Müller & Söhne"


def test_invalid_json_is_still_saved_so_the_failure_can_be_studied(tmp_path):
    path = save_fixture(
        source="xing", name="broken.json", content=b"<html>403 denied</html>", fixture_root=tmp_path
    )

    assert path.read_bytes() == b"<html>403 denied</html>"
