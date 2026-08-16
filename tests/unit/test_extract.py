"""Readable-text extraction for pages the BA API points at indirectly."""

from __future__ import annotations

from jobfinder.sources.extract import extract_readable_text


def test_scripts_and_styles_are_stripped_not_rendered():
    html = (
        "<html><head><style>body{color:red}</style></head><body><script>fetch('/x')</script>"
        "<p>Kellner gesucht für unser Restaurant in der Innenstadt von Ingolstadt.</p>"
        "</body></html>"
    )
    # min_chars lowered: these samples test stripping, not the length threshold
    # (which the too-short tests below cover).
    text = extract_readable_text(html, min_chars=10)
    assert "Kellner gesucht" in text
    assert "fetch" not in text
    assert "color" not in text


def test_html_entities_decode_back_into_umlauts():
    text = extract_readable_text(
        "<p>B&auml;ckerei M&uuml;ller &amp; S&ouml;hne sucht eine Kraft f&uuml;r die fr&uuml;he "
        "Schicht an jedem Wochenende.</p>"
    )
    assert text is not None
    assert text.startswith("Bäckerei Müller & Söhne sucht")


def test_whitespace_collapses_but_line_breaks_survive_as_spaces():
    text = extract_readable_text(
        "<div>Ihre\n  Aufgaben:</div><div>-   Spülen der Teller und Tassen in unserer Küche</div>",
        min_chars=10,
    )
    assert text == "Ihre Aufgaben: - Spülen der Teller und Tassen in unserer Küche"


def test_a_page_with_no_real_text_returns_none():
    assert extract_readable_text("<html><body><div></div><span> </span></body></html>") is None


def test_navigation_leftovers_alone_are_too_short_to_count():
    html = "<html><body><nav>Menü Impressum</nav></body></html>"
    assert extract_readable_text(html) is None


def test_a_real_description_is_kept_whole():
    body = "<p>" + "Wir suchen eine Küchenhilfe für unsere Bäckerei. " * 10 + "</p>"
    text = extract_readable_text(body)
    assert text is not None and "Küchenhilfe" in text
