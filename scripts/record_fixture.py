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


def is_html(content: bytes) -> bool:
    """Does this body look like a page worth parsing, whatever its status said?"""
    head = content.lstrip()[:256].lower()
    return any(market in head for market in (b"<!doctype html", b"<html", b"<div", b"<body"))


def record(
    source: str,
    name: str,
    url: str,
    headers: dict[str, str] | None = None,
    *,
    html: bool = False,
    content: bytes | None = None,
    fixture_root: Path | None = None,
) -> int:
    """Fetch (or take) one response and save it — the `--html` gate lives here."""
    content = content if content is not None else fetch(url, headers or {})
    if html and not is_html(content):
        preview = content[:80].decode("utf-8", errors="replace").strip()
        print(f"not HTML ({preview!r}) — a block or error page, not a fixture. Nothing saved.")
        return 1
    path = save_fixture(source, name, content, fixture_root)
    print(f"recorded {len(content)} bytes -> {path}")
    return 0


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
    parser.add_argument(
        "--html",
        action="store_true",
        help="record an HTML page; a body that is not a page (a block page) is refused",
    )
    args = parser.parse_args(argv)

    headers = {}
    for raw in args.header:
        key, _, value = raw.partition(":")
        headers[key.strip()] = value.strip()

    return record(args.source, args.name, args.url, headers, html=args.html)


if __name__ == "__main__":
    sys.exit(main())
