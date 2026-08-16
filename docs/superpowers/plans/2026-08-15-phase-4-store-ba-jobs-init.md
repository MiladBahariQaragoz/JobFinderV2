---
title: Phase 4 — the store, the Bundesagentur source, jobs-init.csv
date: 2026-08-15
type: phase-plan
status: done
---

# Phase 4 task plan

Branch: `feat/phase-4-store-ba-jobs-init`. Source of truth: `docs/MASTER_PLAN.md`
§ Phase 4, §5 (data contracts), §8 (etiquette), §9 (resume). One task = one commit,
the MASTER_PLAN box ticked in the same commit, pushed immediately.

## Verified API facts (probed live 2026-08-15 — do not re-derive)

- `wo` **must be the canonical umlaut spelling**, percent-encoded UTF-8:
  `wo=Muenchen` → 0 results (silent!), `wo=München` → 19 761. Our `City.name`
  values are already canonical — send them as-is through `urlencode`.
- `arbeitszeit` codes are **short**: `mj` (minijob), `tz` (Teilzeit), `vz` (Vollzeit),
  `snw` (Schicht/Nacht/Wochenende). Unknown values are silently dropped (0 results),
  so never guess codes. **Exactly one code per request** — repeated keys or
  comma-joined values (`mj,tz`) also answer 0 results silently (probed live
  2026-08-16 after a real run silently found nothing), so multi-type specs become
  one query per code.
- `angebotsart=1` = ARBEIT. Every result carries `stellenangebotsart: "ARBEIT"`.
- Search: `GET pc/v6/jobs` returns `ergebnisliste` (no description field),
  `maxErgebnisse` = total, `page` starts at 1.
- Details: `GET pc/v4/jobdetails/{base64(referenznummer)}` (standard base64,
  not urlsafe) returns the same shape plus `stellenangebotsBeschreibung`.
- Header `X-API-Key: jobboerse-jobsuche` (public constant) on both.
- `werkstudent` / `internship` have **no arbeitszeit code** — they ride in `was`
  ("Werkstudent" / "Praktikum"). Corrected 2026-08-16: each employment type gets
  its **own** query rather than stamping its term onto the others. Sending
  `was=Werkstudent` together with `arbeitszeit=mj` asks for a Werkstudent job
  that is also a minijob — 1 result in Ingolstadt against 116 for the minijob
  query alone. See `2026-08-16-phase-4-audit-and-search-shape.md`.
- The `externeURL` fallback shape (`jobboard.compleet.com`) is a client-rendered
  Nuxt SPA: static HTML holds no job text. Recorded as
  `tests/fixtures/ba/external_compleet_4913285274.html`; the fallback must treat
  "no extractable text" as a normal outcome (`has_description=0`), never a crash.
- Probing got a TCP reset after ~10 rapid calls — politeness is not optional.

## Tasks

### T1 — this plan doc
Commit: `docs: phase-4 task plan with verified BA API facts`.

### T2 — `sources/base.py`: `RawPosting` + `SourceAdapter`
`tests/unit/test_sources_base.py`: posting is frozen, defaults are falsy-safe,
`content_hash` helper hashes description text, gender-marker-aware normalisation
(`Werkstudent (m/w/d)` ≡ `Werkstudent (m/f/d)` ≡ `Werkstudent`) exists for dedupe.
Commit: `feat: RawPosting and SourceAdapter contract`.

### T3 — `sources/http.py`: `PoliteClient`
`tests/unit/test_http_client.py`, fake opener + fake clock + fake sleep + rng:
- waits ≥ configured delay between same-host requests (jitter bounds respected),
  no wait on first call, different hosts independent;
- second identical GET served from `data/http-cache/`, zero opener calls,
  expiry after TTL re-fetches;
- budget: network calls counted, cache hits not; over budget →
  `RequestBudgetExhausted`;
- 429 with `Retry-After: 2` sleeps 2 then retries; failures beyond max retries →
  `SourceUnavailable`;
- identifying `User-Agent` header on every request.
Commit: `feat: polite HTTP client — throttle, disk cache, budget, Retry-After`.

