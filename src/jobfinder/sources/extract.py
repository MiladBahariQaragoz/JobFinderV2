"""Readable text out of an HTML page — for the ads BA only links to.

When `stellenangebotsBeschreibung` is empty, the posting carries an
`externeURL` instead. Those pages range from server-rendered job ads (good) to
client-side SPAs whose static HTML holds nothing (normal — the posting then
simply has no description). Phase 6 extends this with JSON-LD extraction for
the scraper sources; text stripping remains the fallback.
"""

from __future__ import annotations

import html as html_lib
import re

_SCRIPT_OR_STYLE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_ANY_TAG = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")

# Shorter than this is navigation junk or an empty app shell, not an ad.
MIN_TEXT_CHARS = 80


def extract_readable_text(markup: str, *, min_chars: int = MIN_TEXT_CHARS) -> str | None:
    """Tag-stripped, entity-decoded page text — or None when there is no real text."""
    without_code = _SCRIPT_OR_STYLE.sub(" ", markup)
    text = html_lib.unescape(_ANY_TAG.sub(" ", without_code))
    collapsed = _WHITESPACE.sub(" ", text).strip()
    if len(collapsed) < min_chars:
        return None
    return collapsed
