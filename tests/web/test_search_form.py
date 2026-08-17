"""The Search page: what she picks, and what pressing it actually starts.

Two rules this file holds, both asked for after seeing the app:

- **Towns are ticked, not typed.** A text box asks her to spell
  `Neuburg an der Donau` correctly, and answers a typo with a refusal. The
  list is known — thirteen towns — so it is a list.
- **Search searches.** Explaining jobs in English is its own page, its own
  thread and its own free-tier cost, because the day she is done searching and
  only wants the interrupted explanations finished, one button that does both
  is the wrong button.
"""

from __future__ import annotations

import re


def checked_cities(html: str) -> list[str]:
    """The towns whose checkbox is ticked, in page order."""
    boxes = re.findall(r'<input[^>]*name="cities"[^>]*>', html)
    return [re.search(r'value="([^"]+)"', box).group(1) for box in boxes if "checked" in box]


def offered_cities(html: str) -> list[str]:
    boxes = re.findall(r'<input[^>]*name="cities"[^>]*>', html)
    return [re.search(r'value="([^"]+)"', box).group(1) for box in boxes]


class TestTownsAreTicked:
    def test_the_towns_are_checkboxes_not_a_text_box(self, client):
        body = client.get("/search").text

        assert '<input type="text" name="cities"' not in body
        assert offered_cities(body), "no city checkboxes at all"

    def test_her_own_towns_are_ticked_to_begin_with(self, client):
        body = client.get("/search").text

        assert checked_cities(body) == ["Neuburg an der Donau", "Ingolstadt", "München"]

    def test_the_other_towns_are_offered_unticked(self, client):
        """She can search Augsburg without editing a settings file — and
        without it joining every search from now on."""
        body = client.get("/search").text

        assert "Augsburg" in offered_cities(body)
        assert "Augsburg" not in checked_cities(body)

    def test_the_towns_she_ticks_are_the_ones_searched(self, seeded, monkeypatch):
        from fastapi.testclient import TestClient

        from jobfinder.web.app import create_app
        from jobfinder.web.runs import RunManager

        started = {}

        class Recording(RunManager):
            def start(self, **kwargs):
                started.update(kwargs)

        with TestClient(create_app(seeded, run_manager=Recording(seeded))) as client:
            client.post("/run/start", data={"cities": ["Ingolstadt", "Augsburg"]})

        assert started["cities"] == "Ingolstadt, Augsburg"

    def test_ticking_nothing_falls_back_to_her_towns(self, seeded):
        """An empty selection must not mean an empty search."""
        from fastapi.testclient import TestClient

        from jobfinder.web.app import create_app
        from jobfinder.web.runs import RunManager

        started = {}

        class Recording(RunManager):
            def start(self, **kwargs):
                started.update(kwargs)

        with TestClient(create_app(seeded, run_manager=Recording(seeded))) as client:
            client.post("/run/start", data={"types": "minijob"})

        assert started["cities"] is None  # the runner's own default: her settings


class TestSearchDoesNotExplain:
    def test_the_search_form_does_not_explain_by_default(self, client):
        """Explaining costs one free-tier call per job. A search that quietly
        spends them is a search she cannot afford to press twice."""
        body = client.get("/search").text
        enrich_box = re.search(r'<input[^>]*name="enrich"[^>]*>', body)

        assert enrich_box is not None
        assert "checked" not in enrich_box.group(0)

    def test_the_search_page_points_at_the_explain_page(self, client):
        body = client.get("/search").text

        assert 'href="/enrich"' in body

    def test_explaining_needs_no_search(self, client):
        """The day she is done searching, Explain is a page she can open and
        press on its own — nothing on it asks about a search."""
        body = client.get("/enrich").text

        assert "/run/enrich" in body
        assert "/run/start" not in body


class TestTheOtherPlacesTownsAreAsked:
    """The same rule everywhere she picks towns, or the typing comes back."""

    def test_the_call_list_offers_ticked_towns(self, client):
        body = client.get("/contacts").text

        assert '<input type="text" name="cities"' not in body
        assert checked_cities(body) == ["Neuburg an der Donau", "Ingolstadt", "München"]

    def test_the_wizard_offers_ticked_towns(self, tmp_path):
        from fastapi.testclient import TestClient

        from jobfinder.config import Settings
        from jobfinder.web.app import create_app

        (tmp_path / "config.yaml").unlink(missing_ok=True)
        with TestClient(create_app(Settings(project_root=tmp_path))) as fresh:
            body = fresh.get("/setup").text

        assert '<input type="text" id="cities"' not in body
        assert checked_cities(body) == ["Neuburg an der Donau", "Ingolstadt", "München"]
        assert "Augsburg" in offered_cities(body)

    def test_the_wizard_writes_the_towns_she_ticked(self, tmp_path):
        from fastapi.testclient import TestClient

        from jobfinder.config import Settings
        from jobfinder.web.app import create_app

        (tmp_path / "config.yaml").unlink(missing_ok=True)
        settings = Settings(project_root=tmp_path)
        with TestClient(create_app(settings)) as fresh:
            fresh.post("/setup", data={"cities": ["Ingolstadt", "Augsburg"], "types": "minijob"})

        assert Settings.load(project_root=tmp_path).cities == ("Ingolstadt", "Augsburg")

    def test_a_call_list_run_uses_the_towns_she_ticked(self, seeded):
        from fastapi.testclient import TestClient

        from jobfinder.web.app import create_app
        from jobfinder.web.runs import RunManager

        started = {}

        class Recording(RunManager):
            def start_contacts(self, **kwargs):
                started.update(kwargs)

        with TestClient(create_app(seeded, run_manager=Recording(seeded))) as client:
            client.post("/run/contacts", data={"cities": ["Ingolstadt", "Augsburg"]})

        assert started["cities"] == "Ingolstadt, Augsburg"
