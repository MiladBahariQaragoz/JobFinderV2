"""Her CV: `pool.yaml` in, a validated `Resume` out.

Every failure raises :class:`ProfileError` with one sentence a non-programmer can
act on — naming the field, the entry id, and where possible the YAML line. A typo
must produce a readable error at second zero, not an empty result list after four
minutes of searching.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

REQUIRED_BASICS = ("name", "email", "location")

_DATE_RE = re.compile(r"^(\d{4})-(\d{2})$")
# The blank template ships literal placeholders like "YYYY-MM" — they mean "unset".
_PLACEHOLDER_RE = re.compile(r"y{2,}", re.IGNORECASE)

_LEVEL_ALIASES = {
    "mother tongue": "C2",
    "native": "C2",
    "native proficiency": "C2",
    "muttersprache": "C2",
    "fluent": "C1",
    "fließend": "C1",
    "advanced": "C2",
    "intermediate": "B1",
    "basic": "A2",
    "beginner": "A1",
    "grundkenntnisse": "A2",
}
CEFR_LEVELS = ("A1", "A2", "B1", "B2", "C1", "C2")


class ProfileError(Exception):
    """One actionable sentence about what is wrong with pool.yaml."""


def normalize_language_level(raw: str) -> str:
    """Map free-text levels ('Mother tongue', 'Fluent', 'Basic') onto CEFR."""
    cleaned = raw.strip()
    upper = cleaned.upper()
    if upper in CEFR_LEVELS:
        return upper
    try:
        return _LEVEL_ALIASES[cleaned.lower()]
    except KeyError:
        raise ProfileError(
            f"Unknown language level '{cleaned}'. Use A1–C2, or one of: "
            f"{', '.join(sorted(_LEVEL_ALIASES))}."
        ) from None


@dataclass(frozen=True)
class Language:
    name: str
    level: str
    normalized: str


@dataclass(frozen=True)
class Experience:
    id: str
    role: str
    org: str
    start: str
    end: str
    employment: str = ""
    location: str = ""
    bullets: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()

    @property
    def start_date(self) -> tuple[int, int] | None:
        return _parse_date(self.start, self.id, "start")

    @property
    def end_date(self) -> tuple[int, int] | None:
        return _parse_date(self.end, self.id, "end")


def _parse_date(raw: str, entry_id: str, which: str) -> tuple[int, int] | None:
    if raw == "present":
        now = date.today()
        return now.year, now.month
    if _PLACEHOLDER_RE.search(str(raw)):
        return None  # template placeholder, not her data
    match = _DATE_RE.match(str(raw))
    if not match:
        raise ProfileError(
            f"Experience entry '{entry_id}': {which} date '{raw}' is not a valid "
            "YYYY-MM (e.g. 2024-10) or 'present'."
        )
    year, month = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12:
        raise ProfileError(
            f"Experience entry '{entry_id}': {which} date '{raw}' is not a valid "
            "YYYY-MM — month must be 01–12."
        )
    return year, month


@dataclass(frozen=True)
class Education:
    org: str
    degree: str
    start: str
    end: str
    location: str = ""
    notes: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    summary: str = ""
    stack: tuple[str, ...] = ()
    highlights: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class Certification:
    name: str
    issuer: str = ""
    date: str = ""
    url: str = ""


@dataclass(frozen=True)
class Resume:
    basics: dict = field(default_factory=dict)
    languages: tuple[Language, ...] = ()
    experience: tuple[Experience, ...] = ()
    projects: tuple[Project, ...] = ()
    education: tuple[Education, ...] = ()
    skill_groups: dict[str, tuple[str, ...]] = field(default_factory=dict)
    certifications: tuple[Certification, ...] = ()
    interests: tuple[str, ...] = ()
    working_style: dict = field(default_factory=dict)

    def years_of_experience(self) -> float:
        """From the earliest start to the latest end, 'present' included."""
        if not self.experience:
            return 0.0
        starts = [e.start_date for e in self.experience if e.start_date]
        ends = [e.end_date for e in self.experience if e.end_date]
        if not starts or not ends:
            return 0.0

        def months(ym: tuple[int, int]) -> int:
            return ym[0] * 12 + ym[1]

        span = months(max(ends)) - months(min(starts))
        return round(span / 12, 1)


def _section_lines(text: str) -> dict[str, int]:
    """Line number of each top-level key, from the YAML node marks (1-based)."""
    try:
        root = yaml.compose(text)
    except yaml.YAMLError:
        return {}
    lines: dict[str, int] = {}
    if isinstance(root, yaml.MappingNode):
        for key_node, _ in root.value:
            if isinstance(key_node, yaml.ScalarNode):
                lines[str(key_node.value)] = key_node.start_mark.line + 1
    return lines


def _string_list(raw) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        return (raw,)
    return tuple(str(item) for item in raw)


# Placeholders the blank template ships with. A template that was downloaded
# and never filled in *parses* — it has a name, an email and a location — so
# nothing downstream would object, and every row would carry a fit score
# computed against "Your Full Name". Saying "this is still the template" is the
# only honest answer.
_TEMPLATE_VALUES = (
    "your full name",
    "your.email@example.com",
    "city, country",
)


def is_unfilled_template(resume: Resume) -> bool:
    """True when this parses but is still the blank template's placeholders."""
    return any(
        str(resume.basics.get(key, "")).strip().lower() in _TEMPLATE_VALUES
        for key in REQUIRED_BASICS
    )