### T4 — BA query builder (`sources/ba.py`)
`tests/sources/test_ba.py` (query half):
- minijob spec → `angebotsart=1`, `arbeitszeit=mj`;
- three cities → three queries, each with its own `umkreis`, canonical `wo`;
- werkstudent-only spec → `was` gains `Werkstudent`, no `arbeitszeit`;
- keywords join `was`.
Commit: `feat: BA query builder on verified parameter values`.

### T5 — BA search parsing
`tests/sources/test_ba.py` (parse half) against the recorded fixture:
- entries → `RawPosting` with title/company/city/plz/lat/lon/published_at;
- `job_id` = `BA:{referenznummer}`;
- minijob flag from `istGeringfuegigeBeschaeftigung`, parttime/fulltime from
  `arbeitszeitTeilzeit*`/`arbeitszeitVollzeit`, homeoffice flag;
- pagination stops when `maxErgebnisse` reached (page fetch loop over fixture).
Commit: `feat: parse BA search pages into RawPostings`.

### T6 — BA details + external fallback
`tests/sources/test_ba.py` (detail half):
- details URL contains standard-base64 of `referenznummer`; answer fills
  description + content_hash;
- empty description + `externeURL` → external page fetched, readable text
  extracted; the real compleet SPA fixture extracts nothing → posting keeps
  `has_description=0`, no error.
Commit: `feat: BA detail fetch with external-URL fallback`.

### T7 — `store/db.py`
`tests/store/test_db.py`: fresh file creates all Phase-4 tables; reopening is a
no-op (idempotent migrations); **WAL + synchronous=NORMAL on every connection**
(§9 test); directory created if missing.
Commit: `feat: SQLite store with WAL and Phase-4 schema`.

### T8 — `store/jobs.py`
`tests/store/test_jobs.py`:
- upsert new → `new`, first_seen == last_seen;
- upsert same job_id again → one row, **only** `last_seen_at` moves (§5 re-run
  rule), description untouched;
- `dedupe_key` equal for the same job from two sources with different gender
  markers/spacing;
- status defaults to `new`.
Commit: `feat: job upsert with re-run rule and cross-source dedupe key`.

### T9 — `store/export.py`
`tests/store/test_export.py`:
- `jobs-init.csv` is `utf-8-sig`, `Bäckerei Müller & Söhne` round-trips;
- no blank lines on Windows (`newline=""`);
- full §5 column set, `status` column from the status table;
- crash mid-export leaves the previous CSV intact (tmp + `os.replace`) (§9).
Commit: `feat: atomic utf-8-sig jobs-init.csv export`.

### T10 — search runner (`search.py`) — the §9 resume contract
`tests/unit/test_search.py` with fake adapter/transport:
- killing after two pages keeps both pages on disk (KeyboardInterrupt injected
  on page 3);
- `--resume` continues at the stored cursor (query index + page), not page 1;
- network error mid-run → run marked `interrupted` with counts, no traceback;
- request budget exhaustion → stops, recorded in `runs.errors`;
- a failing source records its error and the run still returns what it has;
- stale `running` run marked `interrupted` on next start;
- per-page: postings written before the next page is fetched.
Commit: `feat: resumable search runner with runs journal`.

### T11 — CLI `jobfinder search`
`tests/unit/test_cli_search.py`:
- `--dry-run` prints the exact URLs (encoded `wo`, `umkreis`, params) and
  touches nothing;
- a normal run prints found/new/duplicate counts in her words and exits 0;
- interrupted run prints what was kept and how to resume.
Defaults: cities = Neuburg an der Donau, Ingolstadt, München; types =
werkstudent, minijob, parttime; override with `--cities/--types/--keywords/--radius`.
Commit: `feat: jobfinder search with dry-run and readable summary`.

### T12 — live contract test
`tests/live/test_ba_contract.py` (marked `live`): v6 search answers 200,
`ergebnisliste[0]` has `referenznummer` + `stellenangebotsTitel`, `size=50`
accepted (else the adapter's page size drops to 20), details endpoint for one
hit answers 200 with `stellenangebotsBeschreibung`.
Commit: `test: live BA contract — shape only, never counts`.

### T13 — done-when on real data
Real run for her cities → `data/jobs-init.csv`; immediate rerun adds 0 rows and
moves `last_seen_at`; CSV opens with umlauts intact and no blank rows; a killed
run loses nothing. Tick the Phase 4 done-when boxes, merge, push.
