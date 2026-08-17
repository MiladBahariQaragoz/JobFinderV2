"""Recovering an email from a website, for the places OSM has no address for.

Ten of Neuburg's places carry a website and neither a phone nor an email. German
law (§5 TMG) requires a business site to publish contact details on an
*Impressum* page, so one fetch per site can turn a row she cannot act on into one
she can.

Two limits, both etiquette (§8) rather than caution: **one page per site**, and a
site that does not answer costs that place and nothing else.
"""

from __future__ import annotations

import pytest

from jobfinder.contacts.imprint import IMPRINT_PATHS, find_email, imprint_email
from jobfinder.sources.http import SourceUnavailable
from jobfinder.sources.overpass import Place

PAGE = """
<!doctype html><html lang="de"><head><title>Impressum</title></head><body>
<h1>Impressum</h1>
<p>Bäckerei Müller &amp; Söhne GmbH<br>Färberstraße 12<br>86633 Neuburg</p>
<p>Telefon: 08431 / 648595<br>
E-Mail: <a href="mailto:info@baeckerei-mueller.de">info@baeckerei-mueller.de</a></p>
<p>Geschäftsführer: Hans Müller</p>
</body></html>
"""


class FakeClient:
    """Answers each GET from a script, recording every URL it was asked for."""

    def __init__(self, answers):
        self.answers = dict(answers)
        self.urls: list[str] = []

    def get(self, url, *, params=None, headers=None):
        self.urls.append(url)
        answer = self.answers.get(url)
        if answer is None:
            raise SourceUnavailable(f"{url} did not answer")
        if isinstance(answer, Exception):
            raise answer

        class Response:
            status = 200
            body = answer.encode("utf-8")
            headers: dict = {}

        return Response()


def place(website="https://baeckerei-mueller.de", email=None) -> Place:
    return Place(
        contact_id="node/1",
        name="Bäckerei Müller & Söhne",
        kind="bakery",
        city="Neuburg an der Donau",
        website=website,
        email=email,
    )


class TestFindingAnAddressInAPage:
    def test_an_email_is_extracted_from_a_saved_imprint_page(self):
        assert find_email(PAGE) == "info@baeckerei-mueller.de"

    def test_a_mailto_link_is_read(self):
        page = '<a href="mailto:kontakt@example.de">schreiben</a>'

        assert find_email(page) == "kontakt@example.de"

    def test_a_plain_address_in_the_text_is_read(self):
        page = "<p>E-Mail: kontakt (at) example (dot) de</p>"

        assert find_email(page) == "kontakt@example.de"

    def test_an_obfuscated_at_sign_is_recovered(self):
        page = "<p>info [at] baeckerei-mueller.de</p>"

        assert find_email(page) == "info@baeckerei-mueller.de"

    def test_a_page_with_no_email_yields_nothing(self):
        page = "<h1>Impressum</h1><p>Telefon: 08431 648595</p>"

        assert find_email(page) is None

    def test_an_image_file_that_looks_like_an_address_is_not_an_email(self):
        page = '<img src="logo@2x.png"><p>kein Kontakt</p>'

        assert find_email(page) is None

    def test_the_first_real_address_wins_over_a_web_designer_credit(self):
        """Imprint pages routinely end with 'Website by …' and that agency's
        address must not become the bakery's."""
        page = (
            '<p>E-Mail: <a href="mailto:info@baeckerei.de">info@baeckerei.de</a></p>'
            '<footer>Umsetzung: <a href="mailto:hallo@webagentur.de">webagentur</a></footer>'
        )

        assert find_email(page) == "info@baeckerei.de"

    def test_umlauts_in_the_page_do_not_break_the_search(self):
        page = "<p>Geschäftsführung: Müller. E-Mail: müller@example.de</p>"

        assert find_email(page) == "müller@example.de"


class TestFetchingIt:
    def test_the_imprint_page_is_found_and_its_email_returned(self):
        client = FakeClient({"https://baeckerei-mueller.de/impressum": PAGE})

        assert imprint_email(client, place()) == "info@baeckerei-mueller.de"

    def test_the_lookup_is_skipped_when_an_email_already_exists(self):
        client = FakeClient({})

        assert imprint_email(client, place(email="already@known.de")) is None
        assert client.urls == []  # nothing was fetched at all

    def test_a_place_with_no_website_is_not_fetched(self):
        client = FakeClient({})

        assert imprint_email(client, place(website=None)) is None
        assert client.urls == []

    def test_only_one_page_is_fetched_once_it_answers(self):
        client = FakeClient({"https://baeckerei-mueller.de/impressum": PAGE})

        imprint_email(client, place())

        assert len(client.urls) == 1

    def test_the_usual_paths_are_tried_in_turn(self):
        """`/impressum` covers most German sites; the rest are common variants.
        Trying them all is still one small handful of requests, once, per site."""
        client = FakeClient({"https://baeckerei-mueller.de/kontakt": PAGE})

        assert imprint_email(client, place()) == "info@baeckerei-mueller.de"
        assert len(client.urls) <= len(IMPRINT_PATHS)

    def test_a_site_that_does_not_answer_costs_only_that_place(self):
        client = FakeClient({})

        assert imprint_email(client, place()) is None  # no exception escapes

    def test_a_site_that_answers_without_an_email_yields_nothing(self):
        client = FakeClient(
            {"https://baeckerei-mueller.de/impressum": "<h1>Impressum</h1><p>Telefon</p>"}
        )

        assert imprint_email(client, place()) is None

    def test_a_website_with_a_path_is_reduced_to_its_root(self):
        client = FakeClient({"https://baeckerei-mueller.de/impressum": PAGE})

        found = imprint_email(client, place(website="https://baeckerei-mueller.de/shop/brot"))

        assert found == "info@baeckerei-mueller.de"

    def test_a_website_without_a_scheme_is_still_usable(self):
        client = FakeClient({"https://baeckerei-mueller.de/impressum": PAGE})

        assert imprint_email(client, place(website="baeckerei-mueller.de")) is not None


class TestPaths:
    def test_impressum_is_tried_first(self):
        assert IMPRINT_PATHS[0] == "/impressum"

    def test_the_path_list_stays_short(self):
        """Every path is a request to someone's server for a page that may not
        exist. §8: the request count is the scarce resource."""
        assert len(IMPRINT_PATHS) <= 5


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_an_empty_website_is_no_website(raw):
    client = FakeClient({})

    assert imprint_email(client, place(website=raw)) is None
