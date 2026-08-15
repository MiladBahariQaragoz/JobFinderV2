"""Record a real response into tests/fixtures/ so adapter tests parse the real thing.

Hand-written fixtures pass against code that cannot read what a source actually
returns. Every adapter test is backed by a file recorded with this script.

    BA=https://rest.arbeitsagentur.de/jobboerse/jobsuche-service
    python scripts/record_fixture.py ba jobs_werkstudent.json \
        "$BA/pc/v6/jobs?was=Werkstudent&wo=Ingolstadt&size=5" \
        --header "X-API-Key: jobboerse-jobsuche"

JSON is re-indented so a later diff shows what changed upstream; anything else is
written byte for byte.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

DEFAULT_FIXTURE_ROOT = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
USER_AGENT = (
    "JobFinder/0.1 (personal job search; +https://github.com/MiladBahariQaragoz/JobFinderV2)"
)


def save_fixture(source: str, name: str, content: bytes, fixture_root: Path | None = None) -> Path:
    """Write one recorded response and return where it landed."""
    root = Path(fixture_root) if fixture_root else DEFAULT_FIXTURE_ROOT
    path = root / source / name
    path.parent.mkdir(parents=True, exist_ok=True)

    if name.endswith(".json"):
        try:
            parsed = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            # A source answering with an error page is exactly what we want to keep.
            path.write_bytes(content)
            return path
        path.write_text(json.dumps(parsed, indent=1, ensure_ascii=False), encoding="utf-8")
        return path

    path.write_bytes(content)
    return path


def fetch(url: str, headers: dict[str, str]) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **headers})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="adapter name, e.g. ba, arbeitnow, kleinanzeigen")
    parser.add_argument("name", help="fixture filename, e.g. jobs_werkstudent.json")
    parser.add_argument("url", help="the URL to record")
    parser.add_argument("--header", action="append", default=[], help='"Name: value", repeatable')
    args = parser.parse_args(argv)

    headers = {}
    for raw in args.header:
        key, _, value = raw.partition(":")
        headers[key.strip()] = value.strip()

    content = fetch(args.url, headers)
    path = save_fixture(args.source, args.name, content)
    print(f"recorded {len(content)} bytes -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
