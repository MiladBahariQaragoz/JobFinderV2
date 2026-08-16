"""Wording shared by every scraper: what German ads say, and what we search for.

The API sources get flags from their APIs; scraped ads get flags from their
words. One vocabulary here means Kleinanzeigen's "450-Basis" and Xing's
"Minijob" set the same flag, and the employment-type → search-term mapping is
decided once instead of per adapter.
"""

from __future__ import annotations

# The Phase 6 minijob list from the master plan, plus the spellings the sites
# actually use. Matched case-insensitively against title + description.
MINIJOB_WORDS = (
    "minijob",
    "mini-job",
    "mini job",
    # The words the ads on a real Ingolstadt page actually used. "Nebenjob"
    # was the commonest of them and was missing, so those ads were dropped
    # before anyone read them.
    "nebenjob",
    "neben-job",
    "nebentätigkeit",
    "nebentaetigkeit",
    "schülerjob",
    "schuelerjob",
    "studentenjob",  # colloquial for a small job, not the Werkstudent contract
    "geringfügig",
    "geringfuegig",
    "aushilfe",
    "aushilfs",  # Aushilfskraft, Aushilfstätigkeit
    # Every earnings ceiling the minijob has had. The limit is indexed to the
    # minimum wage and rises most years, so an ad quoting this year's figure
    # reads as a full-time post until its number is on this list. Check the
    # current ceiling each January and add it here.
    *(
        spelling
        for amount in ("450", "520", "538", "556")
        for spelling in (f"{amount} €", f"{amount}€", f"{amount} euro", f"{amount}-basis")
    ),
)

WERKSTUDENT_WORDS = ("werkstudent", "studentische hilfskraft", "working student")
INTERNSHIP_WORDS = ("praktikum", "praktikant", "internship", "trainee")
PARTTIME_WORDS = ("teilzeit", "part-time", "part time", " Teilzeit ".strip())
FULLTIME_WORDS = ("vollzeit", "full-time", "full time")

TYPE_WORDS = {
    "minijob": MINIJOB_WORDS,
    "werkstudent": WERKSTUDENT_WORDS,
    "internship": INTERNSHIP_WORDS,
    "parttime": PARTTIME_WORDS,
    "fulltime": FULLTIME_WORDS,
}

# What goes in a site's search box for each employment type she can pick.
# Alternatives, never stacked (Phase 4 audit): each type is its own query.
SEARCH_TERMS = {
    "minijob": "minijob",
    "werkstudent": "werkstudent",
    "parttime": "teilzeit",
    "fulltime": "vollzeit",
    "internship": "praktikum",
}

# Umlaut-free, lowercase, hyphenated — the URL form German sites use.
_UMLAUTS = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}


def slugify(text: str) -> str:
    """City and keyword slugs as the boards spell them: 'München' -> 'muenchen'."""
    folded = text.strip().lower()
    for umlaut, spelled in _UMLAUTS.items():
        folded = folded.replace(umlaut, spelled)
    return "-".join(part for part in folded.replace(" ", "-").split("-") if part)


def employment_type_signals(*texts: str | None) -> set[str]:
    """Which employment types this ad's own words claim it is."""
    haystack = " ".join((text or "") for text in texts).casefold()
    return {
        employment_type
        for employment_type, words in TYPE_WORDS.items()
        if any(word in haystack for word in words)
    }


def search_term_for(employment_type: str) -> str:
    """The search-box word for one of her employment types."""
    try:
        return SEARCH_TERMS[employment_type]
    except KeyError:
        from jobfinder.search_spec import EMPLOYMENT_TYPES

        raise ValueError(
            f"Unknown employment type '{employment_type}'. Valid types are: "
            f"{', '.join(EMPLOYMENT_TYPES)}."
        ) from None
