"""The live markers must be registered and must be excluded by default.

If `pytest` with no arguments ever picks up a live test, the suite starts
spending API quota and failing on someone else's outage.
"""

import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _run_pytest(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )


def test_live_markers_are_registered():
    result = _run_pytest("--markers")

    assert "@pytest.mark.live:" in result.stdout
    assert "@pytest.mark.live_llm:" in result.stdout


def test_default_run_deselects_live_tests():
    result = _run_pytest("tests/live", "--collect-only", "-q")

    # however many live tests exist, the default run deselects every one of them
    match = re.search(r"(\d+) deselected", result.stdout)
    assert match and int(match.group(1)) >= 1, result.stdout
    assert "live_probe" not in result.stdout
    assert "error" not in result.stdout.lower()


def test_live_marker_selects_the_live_test():
    result = _run_pytest("tests/live", "-m", "live", "--collect-only", "-q")

    assert "live_probe" in result.stdout
