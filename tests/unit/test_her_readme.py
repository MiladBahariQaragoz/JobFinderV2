"""`docs/HER_README.md` is the only documentation written for her, not for me.

A page of instructions that has drifted from the app is worse than none: she
would follow it, find the button missing, and conclude that she had broken
something. These are cheap guards, in the same spirit as
`test_plan_checkboxes.py` — they say nothing about whether the writing is any
good, only that it still describes this app.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
README = REPO_ROOT / "docs" / "HER_README.md"
NAV = REPO_ROOT / "src" / "jobfinder" / "web" / "templates" / "base.html"


def readme_text() -> str:
    return README.read_text(encoding="utf-8")


def nav_labels() -> list[str]:
    """The words on the navigation bar, straight out of the template."""
    nav = re.search(r'<nav class="top-nav">(.*?)</nav>', NAV.read_text(encoding="utf-8"), re.S)
    assert nav is not None, "the nav block moved — this test needs updating"
    return re.findall(r"<a[^>]*>([^<]+)</a>", nav.group(1))


def test_her_readme_names_every_page_in_the_nav():
    text = readme_text()
    missing = [label for label in nav_labels() if label.strip() not in text]

    assert not missing, f"HER_README does not explain these pages: {missing}"


def test_her_readme_has_no_developer_instructions_in_it():
    """She has no Python, no terminal and no checkout. Anything that assumes
    one is a dead end on the page she reads when something is wrong."""
    text = readme_text().lower()
    developer_only = ["pip install", "pytest", "git clone", "virtualenv", ".venv", "localhost:8000"]
    found = [phrase for phrase in developer_only if phrase in text]

    assert not found, f"HER_README tells her to do developer things: {found}"


def test_every_screenshot_it_shows_exists():
    referenced = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", readme_text())

    assert referenced, "HER_README has no screenshots — it is supposed to show her the app"
    for relative in referenced:
        assert (README.parent / relative).exists(), f"{relative} is referenced and missing"


def test_it_says_what_to_do_when_something_is_wrong():
    text = readme_text().lower()

    assert "if something looks wrong" in text or "when something goes wrong" in text