def save_profile_text(text: str, path: Path, *, backup_path: Path) -> Resume:
    """Validate an uploaded CV, then write it — never the other way round.

    Nothing on disk is touched until the text parses, so a bad paste costs her
    the upload and not the CV she already had. What she had is copied to
    `backup_path` anyway: replacing a file that took an afternoon to write is
    not otherwise recoverable.

    `backup_path` is required rather than derived, because the obvious
    derivation — `pool.yaml.bak`, beside the CV — is the one that put her name
    and contact details into a public repository. The caller has to name a
    directory that is safe to write her CV into.
    """
    path = Path(path)
    if not text.strip():
        raise ProfileError(
            "That file is empty. Download the template, fill in your details, and upload it."
        )

    resume = parse_profile(text, name=path.name)  # raises ProfileError, naming the field

    # Bytes, not text, on both sides. `write_text` translates newlines on
    # Windows, so a CV saved by any editor on this laptop — CRLF — came back
    # with every line ending doubled to \r\r\n, and doubled again on the next
    # upload. A backup whose bytes differ from the file it saved is not a
    # backup either (§ Cross-cutting concerns, "Windows reality").
    if path.exists():
        backup_path = Path(backup_path)
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path.write_bytes(path.read_bytes())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return resume


def load_profile(path: Path) -> Resume:
    """Parse and validate pool.yaml. Raises ProfileError with one actionable sentence."""
    path = Path(path)
    if not path.exists():
        raise ProfileError(
            f"No CV file at {path}. Copy pool.template.yaml to pool.yaml and fill it in."
        )
    return parse_profile(path.read_text(encoding="utf-8"), name=path.name)


def parse_profile(text: str, *, name: str = "pool.yaml") -> Resume:
    """The same validation, over text that may not be on disk yet.

    `name` is only what the error sentences call the file, so a CV validated
    before it is written still reads as `pool.yaml` rather than naming whatever
    temporary thing it arrived in.
    """
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        line = getattr(getattr(exc, "problem_mark", None), "line", None)
        where = f" (line {line + 1})" if line is not None else ""
        raise ProfileError(
            f"{name} is not valid YAML{where}: {getattr(exc, 'problem', exc)}."
        ) from None

    if not isinstance(data, dict):
        raise ProfileError(
            f"{name}: expected the file to be a list of sections like "
            f"'basics:' and 'experience:', found {type(data).__name__}."
        )

    lines = _section_lines(text)

    basics = data.get("basics")
    if not isinstance(basics, dict):
        where = f" (line {lines['basics']})" if "basics" in lines else ""
        raise ProfileError(
            f"{name}: the 'basics' section{where} is missing or empty — "
            "it holds your name, email and location. "
            "Copy it from pool.template.yaml and fill it in."
        )
    missing = [key for key in REQUIRED_BASICS if not str(basics.get(key, "")).strip()]
    if missing:
        where = f" starts at line {lines['basics']}" if "basics" in lines else ""
        raise ProfileError(
            f"{name}: 'basics'{where} is missing {', '.join(repr(m) for m in missing)}. "
            f"Required fields: {', '.join(REQUIRED_BASICS)}."
        )

    # The template nests languages under `basics:`; either location is accepted.
    raw_languages = data.get("languages") or basics.get("languages") or []
    languages = []
    for raw in raw_languages:
        languages.append(
            Language(
                name=str(raw["name"]),
                level=str(raw.get("level", "")),
                normalized=normalize_language_level(str(raw.get("level", "unclear"))),
            )
        )

    experience = []
    for raw in data.get("experience") or []:
        entry_id = str(raw.get("id", "<no id>"))
        experience.append(
            Experience(
                id=entry_id,
                role=str(raw.get("role", "")),
                org=str(raw.get("org", "")),
                start=str(raw.get("start", "")),
                end=str(raw.get("end", "present")),
                employment=str(raw.get("employment", "")),
                location=str(raw.get("location", "")),
                bullets=tuple(
                    str(b.get("text", b) if isinstance(b, dict) else b)
                    for b in raw.get("bullets") or []
                ),
                skills=_string_list(raw.get("skills")),
                tags=_string_list(raw.get("tags")),
            )
        )
        # Validate the dates immediately, naming the entry.
        _parse_date(str(raw.get("start", "")), entry_id, "start")
        _parse_date(str(raw.get("end", "present")), entry_id, "end")

    education = [
        Education(
            org=str(raw.get("org", "")),
            degree=str(raw.get("degree", "")),
            start=str(raw.get("start", "")),
            end=str(raw.get("end", "present")),
            location=str(raw.get("location", "")),
            notes=_string_list(raw.get("notes")),
            tags=_string_list(raw.get("tags")),
        )
        for raw in data.get("education") or []
    ]

    projects = [
        Project(
            id=str(raw.get("id", f"project-{index}")),
            name=str(raw.get("name", "")),
            summary=str(raw.get("summary", "")),
            stack=_string_list(raw.get("stack")),
            highlights=_string_list(raw.get("highlights")),
            tags=_string_list(raw.get("tags")),
        )
        for index, raw in enumerate(data.get("projects") or [])
    ]

    skill_groups = {
        str(group): _string_list((body or {}).get("items"))
        if isinstance(body, dict)
        else _string_list(body)
        for group, body in (data.get("skill_groups") or {}).items()
    }

    certifications = [
        Certification(
            name=str(raw.get("name", "")),
            issuer=str(raw.get("issuer", "")),
            date=str(raw.get("date", "")),
            url=str(raw.get("url", "")),
        )
        for raw in data.get("certifications") or []
    ]

    return Resume(
        basics=dict(basics),
        languages=tuple(languages),
        experience=tuple(experience),
        projects=tuple(projects),
        education=tuple(education),
        skill_groups=skill_groups,
        certifications=tuple(certifications),
        interests=_string_list(data.get("interests")),
        working_style=dict(data.get("working_style") or {}),
    )
