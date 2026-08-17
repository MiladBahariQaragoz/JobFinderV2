"""One version number, in two files that must agree.

`/healthz` reports `jobfinder.__version__` and the built exe is named from
`pyproject.toml`. When those two drift, "which build is she running" stops
having an answer — which is the question an update path exists to settle.
"""

from __future__ import annotations

import re
from pathlib import Path

import jobfinder

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_the_package_version_matches_pyproject():
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    declared = re.search(r'^version = "([^"]+)"', text, re.MULTILINE)

    assert declared is not None, "pyproject.toml has no version"
    assert jobfinder.__version__ == declared.group(1)
