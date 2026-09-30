"""The town picker: type the first letters, tick the one you meant.

Thirteen towns were a list of checkboxes. Nine hundred and fifty are not, so
the picker asks for two or three letters and offers what matches. Two rules
survive the change unaltered, and they are the reason this is not a text box:

- **A town is never typed into a search.** The filter box only filters. What
  the form submits is still a ticked checkbox carrying a canonical name, so a
  typo cannot reach a source.
- **Nothing is lost between keystrokes.** Ticking a match re-renders the whole
  picker, chosen towns included, because a chosen town that vanished with the
  next letter typed would be a picker that cannot be used.
"""

from __future__ import annotations

import re

from tests.web.test_search_form import checked_cities, offered_cities


def matches(html: str) -> list[str]:
    """The towns offered as unticked options, in page order."""
    start = html.find('id="town-matches"')
    if start < 0:
        return []
    # The partial arrives on its own; on a page load it is inside the picker.
    block = html[start:].split("</fieldset>")[0]
    found = []
    for box in re.findall(r"<input[^>]*>", block):
        name = re.search(r'name="cities"[^>]*value="([^"]+)"', box)
        if name and "checked" not in box:
            found.append(name.group(1))
    return found


class TestWhatIsOnThePage:
    def test_the_chosen_towns_are_ticked_when_the_page_opens(self, client):
        body = client.get("/search").text

        assert checked_cities(body) == ["Neuburg an der Donau", "Ingolstadt", "München"]

    def test_the_page_does_not_render_the_whole_country(self, client):
        """Nine hundred checkboxes is not a page, it is a document."""
        body = client.get("/search").text

        assert len(offered_cities(body)) < 40

    def test_there_is_a_filter_box_and_it_is_not_a_town(self, client):
        """It has to be named something the search never reads as a town."""
        body = client.get("/search").text

        assert 'name="town_filter"' in body
        assert '<input type="text" name="cities"' not in body

    def test_the_filter_box_does_not_submit_the_form(self, client):
        """Enter in a filter box must not start a four-minute search."""
        body = client.get("/search").text
        box = re.search(r'<input[^>]*name="town_filter"[^>]*>', body).group(0)

        assert "Enter" in box and "preventDefault" in box


class TestTypingFindsATown:
    def test_two_letters_offer_the_matching_towns(self, client):
        body = client.get("/cities/options", params={"town_filter": "flen"}).text

        assert "Flensburg" in matches(body)

    def test_the_towns_already_chosen_are_not_offered_again(self, client):
        body = client.get(
            "/cities/options",
            params={"town_filter": "ingol", "cities": ["Ingolstadt"]},
        ).text

        # Dingolfing contains those letters too and is not chosen, so it stays.
        assert "Ingolstadt" not in matches(body)
        assert "Dingolfing" in matches(body)

    def test_a_town_that_does_not_exist_says_so(self, client):
        body = client.get("/cities/options", params={"town_filter": "zzzz"}).text

        assert matches(body) == []
        assert "No town" in body

    def test_the_state_is_shown_beside_the_town(self, client):
        """There is a Neustadt in half the country. The state is what tells
        one from another."""
        body = client.get("/cities/options", params={"town_filter": "flen"}).text

        assert "Schleswig-Holstein" in body


class TestTickingAndUnticking:
    def test_ticking_a_match_keeps_it_and_the_towns_already_chosen(self, client):
        body = client.post(
            "/cities/toggle",
            data={"cities": ["Ingolstadt", "Flensburg"], "town_filter": "flen"},
        ).text

        assert checked_cities(body) == ["Ingolstadt", "Flensburg"]

    def test_unticking_a_town_removes_it(self, client):
        body = client.post("/cities/toggle", data={"cities": ["Ingolstadt"]}).text

        assert checked_cities(body) == ["Ingolstadt"]
        assert "München" not in checked_cities(body)

    def test_what_was_typed_survives_the_tick(self, client):
        """Otherwise every tick clears the box and the next town has to be
        typed from the beginning."""
        body = client.post(
            "/cities/toggle", data={"cities": ["Flensburg"], "town_filter": "flen"}
        ).text

        assert 'value="flen"' in body

    def test_ticking_nothing_leaves_nothing_ticked(self, client):
        """An empty picker is a real state — it is what the search reads as
        "use the towns from my settings"."""
        body = client.post("/cities/toggle", data={"town_filter": "ber"}).text

        assert checked_cities(body) == []


class TestEverywhereTownsAreAsked:
    def test_the_call_list_has_the_picker(self, client):
        body = client.get("/contacts").text

        assert 'name="town_filter"' in body
        assert checked_cities(body) == ["Neuburg an der Donau", "Ingolstadt", "München"]

    def test_the_wizard_has_the_picker_before_anything_is_set_up(self, tmp_path):
        from fastapi.testclient import TestClient

        from jobfinder.config import Settings
        from jobfinder.web.app import create_app

        (tmp_path / "config.yaml").unlink(missing_ok=True)
        with TestClient(create_app(Settings(project_root=tmp_path))) as fresh:
            body = fresh.get("/setup").text
            found = fresh.get("/cities/options", params={"town_filter": "flen"})

        assert 'name="town_filter"' in body
        assert found.status_code == 200, "the wizard's own picker is behind the redirect"
        assert "Flensburg" in matches(found.text)
