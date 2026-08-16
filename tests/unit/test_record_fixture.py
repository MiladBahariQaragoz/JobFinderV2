import json

from scripts.record_fixture import is_html, save_fixture


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


# -- --html: recognising a page before trusting it as a fixture ------------------


def test_is_html_recognises_real_pages():
    assert is_html(b"<!DOCTYPE html><html lang=de>")
    assert is_html(b"  \n<html><body>Aushilfe K\xfcche</body></html>")
    # Kleinanzeigen serves no doctype declaration first — the tag itself is enough.
    assert is_html(b'<div id="viewad-title">')


def test_is_html_rejects_json_xml_and_error_bodies():
    assert not is_html(b'{"data": []}')
    assert not is_html(b"<?xml version='1.0'?><rss></rss>")
    assert not is_html(b"403 Forbidden")
    assert not is_html(b"")


def test_html_flag_fails_loudly_when_the_body_is_not_a_page(capsys, tmp_path):
    """Recording a block page as `--html` would hide the failure from the adapter tests."""
    from scripts.record_fixture import record

    code = record(
        source="indeed",
        name="search.html",
        url="https://de.indeed.com/jobs?q=Aushilfe",
        content=b"403 Forbidden",
        html=True,
        fixture_root=tmp_path,
    )

    assert code == 1
    out = capsys.readouterr().out
    assert "not HTML" in out
    assert not (tmp_path / "indeed" / "search.html").exists()


def test_html_flag_saves_a_real_page(tmp_path, monkeypatch):
    from scripts.record_fixture import record

    monkeypatch.setattr("scripts.record_fixture.fetch", lambda url, headers: b"<html></html>")
    code = record(
        source="xing",
        name="list.html",
        url="https://www.xing.com/jobs/aushilfe-ingolstadt",
        content=None,
        html=True,
        fixture_root=tmp_path,
    )

    assert code == 0
    assert (tmp_path / "xing" / "list.html").read_bytes() == b"<html></html>"
