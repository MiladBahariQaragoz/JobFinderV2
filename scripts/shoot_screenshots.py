"""Take the screenshots that go in `docs/HER_README.md`.

    python scripts/shoot_screenshots.py

**Never against her real store.** The images live in a public repository, so
this builds a throwaway project root with invented jobs and invented places,
serves that, and photographs it. Nothing here reads `data/` or `pool.yaml`.

Re-run it whenever a page changes enough that the README would be lying.
"""

from __future__ import annotations

import shutil
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

IMAGES = REPO_ROOT / "docs" / "images"
VIEWPORT = {"width": 1180, "height": 820}


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def demo_root(tmp: Path, *, set_up: bool) -> Path:
    """A project root with invented data — never hers."""
    from jobfinder.config import Settings
    from jobfinder.sources.base import RawPosting
    from jobfinder.sources.overpass import Place
    from jobfinder.store.contacts import upsert_contact
    from jobfinder.store.db import connect, migrate
    from jobfinder.store.enrichment import save_enrichment
    from jobfinder.store.jobs import upsert_job

    root = tmp / ("set-up" if set_up else "fresh")
    root.mkdir(parents=True)
    if set_up:
        (root / "config.yaml").write_text(
            "cities:\n  - Neuburg an der Donau\n  - Ingolstadt\n  - München\n",
            encoding="utf-8",
        )
    settings = Settings.load(root)
    if not set_up:
        return root

    jobs = [
        (
            "BA:1001",
            "Aushilfe Verkauf (Minijob)",
            "Bäckerei Sonnenfeld",
            "Neuburg an der Donau",
            78,
        ),
        ("BA:1002", "Werkstudent Qualitätssicherung", "Donau Technik GmbH", "Ingolstadt", 71),
        ("KA:1003", "Küchenhilfe Teilzeit", "Gasthaus Am Markt", "Neuburg an der Donau", 64),
        ("AN:1004", "Retail Assistant (English speaking)", "Northside Retail", "München", 58),
        ("BA:1005", "Servicekraft Wochenende", "Hotel Auwald", "Ingolstadt", 52),
    ]
    connection = connect(settings.db_path)
    try:
        migrate(connection)
        for job_id, title, company, city, fit in jobs:
            upsert_job(
                connection,
                RawPosting(
                    job_id=job_id,
                    source=job_id.split(":")[0],
                    source_id=job_id.split(":")[1],
                    source_url=f"https://example.invalid/{job_id}",
                    title=title,
                    company=company,
                    city=city,
                    is_minijob="Minijob" in title,
                    is_werkstudent="Werkstudent" in title,
                    is_parttime="Teilzeit" in title,
                    published_at="2026-08-14",
                    description=(
                        "Wir suchen zuverlässige Unterstützung für unser Team. "
                        "Gute Deutschkenntnisse sind von Vorteil, Erfahrung ist "
                        "nicht erforderlich. Arbeitszeiten nach Absprache."
                    ),
                ),
            )
            if job_id == "BA:1005":
                continue  # left unexplained, so the Explain page has something to do
            # The store decides an answer is stale when its content hash does not
            # match the job's, so the demo has to use the job's own hash — with
            # a made-up one every job reads as "not explained yet".
            stored_hash = connection.execute(
                "SELECT content_hash FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()[0]
            save_enrichment(
                connection,
                job_id,
                "v1",
                stored_hash,
                {
                    "category": "retail",
                    "seniority": "entry",
                    "skills_required": ["customer service"],
                    "skills_nice": ["cash handling"],
                    "german_level": "B1",
                    "german_evidence": "Gute Deutschkenntnisse sind von Vorteil",
                    "english_sufficient": False,
                    "employment_type_norm": "minijob",
                    "hours_per_week": 12,
                    "duties_en": ["Serve customers at the counter", "Keep the shelves stocked"],
                    "requirements_en": ["Reliable", "Weekend availability"],
                    "summary_en": (
                        "A small shop looking for weekend help. No experience needed, "
                        "and the advert says everyday German is enough."
                    ),
                    "fit_score": fit,
                    "fit_reasons": ["Her retail experience matches", "Close to home"],
                    "missing_for_fit": ["Stronger spoken German"],
                    "red_flags": [],
                    "application_method": "email",
                    "contact_email": "jobs@example.invalid",
                    "contact_phone": "",
                    "deadline": "",
                },
            )
        for osm_id, name, kind, city, phone, score in [
            (
                "node/2001",
                "Bäckerei Sonnenfeld",
                "bakery",
                "Neuburg an der Donau",
                "+4984311111",
                93,
            ),
            ("node/2002", "Hotel Auwald", "hotel", "Ingolstadt", "+4984122222", 88),
            ("node/2003", "Café Marktplatz", "cafe", "Neuburg an der Donau", "+4984133333", 70),
        ]:
            upsert_contact(
                connection,
                Place(
                    contact_id=osm_id,
                    name=name,
                    kind=kind,
                    city=city,
                    street="Hauptstraße 1",
                    phone=phone,
                ),
                score=score,
                reason=f"a {kind} — kitchens and counters hire without advertising",
            )
        connection.execute(
            "UPDATE contacts SET script = ?",
            (
                "Guten Tag, mein Name ist Sara.\n"
                "Hello, my name is Sara.\n"
                "Ich suche einen Minijob in Neuburg an der Donau.\n"
                "I am looking for a part-time job in Neuburg an der Donau.\n"
                "Suchen Sie im Moment Aushilfen?\n"
                "Are you looking for help at the moment?",
            ),
        )
        connection.commit()
    finally:
        connection.close()
    return root


def serve(root: Path, port: int):
    """The real app, on a thread, so the screenshots are of the real thing."""
    import uvicorn

    from jobfinder.config import Settings
    from jobfinder.web.app import create_app

    server = uvicorn.Server(
        uvicorn.Config(
            create_app(Settings.load(root)),
            host="127.0.0.1",
            port=port,
            log_level="error",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    return server


SHOTS = [
    ("fresh", "/setup", "01-welcome.png"),
    ("set-up", "/search", "02-search.png"),
    ("set-up", "/", "03-jobs.png"),
    ("set-up", "/jobs/BA:1001", "04-one-job.png"),
    ("set-up", "/enrich", "05-explain.png"),
    ("set-up", "/contacts", "06-call-list.png"),
    ("set-up", "/settings", "07-settings.png"),
]


def main() -> int:
    from playwright.sync_api import sync_playwright

    IMAGES.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="jobfinder-shots-"))
    try:
        roots = {"fresh": demo_root(tmp, set_up=False), "set-up": demo_root(tmp, set_up=True)}
        servers = {}
        for name, root in roots.items():
            port = free_port()
            servers[name] = (serve(root, port), port)

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport=VIEWPORT, device_scale_factor=2)
            for which, path, filename in SHOTS:
                _server, port = servers[which]
                page.goto(f"http://127.0.0.1:{port}{path}", wait_until="networkidle")
                page.screenshot(path=str(IMAGES / filename), full_page=False)
                print(f"  {filename}  <- {path}")
            browser.close()

        for server, _port in servers.values():
            server.should_exit = True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\nWritten to {IMAGES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
