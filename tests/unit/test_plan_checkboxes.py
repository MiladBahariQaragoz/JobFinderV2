"""The plan's ticked boxes have to be true.

MASTER_PLAN is the live progress record — §7 says the ticked boxes on GitHub
are exactly what works. That only holds if a tick cannot outlive the test it
claims. A box naming `test_foo` is a promise that `test_foo` exists and runs
in the suite; renaming a test without renaming its box quietly breaks it.

This is a cheap test that keeps the promise honest. It says nothing about
whether the named test is *good* — only that it is real.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN = REPO_ROOT / "docs" / "MASTER_PLAN.md"
TESTS = REPO_ROOT / "tests"

TICKED_TEST = re.compile(r"^\s*- \[x\]\s*`(test_\w+)`")
TICKED_FILE = re.compile(r"^\s*- \[x\]\s*`(tests/[\w/]+\.py)`")


def existing_test_names() -> set[str]:
    names: set[str] = set()
    for path in TESTS.rglob("*.py"):
        names |= set(re.findall(r"def (test_\w+)", path.read_text(encoding="utf-8")))
    return names


def plan_lines() -> list[str]:
    return PLAN.read_text(encoding="utf-8").splitlines()


def test_every_ticked_box_names_a_test_that_exists():
    have = existing_test_names()
    claimed = [m.group(1) for line in plan_lines() if (m := TICKED_TEST.match(line))]
    missing = sorted(name for name in claimed if name not in have)
    assert not missing, (
        "MASTER_PLAN ticks these tests, but no such test exists — either the box "
        f"is wrong or the test was renamed: {missing}"
    )


def test_every_ticked_test_file_exists():
    claimed = [m.group(1) for line in plan_lines() if (m := TICKED_FILE.match(line))]
    missing = sorted(name for name in claimed if not (REPO_ROOT / name).exists())
    assert not missing, f"MASTER_PLAN ticks these test files, but they are not there: {missing}"


def test_the_plan_still_holds_ticked_boxes():
    # Guards the guard: a regex that silently stops matching would make the
    # two tests above pass by finding nothing at all.
    ticked = [line for line in plan_lines() if TICKED_TEST.match(line)]
    assert len(ticked) > 40, f"only {len(ticked)} ticked test boxes parsed — the pattern drifted"
