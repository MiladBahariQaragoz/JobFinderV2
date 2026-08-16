"""The visual rules of §10, held by tests rather than good intentions.

No emoji anywhere in the UI; every number in the mono face. Both are cheap
greps over rendered pages and template sources, and both drift without
something to stop them.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "src" / "jobfinder" / "web" / "templates"

# Anything the Unicode consortium calls a pictograph, emoji, or symbol used
# decoratively — the whole families, not a hand-picked list that goes stale.
_EMOJI_CATEGORIES = {"So", "Sk", "Cs"}


def _is_emoji(character: str) -> bool:
    return unicodedata.category(character) in _EMOJI_CATEGORIES


def test_no_emoji_in_any_template():
    offenders: list[str] = []
    for path in TEMPLATES_DIR.rglob("*.html"):
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for character in line:
                if _is_emoji(character):
                    offenders.append(f"{path.name}:{line_number} has {character!r}")
    assert not offenders, "§10 bans emoji in the UI: " + "; ".join(offenders)


def test_rendered_pages_carry_no_emoji(client):
    for url in ("/", "/jobs/BA%3A1", "/settings", "/progress"):
        body = client.get(url).text
        emoji = [character for character in body if _is_emoji(character)]
        assert not emoji, f"{url} rendered emoji: {emoji[:5]}"


def test_numbers_render_in_the_monospace_class(settings, client):
    """Fit, km, dates, counts: every number she compares lives in `.num`."""
    from tests.web.conftest import enrichment_answer, store_job

    from jobfinder.store.db import connect

    connection = connect(settings.db_path)
    try:
        store_job(
            connection,
            job_id="BA:42",
            title="Mono Probe",
            city="Ingolstadt",
            answer=enrichment_answer(fit_score=77, hours_per_week=19),
        )
    finally:
        connection.close()

    body = client.get("/jobs/BA%3A42").text
    # The fit score and the weekly hours must sit inside the mono class.
    fit_block = re.search(r'<span class="num fit-big">77</span>', body)
    assert fit_block, "the fit score is not in the monospace class"
    assert re.search(r'<span class="num">19</span> h per week', body)

    listing = client.get("/?sort=fit").text
    assert '<span class="num">77</span>' in listing  # the list column too
