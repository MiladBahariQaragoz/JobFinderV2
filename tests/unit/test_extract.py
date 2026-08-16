"""Readable-text extraction for pages the BA API points at indirectly."""

from __future__ import annotations

from jobfinder.sources.extract import (
    extract_readable_text,
    html_to_text,
    jsonld_jobpostings,
    looks_like_login_wall,
)


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


# -- JSON-LD JobPosting extraction (Phase 6: scrapers) ---------------------------


def xing_detail(fixture_path) -> str:
    return fixture_path("xing", "detail_aushilfe_einzelhandel.html").read_text(encoding="utf-8")


class TestJsonldJobpostings:
    def test_the_recorded_xing_page_yields_its_jobposting(self, fixture_path):
        postings = jsonld_jobpostings(xing_detail(fixture_path))
        assert len(postings) == 1
        assert postings[0]["title"] == "Aushilfe im Einzelhandel (m/w/d) - Minijob Ingolstadt"

    def test_the_recorded_xing_jobposting_carries_the_fields_we_map(self, fixture_path):
        posting = jsonld_jobpostings(xing_detail(fixture_path))[0]
        assert posting["hiringOrganization"]["name"] == "Walbusch Walter Busch GmbH & Co. KG"
        assert posting["datePosted"]
        assert "Minijob" in posting["description"]

    def test_singular_fields_normalize_one_object_or_a_list(self):
        # schema.org allows both; the recorded Xing page emits jobLocation as
        # a list, so the mapping layer has to take either.
        from jobfinder.sources.extract import first_of

        assert first_of([{"a": 1}, {"a": 2}]) == {"a": 1}
        assert first_of({"a": 1}) == {"a": 1}
        assert first_of(None) is None
        assert first_of([]) is None

    def test_locality_and_employer_helpers_read_both_shapes(self, fixture_path):
        from jobfinder.sources.extract import jobposting_city, jobposting_company

        posting = jsonld_jobpostings(xing_detail(fixture_path))[0]
        assert jobposting_company(posting) == "Walbusch Walter Busch GmbH & Co. KG"
        assert jobposting_city(posting) == "Ingolstadt"  # from the list-shaped jobLocation

    def test_locality_helper_reads_the_singular_shape_too(self):
        from jobfinder.sources.extract import jobposting_city

        posting = {
            "@type": "JobPosting",
            "jobLocation": {"address": {"addressLocality": "Neuburg an der Donau"}},
        }
        assert jobposting_city(posting) == "Neuburg an der Donau"

    def test_a_list_block_and_a_graph_block_both_flatten(self):
        markup = """
        <script type="application/ld+json">[
          {"@type": "WebSite", "url": "https://x"},
          {"@type": "JobPosting", "title": "Küchenhilfe"}
        ]</script>
        <script type="application/ld+json">
          {"@graph": [{"@type": "JobPosting", "title": "Aushilfe"},
                      {"@type": "Organization", "name": "x"}]}
        </script>
        """
        titles = [p["title"] for p in jsonld_jobpostings(markup)]
        assert titles == ["Küchenhilfe", "Aushilfe"]

    def test_unparsable_blocks_are_skipped_not_raised(self):
        markup = (
            '<script type="application/ld+json">{"@type": "JobPosting", "title": '
            "</script>"
            '<script type="application/ld+json">{"@type": "JobPosting", "title": "OK"}</script>'
        )
        assert [p["title"] for p in jsonld_jobpostings(markup)] == ["OK"]

    def test_a_page_without_jobposting_blocks_returns_empty(self, fixture_path):
        list_page = fixture_path("kleinanzeigen", "list_ingolstadt.html").read_text(
            encoding="utf-8"
        )
        assert jsonld_jobpostings(list_page) == []


class TestHtmlToText:
    def test_the_recorded_xing_description_loses_its_markup(self, fixture_path):
        posting = jsonld_jobpostings(xing_detail(fixture_path))[0]
        text = html_to_text(posting["description"])
        assert "<" not in text and "&nbsp;" not in text
        assert "Unsere Zielgruppe kennen und studieren wir genau" in text

    def test_nested_lists_become_readable_lines(self):
        assert html_to_text("<ul><li>Spülen</li><li>Putzen</li></ul>") == "Spülen Putzen"

    def test_entities_decode(self):
        assert html_to_text("<p>f&uuml;r 450&nbsp;&euro;</p>") == "für 450 €"


class TestLoginWall:
    def test_german_login_prompt_is_detected(self):
        assert looks_like_login_wall(
            "<html><body><h1>Bitte melde dich an, um fortzufahren</h1></body></html>"
        )

    def test_english_login_prompt_is_detected(self):
        assert looks_like_login_wall(
            "<html><body><p>Please log in to see this job posting.</p></body></html>"
        )

    def test_a_login_form_action_is_detected_even_with_quiet_copy(self):
        assert looks_like_login_wall(
            '<html><body><form action="https://x.example/login"></form></body></html>'
        )

    def test_the_recorded_xing_page_is_not_a_login_wall(self, fixture_path):
        assert not looks_like_login_wall(xing_detail(fixture_path))

    def test_the_recorded_indeed_block_page_is_not_miscalled_a_login_wall(self, fixture_path):
        body = fixture_path("indeed", "blocked_403.html").read_text(encoding="utf-8")
        assert not looks_like_login_wall(body)
