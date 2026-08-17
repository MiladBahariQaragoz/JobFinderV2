---
title: JobFinderV2 Master Plan
date: 2026-08-15
type: master-plan
status: in progress — phases 0-8 done, Phase 8 verified on her real store; M4 shipped
---

# JobFinderV2 — Master Plan

**Goal:** One standalone app for one user — a master's student in Neuburg an der Donau
with limited German — that turns her CV into a shortlist of real, current, reachable
jobs in Bavaria, explains each one in English, and tracks what she has applied to.

**For plan executors:** Every phase below is implemented test-first (see
[TDD working agreement](#tdd-working-agreement)). Before starting a phase, write the
detailed task-level plan for it into `docs/superpowers/plans/YYYY-MM-DD-phase-N-<name>.md`
using the `writing-plans` skill, then execute it. This document is the map, not the
turn-by-turn directions.

---

## 1. The user and the constraints

| | |
|---|---|
| **Who** | One person. A master's student in Germany, living in Neuburg an der Donau. |
| **German** | Limited. Cannot be assumed to read a German job ad, and should not have to. |
| **Background** | Strong — master's in progress, real skills. Both qualified roles and general work are in scope. |
| **Base** | Neuburg an der Donau. Commutable: Neuburg, Ingolstadt, Munich. Also offered: Erlangen, Nürnberg, Würzburg, Ansbach, Regensburg, Augsburg, Landshut, Bamberg, Bayreuth, Passau. |
| **Wants** | Werkstudent, minijob, part-time, internship, or full-time — she picks per run. |
| **Scale** | One user, one laptop. No multi-tenancy, no accounts, no cloud, no server. |
| **Urgency** | Real. A usable build matters more than a complete one — see [milestones](#3-milestones). |

**Non-goals:** hosting this for anyone else, a public web service, a mobile app,
auto-applying to jobs on her behalf, or storing anything about her on a remote server.

---

## 2. Decisions already made

| Decision | Choice | Consequence |
|---|---|---|
| **App shape** | Local web app: FastAPI backend + server-rendered HTML, launched by one `.exe` that opens the browser | Real per-job pages, real buttons; packaging is a phase of its own (Phase 10) |
| **Storage** | SQLite is the source of truth; `jobs-init.csv` and `jobs-enriched.csv` are written row by row as work completes | Safe upserts, an interrupted run leaves a complete readable CSV, and the files she can open in Excel still exist |
| **Sources** | Free/official APIs **and** scrapers, both in v1 | Scrapers are plug-in adapters behind the same interface, with a per-source kill switch |
| **Language** | English UI, English job summaries; the original German text is always one click away | The LLM does the translation work, not her |
| **LLM** | `llmpool` only ([FreeLLMPool](https://github.com/MiladBahariQaragoz/FreeLLMPool)), no provider SDK anywhere | Free-tier pacing, failover and budget handling are already solved |
| **Resume format** | The existing `pool.template.yaml` schema in this repo | She fills one YAML file; no PDF parsing needed in v1 |

### On the scrapers

StepStone's `robots.txt` states that non-conforming robots are prohibited, and Xing
disallows its search paths. This was raised and the decision to include them stands:
this is one person searching for her own job, at human scale, on public listing pages.
The plan therefore builds them — with the constraints in
[§8 Scraping etiquette](#8-scraping-etiquette-non-negotiable), which exist to keep her
from getting IP-blocked halfway through a search rather than as legal theatre. Every
scraper is one adapter file that can be switched off without touching anything else,
because these break whenever a site is redesigned.

---

## 3. Milestones

Phases are ordered so that the app becomes useful before it becomes complete.

| Milestone | Phases | She can... |
|---|---|---|
| **M1 — Skeleton** | 0–1 | Nothing yet; the machinery exists and is tested |
| **M2 — Advice** | 2–3 | Fill in her CV and get job titles worth searching for, in German and English |
| **M3 — First real shortlist** | 4–5, 7 | **Done.** Run a search and get a CSV of live Bavarian jobs, each explained in English — `jobfinder search --enrich` |
| **M4 — The actual product** | 8 | **Done.** Browse, filter, read, and mark jobs applied/deleted in a real UI — `jobfinder serve`, searches started and cancelled from the browser |
| **M5 — Wider net** | 6, 9 | **Done.** Kleinanzeigen, Xing and Adzuna searched in parallel (StepStone and Indeed are blocked from this machine and ship off), and the call-list holds 357 places, 255 reachable — `jobfinder contacts`, or the Call page |
| **M6 — Handover** | 10 | Double-click one file on her own laptop and use it without help |

**If time gets short, ship M4 and stop.** Phases 6 and 9 are additive; nothing in
8 or 10 depends on them. **M4 has shipped**, so everything from here is either
reach (Phase 9's call-list) or handover (Phase 10's `.exe`).

**Next up: Phase 10, the handover** — she can use the app today only by way of a
terminal and a virtualenv, which is not delivery. Phase 9 is the wider net and
can follow it.

The gap Phase 8 left — 20 of her 859 stored jobs explained, with no way to change
that outside a terminal — now has a button (see
[Wanted next](#wanted-next--asked-for-after-using-the-app)). It is still a gap:
**837 jobs are waiting**, one free-tier call each, and the honest way through
them is a few bounded passes rather than one heroic run. The app renders an
unexplained job truthfully ("not read yet", no fit score), so this costs
correctness nothing — but the product only becomes itself once most of that store
is explained, and now that is her decision to make rather than a developer's.

---

## 4. Architecture

```
                    pool.yaml (her CV)          .env (LLM keys)
                          |                          |
                          v                          v
                    +-----------+            +---------------+
                    |  profile  |            |   llm layer   |
                    |  + search |            | llmpool + cache|
                    |    spec   |            +-------+-------+
                    +-----+-----+                    |
                          |                          |
        +-----------------v------------------+       |
        |          source registry           |       |
        |  BA | Arbeitnow | Adzuna | Kleinanz.|       |
        |  StepStone | Indeed | Xing | Overpass|      |
        +-----------------+------------------+       |
                          | RawPosting                |
                          v                           v
                  +---------------+          +------------------+
                  |    store      |<---------|    enrichment    |
                  | SQLite + CSV  |  fields  | skills, German   |
                  |  export       |          | level, fit, EN   |
                  +-------+-------+          +------------------+
                          |
                          v
                  +---------------+
                  |  web app      |  list -> filters -> job page
                  | FastAPI+HTML  |  applied / delete / notes
                  +---------------+
```

**The one rule that keeps this maintainable:** every source is an adapter behind the
same interface, and nothing downstream knows whether a job came from a government API
or a scraped page.

### Repository layout

```
src/jobfinder/
  config.py          settings, paths, .env loading
  profile.py         her CV (pool.yaml) + search preferences -> validated objects
  cities.py          the Bavarian city list, coordinates, radius defaults
  llm/
    pool.py          builds the llmpool Pool once per run
    prompts/         one file per prompt, versioned (roles.v1.md, enrich.v1.md)
    schema.py        expected JSON shapes + validators passed to the Pool
    cache.py         content-hash cache so nothing is enriched twice
  sources/
    base.py          SourceAdapter interface, RawPosting dataclass
    registry.py      enable/disable, ordering, per-source config
    ba.py            Bundesagentur für Arbeit Jobsuche  (API)
    arbeitnow.py     Arbeitnow                          (API)
    adzuna.py        Adzuna                             (API, optional key)
    kleinanzeigen.py Kleinanzeigen classifieds          (scraper — best minijob source)
    stepstone.py     StepStone                          (scraper)
    indeed.py        Indeed                             (scraper)
    xing.py          Xing                               (scraper)
    overpass.py      OpenStreetMap POIs for general work (API)
    http.py          shared polite HTTP client: throttle, cache, retry
  store/
    db.py            SQLite schema + migrations
    jobs.py          upsert, dedupe, status transitions
    export.py        jobs-init.csv / jobs-enriched.csv / contacts.csv writers
  enrich/
    runner.py        batch enrichment over llmpool, resumable
    fields.py        the enrichment contract (what every job must end up with)
  web/
    app.py           FastAPI app
    routes.py        list, detail, status actions
    templates/       Jinja2: index.html, job.html, contacts.html
    static/
  cli.py             typer/argparse entry points
scripts/
  llm_smoke.py       already exists
tests/
  unit/              pure logic, no I/O
  fixtures/          recorded API JSON and saved HTML pages
  sources/           one contract test per adapter, run against fixtures
  live/              opt-in tests that hit the real internet (marked)
  web/               route + template tests, Playwright smoke
data/                gitignored: jobfinder.db, CSV exports, http cache
```

---

## 5. Data contracts

These are the interfaces between phases. Changing one means changing a migration and
an export test, so they are settled here rather than per phase.

### Job identity

| Field | Rule | Example |
|---|---|---|
| `job_id` | `{SOURCE}:{native id}` — stable, the primary key | `BA:11119-4913285274-S` |
| `source` | Short code per adapter | `BA`, `AN`, `AZ`, `KA`, `SS`, `ID`, `XI` |
| `dedupe_key` | `sha1(normalized_title + normalized_company + normalized_city)` — catches the same job listed on three sites | `9f2c…` |
| `content_hash` | `sha1(description)` — changes only when the ad text changes, drives re-enrichment | `41ab…` |

**The re-run rule:** a search that finds a `job_id` already in the database updates
`last_seen_at` and nothing else. Enrichment is skipped unless `content_hash` changed
or the prompt version changed. This is what stops the app from spending her free LLM
quota on the same 200 jobs every morning.

The same rule governs requests: a job already stored **is not fetched in detail
again**, because the answer would be discarded. Detail fetches stay in the search
rather than moving into enrichment — Phase 5's cross-source merge needs the
description at search time to decide which sighting is the richest, and
`has_description` is a Phase 4 contract. Phase 7 revisits that only if live budgets
prove it necessary.

### SQLite tables

| Table | Holds | Notes |
|---|---|---|
| `jobs` | one row per posting, raw facts from the source | never overwritten by the LLM; `published_at` keeps whatever the source said and `published_on` (v7) is the same date made comparable |
| `job_descriptions` | full text, kept out of `jobs` so exports stay small | German original |
| `enrichment` | LLM-derived fields, keyed by `job_id` + `prompt_version` | re-enrichment appends, never destroys |
| `status` | her decisions: `new`, `interested`, `applied`, `rejected`, `deleted` + notes + dates | the only table she writes to |
| `contacts` | general-work places from Overpass: name, type, city, phone, email, website | separate flow, separate page |
| `runs` | one row per search run: spec, sources hit, counts, errors, duration | debuggability when something returns nothing |
| `source_state` | per-source cursors, last success, consecutive failures, cooldown | mirrors how llmpool remembers providers |

### `jobs-init.csv` (exported after every search)

`job_id, source, source_id, dedupe_key, title, company, city, plz, lat, lon,
employment_type_raw, is_minijob, is_parttime, is_fulltime, is_internship,
is_werkstudent, homeoffice, published_at, apply_url, source_url, also_seen_on,
has_description, content_hash, first_seen_at, last_seen_at, status`

`also_seen_on` (added in Phase 5) lists the other sites the same ad was seen
on, comma-joined — cross-source dedupe keeps the first row and records every
alternate sighting there instead of storing the job twice.

The CSV carries `published_at` and not the derived `published_on`: the column
list above is what she opens in a spreadsheet, and a second date column beside
the first would only invite the question of which one is real. The derived value
exists so the app can compare dates, and lives in the database only.

Two rules the key has to obey, both learned from live data:

- **The location in the key is the city, never the postcode.** The BA answers
  with a `plz`, Arbeitnow answers with none at all, so a postcode-based key
  could never match the same ad across those two sources. City names are
  folded before hashing — the BA's `"Ingolstadt, Donau"` is `"Ingolstadt"`.
- **Merging happens only across sources.** One site listing two openings with
  the same title, company and town means two jobs she can apply to: a live BA
  query returned two Penny-Markt Werkstudent ads in Neuburg under two
  reference numbers, and collapsing those would delete one of them.

### `jobs-enriched.csv` (exported after every enrichment run)

`job_id, enriched_at, prompt_version, provider_used, category, seniority,
skills_required, skills_nice, german_level, german_evidence, english_sufficient,
employment_type_norm, hours_per_week, duties_en, requirements_en, summary_en,
fit_score, fit_reasons, missing_for_fit, red_flags, application_method,
contact_email, contact_phone, deadline`

- List fields (`skills_*`, `duties_en`) are pipe-separated, never comma-separated.
- `german_level` is one of `none, A1, A2, B1, B2, C1, C2, unclear` and must be
  backed by `german_evidence` — the phrase in the ad that justifies it.
- `fit_score` is 0–100 against her CV, and `missing_for_fit` names what she lacks.
  Both are advisory; nothing is hidden from her because of a low score.

### `contacts.csv` (general-work mode)

`contact_id, name, kind, city, street, phone, email, website, back_of_house_score,
osm_id, first_seen_at, last_contacted_at, outcome, notes`

### Encoding rules (Windows + German text)

Every CSV is written UTF-8 **with BOM** (`utf-8-sig`) and `newline=""`, or Excel will
mangle every `ä`, `ö`, `ü` and `ß` she reads. This is a test, not a comment — see
Phase 4.

---

## 6. Source registry

Verified live on 2026-08-15 from this machine — the results below are facts, not
assumptions, and the failures are recorded so nobody re-discovers them.

| Source | Status | How it works | Notes |
|---|---|---|---|
| **Bundesagentur für Arbeit** | ✅ verified `200` | `GET rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs` with header `X-API-Key: jobboerse-jobsuche`; details via `pc/v4/jobdetails/{base64(referenznummer)}` | The backbone. Germany's largest job database, free, no signup. Returns `istGeringfuegigeBeschaeftigung` (minijob), `arbeitszeitTeilzeit*`, `arbeitszeitVollzeit`, `homeofficemoeglich`, `entfernung` (km from `wo`), and ~3 000-character German descriptions for most ads. |
| | ⚠️ | `pc/v4/jobs` → `403`, `pc/v6/jobdetails` → `403`, OAuth `gettoken_cc` → `403` | Use v6 for search, v4 for details. Do not "fix" this by switching versions. |
| | ⚠️ | ~1 in 3 ads has an empty `stellenangebotsBeschreibung` and only an `externeURL` | Fallback: fetch the external URL and extract text (Phase 4). |
| **Arbeitnow** | ✅ verified `200` | `GET www.arbeitnow.com/api/job-board-api`, no key, CORS open | Tech/English-friendly DACH roles, paginated. Good for her qualified-role search, weak on Bavaria-specific and non-tech work. |
| **Adzuna** | ✅ verified `200`, key registered 2026-08-16 | `api.adzuna.com/v1/api/jobs/de/search/{page}` with free `app_id`/`app_key` | Measured, not assumed: **204** minijobs for Ingolstadt, **84 %** of rows absent from the Bundesagentur set. Its description is a **500-character teaser**, so `fetch_detail` follows `redirect_url` for the real ad — good for the first ~40 of a run, after which adzuna.de serves a sign-in wall and the rest keep teasers. Which board is behind a row is never visible. A source of leads, not of readable ads. Absent keys mean skipped, never an error. |
| **OpenStreetMap Overpass** | ✅ shipped (Phase 9) | `POST` one small query per tag, to the first of five endpoints that answers | The cold-contact engine. Measured 2026-08-17: Neuburg **118** places / **34** reachable at 6 km, Ingolstadt **304** / **219**. Hotels are `tourism=hotel`, not `amenity=hotel`. **It rate-limits by IP:** after a few hundred queries every endpoint refused this machine at once while the rest of the internet was fine, so the gap is 10 s and a tag is retried on two hosts, not five. **Munich at 6 km never returned**, and a later probe says why: 3 km around Marienplatz holds **3019** elements against Neuburg's 118 at 6 km, so the city needs its own radius. That probe also had to go outside the endpoint list to get an answer at all — the block is one operator's, and a public mirror served Munich in 43 s. |
| **StepStone** | ⛔ blocked below HTTP (re-probed 2026-08-16) | Search results page → listing pages | Every request is reset at the transport level — TLS-fingerprint filtering, so a User-Agent change buys nothing. Adapter built and tested against the failure path, **off by default**, skip line says why. Only a real browser would change this, which Phase 6 rules out. |
| **Indeed** | ⛔ `403` + WAF page (re-probed 2026-08-16) | Search results page → listing pages | Answers with a 27 KB block page. No sanctioned API exists — their publisher API is closed to new signups. Built, tested against the recorded 403, **off by default**. |
| **Xing** | 🔨 scraper | Public job pages | `robots.txt` disallows `/search/` and `/publicsearch/`. Public listing pages only, never anything behind login. |
| **Kleinanzeigen** | ✅ verified `200`, scraper | `GET www.kleinanzeigen.de/s-jobs/{city}/c102l{locationId}` → 25 listings per page, then `/s-anzeige/{slug}/{id}` | **Probably her best source for minijobs.** This is where Bavarian bakeries, kitchens, cleaning firms and shops actually post. Verified: 25 parseable listing links and 27 JSON-LD blocks on one page, ads like "Aushilfe im Verkauf Minijob", "Reinigungskraft als Minijob". Category `c102` is Jobs. |
| | ⚠️ | The `l{id}` code is a Kleinanzeigen location id, not a city name — `l7414` resolved to Stockstadt, not Ingolstadt | A verified city → location-id map is a deliverable, not something to guess at runtime. |

**Adding a source later** must mean writing one adapter file plus one fixture-backed
contract test. If it ever means touching the store, the enrichment, or the UI, the
interface is wrong.

---

## 7. TDD working agreement

Follow `~/.claude/commands/test-driven-development.md` exactly: **no production code
without a failing test first**, watch every test fail, then write the minimum to pass.
The rules below are the project-specific parts of that.

### Test layers

| Layer | Location | Speed | Hits network |
|---|---|---|---|
| **Unit** | `tests/unit/` | ms | Never |
| **Contract** | `tests/sources/` | ms | Never — parses recorded fixtures |
| **Store** | `tests/store/` | ms | Never — temp SQLite file |
| **Web** | `tests/web/` | fast | Never — FastAPI TestClient; one Playwright smoke |
| **Live** | `tests/live/` | slow | Yes — `pytest -m live`, run manually and weekly |

`pytest` with no arguments must never touch the internet or spend an LLM call.
That is enforced by an autouse fixture that raises on outbound sockets outside
`tests/live/`.

### Fixtures are recorded, never hand-written

Every adapter test parses a real captured response saved under `tests/fixtures/<source>/`
by a small `scripts/record_fixture.py`. Hand-written JSON tests pass against code that
cannot parse the real thing.

### Live tests answer one question only

Not "did we get 4 results for Kellner" — that changes hourly. They assert **shape**:
the endpoint still answers, the fields the adapter reads still exist, the auth header
still works. When a live test fails, the fixture is stale and the adapter needs updating.

### The LLM in tests

- `FakePool` implements `complete_json`/`complete_text` and returns canned answers.
  Every enrichment and recommendation test uses it.
- The **validator** passed to the real `Pool` is itself unit-tested against junk:
  missing keys, wrong `german_level` values, prose instead of JSON.
- Exactly one live LLM test, marked, that enriches one real posting end to end.

### Commit rhythm — one task, one commit, pushed (source code only)

Version control tracks **development progress**: code, tests, and this plan. It never
touches her data — `data/`, both CSVs, the database, `pool.yaml` and `.env` are
gitignored and stay on her laptop. Runtime saving is a different mechanism entirely,
covered in [§9](#9-incremental-saving-and-resume-runtime-data).

**Every time a checklist item in this document is finished, it is closed out on the
spot:**

1. Tick the box in `docs/MASTER_PLAN.md` — `- [ ]` becomes `- [x]`
2. `git commit` the code, its tests and the ticked box together, message in the form
   `type: what and why`
3. `git push` immediately — no batching, no end-of-day dump

The plan is therefore the live progress record: at any moment, the ticked boxes on
GitHub are exactly what works. Nothing is "done but not pushed", so picking the work
back up after a break needs no reconstruction of where it stopped.

A red test is not a task. Commit at green, or at green-plus-refactor.

### Definition of Done — applies to every phase

- [ ] Every new behavior had a failing test first, and the failure was watched
- [ ] `pytest` green, no network, no warnings
- [ ] `ruff check` and `ruff format --check` clean
- [ ] The phase's own "she can now…" statement is demonstrably true on real data
- [ ] `docs/` updated where the phase changed a contract
- [ ] Work committed on `feat/phase-N-<name>`, pushed, atomic commits

---

## 8. Scraping etiquette (non-negotiable)

These are engineering constraints that keep her searches working, and they are tested.

1. **One request at a time per host**, with ±1 s jitter and a minimum gap that
   depends on what the host is: **3 s for a scraped site**, **1 s for a
   documented API** (Bundesagentur, Arbeitnow, Adzuna, Overpass). The 3 s rule
   exists because a scraper that hammers a site gets her IP blocked; an API
   published for programmatic use is not that, and spending seven minutes on
   one search out of misplaced caution is its own failure. Neither API
   documents a rate limit, so 1 s is a judgment call backed by rule 5 —
   a 429 is honoured, backed off and, if it persists, kills the source.
   Measured live on 2026-08-16: a cold Augsburg minijob search spent 268
   requests in 402 s (1.50 s each, the 1 s gap plus mean jitter) and returned
   263 jobs with no 429 and no failed source. The same run at the old pace
   would have taken 15.6 minutes. **No parallel fetching of one host, ever**,
   whatever kind it is.
2. **Different hosts may be fetched in parallel** — one worker per host, each
   keeping its own gap from rule 1. Sources are serialised today, which costs
   nothing while one source holds most of the requests but multiplies wall
   time once Phase 6 adds four scrapers on four hosts (measured shape: four
   sources × 60 requests is 14 minutes serial, 3.5 minutes in parallel).
   Two conditions before any of it runs concurrently:
   - The **throttle must be shared per host, not per client.** Each adapter is
     built with its own `PoliteClient` today, so two adapters pointed at one
     host would each keep their own `_next_allowed` and both think they are
     clear — rule 1 broken with no test failing. A process-wide, lock-guarded
     host → next-allowed registry is the fix.
   - The **store must tolerate concurrent writers**: an explicit `busy_timeout`
     on every connection and one connection per thread. WAL lets readers
     through a write, but two writers still take turns, and the one that
     arrives second must wait rather than raise `database is locked`. The
     Python driver happens to default to 5 s, which is why this worked before
     anyone stated it; `connect()` now sets 15 s deliberately, and the
     per-thread rule is enforced by sqlite3's own guard — a worker calls
     `connect()` again instead of sharing the search's connection.

   Both prerequisites shipped in v0.3.0; the measurements behind rules 1 and 2,
   and the two mistakes made proving them, are in
   [the pacing change record](superpowers/plans/2026-08-16-request-pacing-and-concurrency.md).
3. **Cache every fetched page for 24 h** in `data/http-cache/`. A re-run must not
   re-fetch. Tests assert the second call hits the cache.
4. **A real identifying User-Agent** with a contact address. No pretending to be
   Chrome-on-someone-else's-machine.
5. **Honor `Retry-After` and back off exponentially** on 429/503, then trip the
   source's kill switch after 3 consecutive failures and move on. One dead source
   never fails the run.
6. **Public pages only.** No login, no session cookies, no CAPTCHA-solving service,
   no proxy rotation. If a page needs an account, the adapter skips it.
7. **Per-source kill switch** in config; `sources.stepstone.enabled: false` is a
   one-line fix when a site changes and she needs results today.
8. **Request budget per leg of a run** (default 800) so a bug cannot turn into a
   flood. A search that spends its budget is continued automatically with a fresh
   one, which is safe only because `max_search_legs` (default 6) bounds the total
   and any stop that is not a spent budget ends the search there.

---

## 9. Incremental saving and resume (runtime data)

> **Two different things share the word "commit" in software, so this document does not
> use it loosely.** This section is about the **running app saving her data to disk** —
> SQLite and CSV, on her laptop. Git is never involved: `data/` is gitignored, and her
> jobs, CV and contacts are never pushed anywhere. Version control of the *source code*
> is [§7's commit rhythm](#commit-rhythm--one-task-one-commit-pushed), a separate matter.

**The rule: nothing lives only in memory.** Every unit of work is written to disk the
moment it completes. Her internet drops on a train, a free-tier quota runs out at job
143 of 400, she closes the laptop lid — in every case the app keeps what it had and
continues from there. This is a first-class requirement, not error handling bolted on
later.

### How it works

| Mechanism | Detail |
|---|---|
| **Unit of work** | One fetched page, one stored job, one enriched job, one contact. Each is written in its own SQLite transaction, straight away. |
| **Enrichment lands twice** | The instant an answer passes validation it is written to the `enrichment` table **and** appended to `jobs-enriched.csv`. If the app dies one second later, both files already hold it. |
| **SQLite mode** | WAL journal, `synchronous=NORMAL`. Survives a hard kill without corrupting the database. |
| **Run journal** | `runs` holds one row per search/enrich/contacts run: spec, started_at, `last_progress_at`, state (`running`, `done`, `interrupted`, `failed`), counters. Updated as work lands, not at the end. |
| **Per-source cursors** | `source_state` stores the query hash and the last completed page per source. A resumed search re-enters at that page instead of at page 1. |
| **Idempotent writes** | `job_id` is the primary key; enrichment is keyed by `(job_id, prompt_version)`. Replaying work already done changes nothing and costs nothing. |
| **CSV as it goes, not at the end** | Rows are appended and flushed per result, so the CSV is usable mid-run. A full, sorted re-export runs at the end of a run — written to `*.tmp` then `os.replace()`d, so a crash mid-export leaves the previous good CSV intact, never a half file. |
| **Stale run detection** | A `running` row whose `last_progress_at` is older than the heartbeat interval is marked `interrupted` on next start, so the app never claims to be doing something it is not. |
| **Nothing partial is stored** | An LLM answer that fails validation is discarded, not written half-parsed. The job stays unenriched and gets retried. |

### Enrichment does not wait for the search to finish

A search is bound by HTTP pacing against job-site hosts; enrichment is bound by
LLM providers on entirely different hosts, paced by `llmpool`. Running them one
after the other adds their wall times together for no reason — the two never
contend for the same host, and §9 already makes the handover safe: every job is
committed to SQLite the moment it is stored, so a job that exists is a job that
can be enriched.

- **The store is the queue.** The enrichment worker polls for jobs with a
  description and no `enrichment` row at the current `prompt_version`. No
  in-memory queue, no handoff between the two, and an interrupted search leaves
  a partially enriched but perfectly consistent database.
- **`jobfinder search --enrich` runs both**, search in the foreground with its
  page lines, enrichment as a second worker narrating its own counts. Either
  command alone must still work exactly as it does now.
- **Prerequisite:** `busy_timeout` on every connection and one connection per
  thread (§8 rule 2). Without them the second writer fails instantly rather
  than waiting.
- **Her quota is the limit that matters**, not throughput: enrichment stops on
  `PoolExhausted` and says so, whether or not the search is still running.

### Failure semantics — what happens, and what she sees

| Failure | Kept | On resume |
|---|---|---|
| Internet drops mid-search | Every page already fetched and stored | Continues from the last completed page of each source |
| A source blocks or times out | Everything from the other sources | That source is skipped or retried; the run does not fail |
| LLM quota exhausted (`PoolExhausted`) | Every job enriched so far | "143 of 400 enriched — quota spent. Resume tomorrow, or add another key." Resuming skips the 143. |
| She closes the app / Ctrl-C | Everything saved up to that second, in both the database and the CSV | "Interrupted run — Resume" offered on next start |
| Power loss | Same, WAL-protected | Same |
| A single job's enrichment fails | All others | That job alone is retried next run |

### Commands and UI

- `jobfinder search --resume` and `jobfinder enrich --resume` continue the newest
  interrupted run; without the flag, a new run starts and finished work is still skipped
- The web app shows an interrupted run as a banner with a **Resume** button, and the
  counts it left behind
- Every run's summary is stored, so "what happened last night" is answerable

### Tests (owned by Phases 4, 7 and 9, listed together because the rule is shared)

- [x] `test_killing_after_two_pages_keeps_both_pages_on_disk`
- [x] `test_resume_continues_at_the_stored_cursor_not_page_one`
- [x] `test_network_error_mid_run_marks_run_interrupted_with_counts`
- [x] `test_a_spent_quota_stops_the_run_rather_than_retrying_every_job` (with
      `test_batch_persists_each_result_as_it_lands`: quota spent mid-batch keeps
      every completed enrichment)
- [x] `test_a_second_run_enriches_nothing_and_makes_zero_calls` — resuming after
      a spent quota skips what is already explained
- [x] `test_a_junk_answer_is_refused_and_leaves_that_job_unenriched` — never
      half-written
- [x] `test_the_csv_line_lands_with_the_answer_not_at_the_end_of_the_run`
- [x] `test_an_interrupted_run_leaves_a_csv_she_can_open` — readable mid-run,
      holding every finished job
- [x] `test_crash_mid_export_leaves_the_previous_csv_intact` (write to tmp, fail, assert old file)
- [x] `test_stale_running_run_is_marked_interrupted_on_next_start`
- [x] `test_a_second_run_enriches_nothing_and_makes_zero_calls` and
      `test_same_job_twice_leaves_one_row` — a second full run with nothing
      changed spends no LLM call and adds no row
- [x] `test_every_connection_runs_wal_and_synchronous_normal`
- [x] `test_connecting_while_another_writer_holds_a_new_database_still_works` —
      the second writer waits rather than raising `database is locked`
- [x] `test_enrichment_started_during_a_search_enriches_what_the_search_stored`

---

## 10. UX principles

She is not a developer, she is under pressure, and a screen that sits still reads as
broken. **The panic rule: at any moment she must be able to answer three questions
from what is on screen — is it working, how far along is it, and how long is left.**

### Progress and feedback

| Situation | What she sees |
|---|---|
| Any action over ~1 s | Immediate acknowledgement — the button enters a working state, nothing looks unclicked |
| Search running | A determinate progress bar (pages done / pages expected), the current source and city in words, live counters: found / new / duplicates, and elapsed time |
| Per source | One line each: `Bundesagentur — 42 found, 7 new`, `StepStone — searching…`, `Indeed — skipped (disabled)`. A failed source says so in plain English and the run continues |
| Enrichment running | `143 of 400 jobs explained`, a progress bar, the title of the job being processed, and an estimate from the observed average |
| Long waits inside a run | The reason, in her words: "Waiting 40 s for a free provider slot" — never a frozen bar |
| Any run | A **Cancel** button that is always safe to press, because of [§9](#9-incremental-saving-and-resume-runtime-data) |
| After a run | A summary that stays on screen: what was searched, per-source counts, what failed, what to do next |

**Progress is read from the database, not from memory.** If she reloads the page or
closes and reopens the browser mid-run, the progress bar is still there and still
correct. This falls out of §9 and is tested as such.

### States that must exist before a page is called done

Loading (skeleton rows matching the real layout, not a spinner), empty (what was
searched, why it found nothing, and the one filter to loosen), error (plain sentence
plus the fix — "No API key yet. Add one in Settings."), and success. A page with only
its success state is not finished.

### Visual system

Built for reading a lot of structured information quickly, not for looking clever.

- **Stack:** Jinja2 templates + HTMX for interactivity + one bundled CSS file. No build
  step, no CDN — the packaged `.exe` must work offline, so fonts and scripts ship inside it.
- **Type:** `Geist` (or `Satoshi`) for text, `JetBrains Mono` for every number — fit
  score, distance in km, dates, counts. Never `Inter`, never a serif in this UI.
- **Colour:** neutral zinc base, exactly **one** desaturated accent. No purple-blue AI
  glow, no neon, no gradient text, no pure black. German level and fit score get a
  restrained three-step scale (comfortable / stretch / out of reach) that reads in
  greyscale too.
- **Density ~6:** an information app, not an art gallery. Group with `divide-y` and
  1 px rules; use a card only where elevation actually means something. No three-equal-cards
  row.
- **Motion:** CSS transitions only, 150–250 ms, `transform` and `opacity` exclusively.
  Tactile `:active` press on buttons. Nothing decorative that moves while she reads.
- **No emoji anywhere in the UI.** Inline SVG icons, one stroke width throughout.
- **Language:** every string is plain English written for her, not log output.
  `Bundesagentur — 42 found` beats `GET /pc/v6/jobs 200`.

### Tests for the above (owned by Phase 8)

- [x] `test_search_progress_is_persisted_and_survives_a_page_reload`
- [x] `test_progress_endpoint_reports_current_source_and_counts`
- [x] `test_cancel_stops_the_run_and_keeps_completed_work`
- [x] `test_every_list_page_renders_a_skeleton_state`
- [x] `test_empty_result_page_names_the_filters_that_were_applied`
- [x] `test_missing_api_key_renders_a_sentence_and_a_link_not_a_traceback`
- [x] `test_interrupted_run_banner_offers_resume_with_the_right_counts`
- [x] `test_no_emoji_in_any_template` (a grep test — cheap, and it holds the line)
- [x] `test_numbers_render_in_the_monospace_class`
- [x] `test_a_long_run_keeps_its_heartbeat_beating` — the progress panel is only
      honest if the journal behind it keeps time; a real run proved it did not

---

## Phase 0 — Skeleton and test harness

**Goal:** A repository where writing a failing test is the path of least resistance.

**Why first:** Every later phase's Definition of Done says "pytest green, no network".
That sentence has to mean something before Phase 1.

### Deliverables

- `pyproject.toml`: package `jobfinder` under `src/`, pytest + ruff config, markers
  `live` and `live_llm` registered
- `src/jobfinder/config.py`: `Settings` object — data dir, db path, enabled sources,
  request budget, LLM budget — loaded from `config.yaml` + `.env`, with defaults that
  work on a fresh machine
- `tests/conftest.py`: `no_network` autouse fixture, `tmp_data_dir` fixture,
  `fixture_path()` helper
- `scripts/record_fixture.py`: saves a live response into `tests/fixtures/<source>/`
- `pytest.ini` markers documented in README; `ruff` clean on the existing files

### Test-first checklist

- [x] `test_settings_defaults_point_into_data_dir` — fails, then implement `Settings`
- [x] `test_settings_override_from_config_yaml` — plus defaults and a typo'd key that
      names itself and the valid settings
- [x] `test_secrets_are_read_from_env_not_config_yaml` — a key in `config.yaml` is
      rejected outright, `.env` is loaded, and an already-set variable wins over it
- [x] `test_outbound_connection_is_blocked` — proves the guard actually bites:
      `create_connection`, raw `connect`, the host named in the error, localhost still allowed
- [x] `test_live_markers_are_registered` — both markers registered, live tests deselected
      by default, `pytest -m live` selects them, and the live lane really can reach out
- [x] `test_json_fixture_is_pretty_printed_under_the_source_directory` — plus verbatim HTML,
      umlauts intact, and an error page kept rather than discarded

### Done when

- [x] `pytest` runs in under 2 seconds and is green — 18 passed in 0.95 s, clean under
      `-W error`
- [x] A deliberate `requests.get("https://example.com")` inside a unit test fails loudly
- [x] `pip install -e .` then `python -c "import jobfinder"` works in the venv

**Phase 0 complete.** `ruff check` and `ruff format --check` clean, `pytest -m live`
green, and `scripts/record_fixture.py` has recorded its first real Bundesagentur
response into `tests/fixtures/ba/`.

**Out of scope:** CI. One user, one laptop — a pre-commit hook running ruff + pytest
is enough, and even that is optional.

---

## Phase 1 — Her CV and her preferences

**Goal:** Two validated inputs — who she is, and what she is looking for this run.

**Why:** Everything downstream keys off these. A typo in a city name must produce a
readable error at second zero, not an empty result list after four minutes of searching.

### Deliverables

- `pool.template.yaml` stays as the blank template (already in the repo); her filled
  copy is `pool.yaml`, **gitignored** — it holds her name, address and email
- `src/jobfinder/profile.py`: parses `pool.yaml` into a `Resume` object — basics,
  languages, experience, projects, education, skill groups, certifications
- `src/jobfinder/cities.py`: the Bavarian city list with coordinates and default radius —
  Neuburg an der Donau, Ingolstadt, München, Erlangen, Nürnberg, Würzburg, Ansbach,
  Regensburg, Augsburg, Landshut, Bamberg, Bayreuth, Passau
- `src/jobfinder/search_spec.py`: `SearchSpec` — mode (`resume` | `general`),
  employment types (`minijob`, `werkstudent`, `parttime`, `fulltime`, `internship`),
  cities + radius per city, German level she is comfortable with, keywords
- `jobfinder profile validate` and `jobfinder profile show` CLI commands

### Test-first checklist

- [x] `test_parses_the_blank_template_without_crashing` — the shipped template must load
- [x] `test_missing_required_basics_names_the_field_and_the_line`
- [x] `test_language_levels_parse_including_mother_tongue`
- [x] `test_experience_dates_accept_yyyy_mm_and_present`
- [x] `test_invalid_date_reports_the_entry_id_not_a_stack_trace`
- [x] `test_unknown_city_lists_the_valid_ones` — the error message is the feature
- [x] `test_city_radius_defaults_to_25km_and_can_be_overridden`
- [x] `test_search_spec_rejects_empty_employment_types`
- [x] `test_general_mode_does_not_require_a_resume` — she can search for kitchen work
      before her CV is finished
- [x] `test_resume_mode_requires_a_readable_pool_yaml`

### Done when

- [x] She fills `pool.yaml` and `jobfinder profile validate` prints a green summary:
      name, languages, 3 strongest skill groups, years of experience
- [x] Every failure mode above prints one sentence a non-programmer can act on

**Out of scope:** PDF/DOCX CV parsing. She has the YAML; asking her to fill one file
once is cheaper than building a parser that guesses.

---

## Phase 2 — The LLM layer

**Goal:** One place where this project talks to a model, with caching and budgets,
and a `FakePool` that makes every later LLM feature testable offline.

**Why before any prompt:** if enrichment is written first, the cache and the budget
get bolted on afterwards, and her free quota gets burned re-answering questions the
app already knows the answer to.

### Deliverables

- `src/jobfinder/llm/pool.py`: `build_pool()` — one `Pool` per run, validator injected,
  `state_path=data/pool_state.json`, `max_wait` and `run_deadline_seconds` from settings
- `src/jobfinder/llm/prompts/`: one Markdown file per prompt, filename carries the
  version (`roles.v1.md`, `enrich.v1.md`); the version string lands in the database
- `src/jobfinder/llm/schema.py`: expected JSON shape per prompt + the validator function
  `llmpool` calls; unknown keys tolerated, missing/invalid keys rejected with a reason
- `src/jobfinder/llm/cache.py`: SQLite-backed, keyed by
  `sha1(prompt_version + content_hash + spec_fingerprint)`
- `tests/fakes.py`: `FakePool` — canned answers, records calls, can simulate
  `PoolExhausted` and junk answers
- `jobfinder llm doctor` — wraps `python -m llmpool doctor` and reports the cache size

### Test-first checklist

- [x] `test_validator_accepts_a_well_formed_answer`
- [x] `test_validator_rejects_missing_required_key_with_named_reason`
- [x] `test_validator_rejects_prose_masquerading_as_json`
- [x] `test_validator_rejects_out_of_range_enum_value` (e.g. `german_level: "fluent"`)
- [x] `test_cache_returns_stored_answer_without_calling_the_pool` — assert the fake
      recorded zero calls
- [x] `test_cache_misses_when_prompt_version_changes`
- [x] `test_cache_misses_when_content_hash_changes`
- [x] `test_pool_exhausted_is_surfaced_as_a_handled_error_not_a_crash`
- [x] `test_build_pool_raises_a_readable_error_when_no_provider_keys_exist`
- [x] `tests/live/test_llm_smoke.py` (marked `live_llm`) — one real call, valid JSON back

### Done when

- [x] `pytest` covers every LLM path with zero real calls
- [x] `pytest -m live_llm` passes with one provider key present
- [x] Running the same enrichment twice makes exactly one provider call

**Out of scope:** streaming, function calling, embeddings. `complete_json` covers
everything this product needs.

---

## Phase 3 — Role recommendations from her CV

**Goal:** She fills in her CV, runs one command, and gets job titles worth searching
for — in German, because that is what the search boxes need.

**Why here:** it is the first thing she sees working, it needs only Phases 1–2, and
its output feeds the search keywords in Phase 4.

### Deliverables

- `src/jobfinder/llm/prompts/roles.v1.md` — takes the CV summary, returns 8–12 roles:
  `title_de`, `title_en`, `why`, `search_keywords[]`, `typical_employment_types[]`,
  `german_level_typical`, `confidence`
- `src/jobfinder/roles.py`: builds the CV digest sent to the model (skills, education,
  experience — never her address, phone or email), calls the pool, validates, caches
- `jobfinder suggest-roles [--json] [--top N]` — prints a readable table
- Recommendations are stored so Phase 4 can offer them as search presets

### Test-first checklist

- [x] `test_cv_digest_excludes_address_email_and_phone` — privacy, tested not assumed
- [x] `test_cv_digest_includes_skill_groups_and_education_level`
- [x] `test_roles_parsed_from_fake_answer_into_objects`
- [x] `test_role_without_german_title_is_rejected_by_the_validator`
- [x] `test_search_keywords_are_deduplicated_and_lowercased`
- [x] `test_suggestions_are_cached_and_second_run_makes_no_call`
- [x] `test_suggest_roles_cli_renders_a_table_from_stored_suggestions`
- [x] `test_empty_cv_produces_a_helpful_message_not_an_empty_table`

### Done when

- [x] Run against her real CV, the German titles are ones a German recruiter would
      actually use (`Werkstudent Datenanalyse`, not a literal translation)
- [x] Each suggestion carries keywords that go straight into the Phase 4 search
- [x] Second run is instant and costs nothing

**Out of scope:** ranking roles by market demand. Phase 5 will show how many live
postings each keyword actually returns, which is the honest version of that.

---

## Phase 4 — The store, the first source, and `jobs-init.csv`

**Goal:** `jobfinder search` hits the Bundesagentur API for her cities and employment
types, writes rows into SQLite, exports `jobs-init.csv`, and — run twice — adds nothing
the second time.

**Why the BA first:** it is verified, free, keyless, covers everything from kitchen work
to engineering, and returns the minijob and part-time flags her filters depend on. If
only one source ever works, this is the one that has to.

### Deliverables

- `src/jobfinder/sources/base.py`: `RawPosting` dataclass + `SourceAdapter` protocol —
  `search(spec) -> Iterable[RawPosting]`, `fetch_detail(posting) -> RawPosting`
- `src/jobfinder/sources/http.py`: shared client — per-host throttle, on-disk cache,
  retry with backoff, request budget, `Retry-After` handling
- `src/jobfinder/sources/ba.py`: search via `pc/v6/jobs`, details via
  `pc/v4/jobdetails/{base64(referenznummer)}`, `SearchSpec` → query parameters
  (`was`, `wo`, `umkreis`, `angebotsart`, `arbeitszeit`, `page`, `size`), pagination
  until `maxErgebnisse` is reached or the budget runs out
- **Employment types are alternatives, never one stacked filter.** Each type builds
  its own query — a type the API can filter carries only its `arbeitszeit` code,
  `werkstudent` and `internship` carry only their `was` term. Combining them asks
  for a Werkstudent job that is also a minijob and loses her market: 1 result
  against 116 in Ingolstadt, measured live. See
  [the Phase 4 audit](superpowers/plans/2026-08-16-phase-4-audit-and-search-shape.md).
- External-URL fallback: when `stellenangebotsBeschreibung` is empty, fetch `externeURL`
  and extract readable text
- `src/jobfinder/store/`: schema + migrations, `upsert_job`, `touch_last_seen`,
  `export.py` writing `jobs-init.csv` as `utf-8-sig`
- `jobfinder search --dry-run` prints the exact URLs it would call
- A spent request budget pauses a search, it does not end it: `run_search_until_done`
  continues with a fresh budget from the stored cursor, bounded by `max_search_legs`
  and stopped by her Ctrl-C, a refusing host, or a leg that stored nothing

### Test-first checklist

- [x] `test_spec_with_minijob_maps_to_ba_angebotsart_and_arbeitszeit_params`
- [x] `test_spec_with_three_cities_produces_three_queries_with_correct_umkreis`
- [x] `test_ba_fixture_parses_into_raw_postings_with_expected_fields`
- [x] `test_ba_posting_id_is_source_prefixed_referenznummer`
- [x] `test_ba_minijob_flag_is_read_from_istGeringfuegigeBeschaeftigung`
- [x] `test_detail_fetch_base64_encodes_the_reference_number`
- [x] `test_empty_description_triggers_external_url_fallback` (fixture: the real
      `jobboard.compleet.com` shape)
- [x] `test_http_client_waits_between_requests_to_the_same_host` (fake clock)
- [x] `test_http_client_serves_second_identical_request_from_cache`
- [x] `test_request_budget_exhaustion_stops_and_is_recorded_in_runs`
- [x] `test_same_job_twice_leaves_one_row` + `test_only_last_seen_moves`
- [x] `test_dedupe_key_is_stable_across_sources`
- [x] `test_file_starts_with_the_bom` + `test_umlauts_and_ampersand_survive_a_round_trip`
- [x] `test_no_blank_lines_on_windows` (the `newline=""` bug)
- [x] `test_failing_source_records_its_error_and_the_run_returns_what_it_has`
- [x] The search-side resume tests from [§9](#tests-owned-by-phases-4-7-and-9-listed-together-because-the-rule-is-shared):
      per-page saving, cursor resume, interrupted-run marking, atomic export
- [x] `tests/live/test_ba_contract.py` — endpoint answers, `referenznummer` and
      `stellenangebotsTitel` still exist, `X-API-Key` still accepted

### Done when

- [x] A real run for her cities returns live postings and writes `jobs-init.csv`
- [x] Running it again immediately adds **0** new rows and updates `last_seen_at`
- [x] The CSV opens in Excel with correct umlauts and no empty rows
- [x] Killing the run mid-way loses nothing already written

**Out of scope:** LLM anything. This phase is deliberately dumb — collect and store.

---

## Phase 5 — The rest of the API sources

**Goal:** More coverage behind the same interface, and one merged, deduplicated result
set she can trust.

### Deliverables

- `src/jobfinder/sources/arbeitnow.py` — paginated, filtered to her cities client-side
  (the API has no radius parameter), English-friendly roles
- `src/jobfinder/sources/adzuna.py` — enabled only when `ADZUNA_APP_ID` /
  `ADZUNA_APP_KEY` exist; absent keys means the adapter reports "skipped", not an error
- `src/jobfinder/sources/registry.py` — enable/disable, ordering, per-source budgets,
  kill switch, and a run summary: per source `found / new / duplicate / failed`
- Cross-source dedupe on `dedupe_key`, keeping the richest record and recording the
  alternates in `jobs.also_seen_on`

### Test-first checklist

- [x] `test_arbeitnow_fixture_parses_into_raw_postings`
- [x] `test_arbeitnow_results_outside_her_cities_are_filtered_out`
- [x] `test_pagination_stops_at_the_last_page`
- [x] `test_adzuna_adapter_is_skipped_cleanly_without_keys`
- [x] `test_registry_runs_only_enabled_sources`
- [x] `test_a_failing_source_lands_in_its_own_counts_and_the_run_continues`
      (the registry's guarantee, tested through the runner that uses it)
- [x] `test_same_job_from_ba_and_arbeitnow_collapses_to_one_row_with_both_sources`
- [x] `test_richest_record_wins_when_merging` (the one with a description)
- [x] `test_run_summary_counts_match_the_database`
- [x] `tests/live/test_arbeitnow_contract.py`

### Done when

- [x] One `jobfinder search` covers all enabled API sources and prints a per-source summary
- [x] Disabling a source in `config.yaml` visibly changes the summary and nothing breaks
- [x] Duplicate rate across sources is measured and reported, not guessed —
      **zero** between the Bundesagentur and Arbeitnow, measured over 590 live
      postings in München and Ingolstadt. The two sources do not overlap in her
      market; the merge is built for Phase 6's scrapers, which list the same
      corporate ads the Bundesagentur does. Within one source, 5–9 % of postings
      share a dedupe key — separate openings, which is why merging is
      cross-source only. See
      [the Phase 5 plan](superpowers/plans/2026-08-16-phase-5-api-sources.md).

---

## Phase 6 — Scrapers: Kleinanzeigen, StepStone, Indeed, Xing

**Goal:** The commercial boards and the local classifieds, behind the same adapter
interface, built to fail softly.

**Build Kleinanzeigen first.** It is verified working, it is the least defended, and it
is where the jobs she can actually take today are posted — Aushilfe, Reinigungskraft,
Verkauf, Küchenhilfe, all as minijobs. The corporate boards matter for her qualified
roles; this one matters for rent.

**Reality check:** these will break. Not "might" — will, whenever a site redesigns.
The design goal is that a broken scraper costs her one missing source in a run summary,
never a failed run and never a blocked IP. Everything in
[§8 Scraping etiquette](#8-scraping-etiquette-non-negotiable) is enforced here by tests.

### Deliverables

- `src/jobfinder/sources/kleinanzeigen.py` — category `c102` (Jobs) per city, paginated;
  extracts title, price/pay line, location, posted date, description, and the seller's
  contact route (message form, sometimes a phone number in the ad text)
- `src/jobfinder/cities.py` gains a verified **city → Kleinanzeigen location id** map,
  recorded once by hand from their location picker and asserted by a live test — a wrong
  id silently returns jobs in the wrong part of Germany, which is worse than an error
- `src/jobfinder/sources/stepstone.py`, `indeed.py`, `xing.py` — search page → listing
  URLs → listing page → `RawPosting`
- Extraction prefers **structured data** (`JSON-LD` `JobPosting` blocks, which all three
  emit for SEO) and falls back to CSS selectors — selectors change far more often than
  schema.org markup
- `scripts/record_fixture.py --html` saves real pages into `tests/fixtures/<source>/`
- Per-source health in `source_state`: consecutive failures, auto-disable after 3,
  surfaced in the run summary as "StepStone: disabled after 3 failures — re-record
  fixtures"
- A single `jobfinder sources check` command that runs each scraper against one known
  query and reports which ones still parse

### Test-first checklist

- [x] `test_kleinanzeigen_fixture_yields_25_listing_urls_from_one_page`
- [x] `test_listing_parses_title_location_date_and_body`
- [x] `test_minijob_wording_sets_the_minijob_flag` + `test_detail_wording_sets_the_flags`
      ("Minijob", "450 €", "520 €", "Aushilfe", "geringfügig")
- [x] `test_gesuche_ads_are_excluded` — people *seeking* work, not offering it
- [x] `test_a_city_without_a_location_id_is_skipped_loudly`
- [x] `tests/live/test_kleinanzeigen_location_ids.py` — each mapped id still returns ads
      whose **postcodes** match the intended city (big cities label ads by borough)
- [ ] `test_stepstone_fixture_yields_expected_listing_urls` — URL parsing is
      tested (`test_listing_urls_parse_with_their_ids`) but against inline HTML:
      StepStone refuses this network, so no page could be recorded
- [ ] `test_stepstone_listing_page_parses_title_company_city_description` — the
      shared JSON-LD path is proven (`test_stepstone_detail_uses_the_shared_jsonld_path`)
      but over a recorded **Xing** page, not a StepStone one
- [x] `test_jsonld_extraction_is_preferred_over_css_selectors`
- [x] `test_missing_jsonld_falls_back_to_selectors_on_a_real_saved_page`
- [ ] `test_unparseable_page_records_a_failure_and_returns_nothing` (never a crash)
      — "returns nothing" holds (`test_a_junk_200_page_yields_no_postings_and_no_crash`,
      both boards); "records a failure" waits for the source-health work below
- [x] `test_three_consecutive_failures_disable_the_source`
- [x] `test_disabled_source_is_skipped_on_the_next_run_until_reset`
- [x] `test_scraper_sources_are_built_with_the_scraper_delay` +
      `test_http_client_waits_between_requests_to_the_same_host` (fake clock)
- [x] `test_concurrent_requests_to_one_host_are_still_spaced`
- [x] `test_two_clients_on_the_same_host_wait_for_each_other`
- [x] `test_two_different_hosts_are_fetched_at_the_same_time` (§8 rule 2 — the
      reason this phase is not four times slower than Phase 5)
- [x] `test_retry_after_header_is_honoured` + `test_exhausted_retries_raise_source_unavailable`
- [x] `test_a_login_walled_list_page_is_detected_and_skipped_not_retried` (Kleinanzeigen and Xing)
- [x] `test_every_request_carries_the_identifying_user_agent`
- [x] `tests/live/test_scrapers_smoke.py` — one query per site, marked `live`,
      asserts ≥1 parseable result (a blocked board skips; answering-but-unparseable fails)

### Done when

- [ ] Each scraper returns real listings for "Werkstudent München" and "Aushilfe Küche
      Ingolstadt" — **partly, and honestly**: run live 2026-08-16, Xing returned 20 and
      19; Kleinanzeigen returned 3 for Aushilfe Küche Ingolstadt and **0** for
      Werkstudent München, whose jobs browse carries almost no student work that day;
      StepStone and Indeed are blocked and cannot answer at all
- [x] Kleinanzeigen returns ads for Neuburg, Ingolstadt and Munich with the right
      locations, and the minijob flag is right on a hand-checked sample —
      `tests/live/test_kleinanzeigen_location_ids.py` verified **all thirteen** ids
      against live postcodes, and the stored Kleinanzeigen rows were right on 7 of 7
      (the sample it produced), including two the title alone would have missed
- [x] Turning all three off leaves the app fully working on API sources — run with
      `enabled_sources: [ba, arbeitnow, adzuna]`: 320 jobs, three skip lines, nothing broke
- [x] A deliberately corrupted fixture produces a clean "source failed" line, no traceback
      — `test_a_junk_200_page_yields_no_postings_and_no_crash` (both boards),
      `test_one_source_failing_costs_only_its_own_results`, and
      `test_an_unexpected_break_is_reported_not_raised` for `sources check`
- [x] A full run makes no more requests than the budget allows, at human pace —
      `test_request_budget_is_enforced_on_retries_too` plus the per-host gap in
      `test_http_client_waits_between_requests_to_the_same_host`; live runs held 1.50 s
      per API request and 3 s per scraped one

**Phase 6 complete (v0.4.0).** Kleinanzeigen, Xing and Adzuna ship enabled; a real
run returns 346 jobs across five sources in 11 seconds, with the sources searched in
parallel, one connection each. StepStone and Indeed were re-probed on 2026-08-16 and
still refuse this machine — both ship off with a skip line that says so, and neither
has a sanctioned API to fall back on. Adzuna reaches part of that inventory instead:
84 % of its rows were jobs the Bundesagentur search never returned. Three gaps are
recorded in
[the phase plan](superpowers/plans/2026-08-16-phase-6-scrapers.md#known-gaps-this-phase-ships-with).

**Out of scope:** headless browsers. If a site requires JavaScript execution, that
adapter is dropped rather than escalated — the cost/benefit against the BA API is poor.

---

## Phase 7 — Enrichment: German ad in, English answer out

**Goal:** Every stored job gets the six things she actually needs to know, in English,
without opening the original ad: what the work is, what skills it wants, **how much
German it needs**, what type of contract it is, how well it fits her, and how to apply.

**This is the heart of the product.** Everything before it is plumbing.

### Deliverables

- `src/jobfinder/llm/prompts/enrich.v1.md` — one German posting in, the
  `jobs-enriched.csv` field set out (see [§5](#5-data-contracts))
- `src/jobfinder/enrich/runner.py` — `llmpool.run_batch` over unenriched jobs,
  `workers` from settings, `on_result` persisting each answer the moment it lands
- Skip logic: already enriched at this `prompt_version` **and** unchanged
  `content_hash` → not sent
- Each validated answer is written to SQLite and appended to `jobs-enriched.csv`
  immediately, before the next job is sent — she can open the CSV while the run is
  still going, and an interrupted run leaves a complete, readable file behind
- `fit_score` computed against her CV digest in the same call, with `fit_reasons` and
  `missing_for_fit` so a 40 % is explained rather than just discouraging
- Application route extraction: email, portal URL, or phone — the difference between
  "she can apply tonight" and "she needs to make a German phone call"
- `jobfinder enrich [--limit N] [--force]`, exports `jobs-enriched.csv` when done
- **Enrichment runs alongside a search, not after it** (see
  [§9](#enrichment-does-not-wait-for-the-search-to-finish)): the store is the
  queue, `jobfinder search --enrich` starts both, and either command alone
  still behaves exactly as it does today

### Test-first checklist

- [x] `test_enrichment_prompt_includes_the_full_description_and_her_cv_digest`
- [x] `test_fake_answer_maps_onto_every_enriched_csv_column`
- [x] `test_a_german_level_outside_the_enum_is_rejected`
- [x] `test_a_german_level_without_evidence_is_rejected` — no unsupported guesses
- [x] `test_an_answer_written_in_german_is_rejected` (summary must be English)
- [x] `test_pipe_separated_list_fields_survive_a_csv_round_trip`
- [x] `test_already_enriched_job_is_not_sent_again`
- [x] `test_changed_description_triggers_re_enrichment`
- [x] `test_new_prompt_version_triggers_re_enrichment_and_keeps_the_old_row`
- [x] `test_batch_persists_each_result_as_it_lands` (kill after 3 of 10 → 3 saved)
- [x] `test_one_failing_item_does_not_end_the_batch`
- [x] `test_pool_exhausted_stops_cleanly_with_a_resumable_message`
- [x] `test_enrich_limit_respects_the_llm_budget`
- [x] `test_enrichment_started_during_a_search_enriches_what_the_search_stored`
- [x] `test_search_alone_and_enrich_alone_are_unchanged_by_the_combined_command`
- [x] The enrichment-side resume tests from [§9](#tests-owned-by-phases-4-7-and-9-listed-together-because-the-rule-is-shared):
      quota exhaustion keeps completed work, resume skips it, no half-written answers
- [x] `tests/live/test_enrich_one_real_posting.py` (marked `live_llm`)

### Done when

- [x] 20 real Bavarian postings enriched; she reads five and confirms the English
      summaries match the ads
- [x] `german_level` is right on a hand-checked sample of ten, including at least
      three kitchen/retail ads where the requirement is often implicit
- [x] Interrupting the batch and re-running resumes without re-spending calls
- [x] A full re-run with no new jobs makes **zero** provider calls

**Out of scope:** writing her applications. Tailored CVs and cover letters are backlog
(§ [Later](#later--explicitly-not-now)); the `/job-scout` command already covers the
manual version.

---

## Phase 8 — The app she actually uses

**Goal:** She opens a browser, sees her jobs, filters them, reads one page per job, and
marks what she has applied to. This is the milestone that makes the project real.

### Deliverables

- `src/jobfinder/web/app.py` — FastAPI, binds `127.0.0.1` only, no auth (single user,
  local)
- **List page:** table/cards with title, company, city, distance, employment type,
  German level, fit score, status. Filters: city, employment type, max German level,
  min fit, source, status. Sort by fit, date, or distance.
- **Job page** (one standard template): English summary, duties, required and
  nice-to-have skills, German level with the evidence phrase, contract type and hours,
  fit score with reasons and gaps, how to apply, deadline, buttons — *Applied*,
  *Interested*, *Not for me*, *Delete* — a notes box, a link to the original ad, and
  the German original in a collapsible block
- **Status actions** write to `status` and are visible immediately; deleted jobs are
  soft-deleted and never re-appear in a later search
- **Live progress surface** — the whole of [§10](#10-ux-principles) is built here:
  a `/progress` endpoint reading the `runs` journal, a determinate bar, per-source
  lines in plain English, live found/new counters, elapsed and estimated time, a
  Cancel button, and an interrupted-run banner with **Resume**. Progress comes from
  the database, so reloading mid-run shows the same state.
- Skeleton, empty and error states for every page, written at the same time as the
  success state
- `jobfinder serve` starts it and opens the browser

### Test-first checklist

- [x] `test_index_lists_only_non_deleted_jobs`
- [x] `test_filter_by_city_returns_only_that_city`
- [x] `test_filter_by_max_german_level_excludes_c1_when_she_selects_b1`
- [x] `test_filter_combination_city_and_type_and_fit`
- [x] `test_sort_by_fit_score_descending`
- [x] `test_job_page_renders_every_enriched_field_present_in_the_row`
- [x] `test_job_page_renders_when_enrichment_is_missing` — never a 500 on a fresh job
- [x] `test_mark_applied_persists_and_sets_applied_on_date`
- [x] `test_delete_soft_deletes_and_survives_a_new_search_run`
- [x] `test_notes_are_saved_and_shown_after_reload`
- [x] `test_german_original_is_present_but_collapsed`
- [x] `test_server_binds_localhost_only` — and
      `test_serve_opens_the_browser_once_against_a_server_that_answers`, which
      drives the real serve function against a real port after the first
      version of it could not start at all
- [x] `test_playwright_smoke_filter_open_job_mark_applied` (one end-to-end path)
- [x] Plus every test in [§10](#tests-for-the-above-owned-by-phase-8)
- [x] `test_a_section_the_ad_says_nothing_about_says_so` and
      `test_the_empty_state_only_names_filters_she_actually_set` — two empty
      states found by using the app on her real store, not by reading the code

### Done when

- [ ] She uses it for one real search session without asking a question — **not
      yet hers to confirm.** Driven end to end against her real store instead:
      browse, filter, open, mark, search, cancel, all without a dead end. Her
      own session is the one box only she can tick.
- [x] During a search she can tell, at every moment, that it is working and
      roughly how far along it is — and a mid-run browser reload proves it.
      Measured live on 2026-08-16: `Searching — 104 found, 15 new`, elapsed and
      a jobs-per-minute rate, one line per source (`Bundesagentur — 50 found,
      1 new · searching`, `Arbeitnow — 0 found, 0 new · done`), and a reload
      mid-run came back with the run still going and its counts current
- [x] Every action survives a restart of the app — a job marked applied with a
      note came back applied, dated, and noted after `jobfinder serve` was
      stopped and started again
- [x] The list stays responsive at 1 000 jobs — timed against a 1 348-job copy
      of her store: 413 ms for the whole page, 103–125 ms per filtered or
      sorted row page, 57 ms for the narrowest filter
- [x] Nothing on screen is in German except the original ad and job titles —
      confirmed on the job page, where the German original sits collapsed under
      its own heading and every field around it reads in English
- [x] Cancel stops a run and keeps what it stored — live: 282 found, 68 new
      kept, run row `interrupted`, and the banner offered Resume with those
      counts

**Phase 8 complete.** `jobfinder serve` opens the app on 127.0.0.1; her 674-job
store browses, filters, sorts and opens one page per job, and her decisions
persist across restarts. Searches start, narrate and cancel from the browser.
Using it on real data — rather than reading the tests — is what turned up all
four defects this phase closed: `serve` could not start at all, two sections
rendered empty headings, the empty state offered filters she had not set, and
the run journal froze its own clock. Each is now held by a test.

**Out of scope:** editing job data by hand, bulk actions, charts. If she wants a
spreadsheet view, `jobs-enriched.csv` is right there.

---

## Phase 9 — General work: a call-list, not a job board

**Goal:** For the "I just need work" mode — a list of restaurants, cafés, bakeries and
hotel kitchens in her cities, with a phone number or email, ranked so the ones where
she can work in the back and speak little German come first.

**Pairs with Kleinanzeigen.** Phase 6 finds the local places that *did* post something;
this phase finds the far larger number that never post at all. Together they are her
whole realistic minijob market.

**Why this is separate:** these places do not post jobs. They hire when someone walks
in or calls. The product here is a contact list and the courage to use it, not a
posting feed. Verified: Neuburg alone has 60 such places, 28 with contact details.

### Deliverables

- `src/jobfinder/sources/overpass.py` — Overpass query per city for
  `amenity=restaurant|cafe|fast_food|bar|hotel`, `shop=bakery|butcher|supermarket`;
  extracts name, kind, address, `phone`/`contact:phone`, `email`/`contact:email`,
  `website`
- `back_of_house_score`: heuristic favouring kitchens, bakeries and hotels (dishwashing,
  prep, cleaning — little customer contact) over counter-service roles; cuisine tags
  matching her languages are a bonus, not a requirement
- `contacts.csv` export and a **Contacts page** in the web app, with the same
  status buttons: *Called*, *Emailed*, *No*, plus an outcome note
- LLM-generated, per-place: a five-line **German phone script** with an English gloss
  under each line ("Guten Tag, ich suche Arbeit…" / "Hello, I'm looking for work…"),
  and a short **German email** she can send, both mentioning that she is a student
  looking for a minijob or part-time work
- Contacts with a website but no email get their imprint page fetched once (German law
  requires contact details there) to recover an address

### Test-first checklist

- [x] `test_the_fixture_parses_places_with_and_without_contact_details`
- [x] `test_a_place_with_no_contact_route_at_all_is_excluded`
- [x] `test_a_contact_id_is_stable_across_runs` (OSM type + id)
- [x] `test_a_bakery_and_a_hotel_outrank_a_bar`
- [x] `test_a_spaced_german_number_becomes_e164` + `test_two_spellings_of_one_number_agree`
- [x] `test_a_place_seen_in_two_tag_queries_appears_once`
- [x] `test_an_email_is_extracted_from_a_saved_imprint_page`
- [x] `test_the_lookup_is_skipped_when_an_email_already_exists`
- [x] `test_a_script_is_five_lines_of_german_each_with_an_english_gloss` (FakePool)
- [x] `test_a_rendered_email_names_the_place_and_her_availability`
- [x] `test_marking_it_survives_a_restart_of_the_app` +
      `test_a_marked_place_leaves_the_queue_but_can_be_found_again`
- [x] `tests/live/test_overpass_contract.py` — Neuburg still returns places with contacts
      (it **skips** rather than fails when Overpass is rate-limiting this machine,
      which it does; see the phase plan)

### Done when

- [x] ≥ 50 contactable places across Neuburg, Ingolstadt and Munich, ranked —
      **357 places, 255 reachable**, five times the target, from Neuburg (53/36)
      and Ingolstadt (304/219). Ranked bakeries and hotels first, bars last.
      **Munich is not in that number**: 6 km over nine tags never came back, and
      by then Overpass was refusing this machine altogether (below). Probed
      afterwards, its data reads correctly and its volume is the problem — the
      measurements are in
      [the phase plan](superpowers/plans/2026-08-17-phase-9-call-list.md#munich-probed-after-the-fact).
- [x] She can print or open the list and start calling, script in hand —
      `contacts.csv` holds all 357 rows and matches the store field for field,
      and 352 of them carry a five-line German script with an English gloss under
      each line
- [x] Marking one "Called — come by Tuesday" persists and moves it out of the
      queue — done for real on `Backhaus Hackner`: gone from the working list,
      still there under *Show every place* with the note and the date, and in the
      CSV

**Phase 9 complete.** `jobfinder contacts` and the **Call** page in the browser
both build the list; the Contacts page pages twenty at a time, offers `tel:` and
`mailto:` links, and takes *Called / Emailed / Not for me* with a note. Details
and the four defects that only appeared on real data are in
[the phase plan](superpowers/plans/2026-08-17-phase-9-call-list.md).

**Three corrections to what this section asked for**, all measured rather than
argued:

- **`amenity=hotel` returns nothing — hotels are `tourism=hotel`.** The tag list
  above would have missed every hotel kitchen, which is one of the best fits in
  the list for someone with little German. `amenity=pub` was worth adding too.
- **The phone script is per *kind* of place, not per place.** Per-place would
  have spent 352 free-tier calls to produce texts differing by a proper noun; per
  kind is 8, and the name and town are substituted on the way into the store.
- **Overpass rate-limits this machine after a few hundred queries** — every
  endpoint refusing TCP at once while the rest of the internet answered in under
  a second. The gap between requests is now 10 s, a tag is tried on two hosts
  rather than five, and a refusal says "worth trying later" instead of
  `URLError`.

**Out of scope:** sending the emails automatically. She reviews and sends them herself,
from her own address.

---

## Phase 10 — Handover: one file she double-clicks

**Goal:** It runs on her laptop, started by her, without Python, a terminal, or you.

**Why it is a phase and not an afterthought:** a tool that only runs on the developer's
machine has not been delivered.

### Deliverables

- PyInstaller build → `JobFinder.exe`: starts the server on a free port, opens the
  browser, and shows a small console window with a plain-English status line
- **First-run wizard** in the browser: paste at least one free LLM API key (with the
  signup links `llmpool doctor` already prints), pick cities, pick employment types,
  point at `pool.yaml` — no file editing required after that
- A **Search** button in the UI, so a normal session is: open app → Search → wait →
  read. The CLI stays for you.
- Errors she might actually hit are translated: no keys, no internet, all sources
  failed, quota spent — each with one clear next step
- `data/` backup on every run (last 5 kept) and a one-click "export everything to CSV"
- `docs/HER_README.md` — one page, screenshots, in English: how to start it, what the
  buttons do, what to do when it says something is wrong
- Update path: a script that pulls a new build and keeps `data/` intact

### Test-first checklist

- [x] `test_the_next_port_is_chosen_when_the_preferred_one_is_busy`
- [x] `test_first_run_wizard_appears_when_no_config_exists`
- [x] `test_wizard_writes_env_and_config_and_never_logs_the_key`
- [x] `test_wizard_is_skipped_on_second_start`
- [x] `test_missing_api_key_renders_a_sentence_and_a_link_not_a_traceback`
- [x] `test_no_internet_produces_a_readable_page_not_a_traceback`
- [x] `test_the_search_button_starts_a_run_the_progress_panel_narrates` (Phase 8)
- [x] `test_backup_rotation_keeps_five_and_deletes_the_sixth`
- [x] `test_data_dir_resolves_next_to_the_exe_when_frozen` (PyInstaller `sys.frozen`)
- [ ] `test_built_exe_starts_and_answers_healthcheck` (build smoke, marked `live`)

### Done when

- [ ] She installs nothing, double-clicks once, and completes a search on her own laptop
- [ ] Her data survives an app update
- [ ] Deleting `data/` and starting again works and re-runs the wizard

---

## Cross-cutting concerns

Checked at the end of every phase, not saved for the end of the project.

| Concern | Rule | Where it is tested |
|---|---|---|
| **Her privacy** | Name, address, phone and email never leave the machine except inside a job application she sends herself. The CV digest sent to LLM providers is skills and education only. | Phase 3 |
| **Free-tier budget** | Every LLM call is cached and skippable; a run announces how many calls it will make before making them. | Phases 2, 7 |
| **Resumability** | Any long run can be killed at any moment and resumed without loss or duplicate spend — the full contract is [§9](#9-incremental-saving-and-resume-runtime-data). | Phases 4, 7, 9 |
| **Never looks frozen** | Every wait over a second is narrated with counts and progress, read from the database so it survives a reload — [§10](#10-ux-principles). | Phase 8 |
| **Windows reality** | `pathlib` everywhere, `utf-8-sig` CSVs, `newline=""`, no `:` in filenames, paths with spaces. | Phase 4 onward |
| **German text** | Umlauts and `ß` survive fetch → store → CSV → browser. One fixture with `Bäckerei Müller & Söhne` rides along through every layer. | Phases 4, 8 |
| **One dead source** | Never fails a run. Ever. | Phases 5, 6 |
| **Honest empty states** | "No jobs found" says which sources ran, what was searched, and what to loosen. Silence is a bug. | Phases 5, 8 |
| **Stale postings** | `last_seen_at` is shown; jobs not seen in 14 days are visually greyed out. She should not apply to a dead ad. | Phase 8 |

---

## Risks

| Risk | Likelihood | What we do about it |
|---|---|---|
| BA API changes or starts requiring auth | Medium | Live contract test catches it early; it is one adapter, and Arbeitnow + scrapers keep the app alive |
| Scrapers break | **High** | Expected. Auto-disable, run summary tells her, fixtures get re-recorded |
| An IP block on a commercial site | Medium | Throttle, cache and budget in §8; a block hits one source, not the app |
| Free LLM quota exhausted mid-search | Medium | `llmpool` handles pacing and failover; enrichment is resumable and cached; she can add a second key in 30 seconds |
| LLM invents a German level or a skill | Medium | Evidence field is mandatory and validated; she sees the original ad on the same page |
| Too many results, she cannot act | Medium | Fit score, filters, and "not for me" as a first-class action |
| Too few results in Neuburg | **High** | Radius per city, Munich and Ingolstadt included by default, Kleinanzeigen for local minijobs, and Phase 9's cold-contact list exists precisely for this |
| She thinks the app has frozen and force-quits it | Medium | [§10](#10-ux-principles) progress rules — and thanks to [§9](#9-incremental-saving-and-resume-runtime-data) a force-quit costs her nothing anyway |
| Kleinanzeigen location ids drift or the layout changes | Medium | Live test asserts each mapped id still returns the right city; JSON-LD first, selectors second |
| Building all ten phases takes too long | Medium | M4 is the shipping line. Phases 6, 9, 10 are additive |

---

## Wanted next — asked for after using the app

Three gaps she named while clicking through the finished Phase 8, on
2026-08-16. **All three shipped on 2026-08-17** — the plan, the measurements and
the four defects that only appeared on real data are in
[the task plan](superpowers/plans/2026-08-17-wanted-next.md).

- **Explain, from the browser.** `/enrich` explains stored jobs in English on its
  own thread, so it runs beside a search rather than instead of one, and Cancel
  keeps every answer already saved. It says what it will spend before spending
  it — `837 of your jobs have no English answer yet`, one free-tier call each,
  bounded to 50 by default. Verified live: a 10-job pass took 2 m 24 s, and a
  cancelled 20-job pass kept 16 answers with the CSV and the database agreeing
  job for job.
- **Her CV, from the browser.** Settings offers the template as a download,
  takes the filled file back, and validates it before anything on disk changes —
  a bad paste costs her the upload, never the CV she had. It summarises what it
  found (languages, skill groups, years) without putting her address, phone or
  email on screen, and role suggestions can be asked for from the same page,
  each German title linking into the search form as a keyword.
- **A posting-date filter.** Any time / last 3 days / last week / last month.
  Schema **v7** adds `published_on`, one comparable `YYYY-MM-DD` derived by one
  function, and backfills every row already stored — `published_at` keeps
  whatever the source said. On her store the filter and SQL agree exactly: 859 /
  68 / 137 / 385.

What follows is what was written before any of it was built, kept because each
section records what was measured first and why the shape was chosen.

### An Enrich button, to run and resume enrichment from the browser

**Why.** Enrichment is the heart of the product and today it only runs from a
terminal, so **20 of her 859 jobs** carry an English answer. Everything the
list and job pages promise — the summary, the German level, the fit score — is
blank for the other 839, and she has no way to change that from the app.

**What already exists.** Nearly all of it. The store is the queue, so
enrichment needs no handover from a search. `enrich/companion.py` already
journals a `runs` row of kind `enrich` and has `cancel()`. `web/runs.py`
`RunManager` already owns one daemon thread per run, and `_progress.html`
already renders `Explaining jobs in English as they arrive — N explained so
far`. The skip logic (§5's re-run rule) already means pressing it twice costs
nothing.

**What is actually new.** A `POST /run/enrich`, its own progress line with a
Cancel, and — the part that needs thought — telling her **what it will spend
before it spends it**. A full pass over 839 unenriched jobs is 839 real
free-tier calls; the cross-cutting rule says a run announces its cost first,
and `--limit` exists on the CLI precisely because a full pass is expensive.
A quota spent mid-run already stops cleanly and resumes, so Resume is the same
button.

### Somewhere to put her CV, so the rest of the app comes alive

**Why.** `pool.yaml` is the input to her profile, the role suggestions, and
every `fit_score`. Today it can only be edited as a file next to the source
code, which is not something to ask of her — and until it exists,
`jobfinder suggest-roles` cannot run and the fit column has nothing to say.

**Shape.** The Settings page offers `pool.template.yaml` as a download and
takes the filled file back as an upload, validated by the existing
`load_profile` — Phase 1 already answers every failure with one sentence
naming the field and the line, so the error state is written. With a CV
present, role suggestions can be requested from the browser and their keywords
handed to the search form.

**Where it belongs.** Phase 10's first-run wizard already promises "point at
`pool.yaml`", so this is that deliverable, brought forward if the fit scores
are wanted sooner. **Privacy is the constraint, not a footnote:** `pool.yaml`
holds her name, address and email, stays gitignored, and never leaves the
machine — only the skills-and-education digest goes to a provider (§
Cross-cutting concerns, tested in Phase 3).

### A posting-date filter

**Why.** She can see how old an ad is on its page but cannot ask for "posted in
the last week", and an old posting is a wasted application. This is a
different question from the 14-day greying, which says whether *her searches*
still see the ad listed, not when it was written.

**Measured first, because it decides the implementation.** `published_at` is
present on **859 of 859** stored jobs — but in two shapes: the Bundesagentur,
Kleinanzeigen and Xing store plain dates (`2022-12-15`), while Arbeitnow and
Adzuna store full ISO timestamps (`2026-08-16T12:37:59Z`). A string comparison
across both is wrong at the boundary, so the filter needs a normalised
comparable value — and the honest place to fix it is the adapters, on the way
in, rather than every query afterwards. The stored range starts in **2022**,
so ads far older than they look are already in her store.

**Shape.** A "posted within" filter on the list (any / 3 days / week / month),
alongside the existing ones. The search side is a second question: the
Bundesagentur and Adzuna both take a date parameter, so a date bound could
also stop old postings being fetched at all.

---

## Later — explicitly not now

- Tailored CV and cover letter generation per job (the `pool.template.yaml` `tags`
  and `targets` design already anticipates this; `/job-scout` covers it manually today)
- Application deadline reminders and a follow-up nudge after 10 days
- Interview prep notes per company
- Visa/work-hour rules for student residence permits surfaced per job type
- Telegram notifications for new high-fit jobs (a `telegram-serverless` skill exists)
- A second user. The moment there are two, storage, secrets and packaging all change.

---

## How each phase runs

1. `git checkout -b feat/phase-N-<name>`
2. Write the detailed task plan with the `writing-plans` skill into
   `docs/superpowers/plans/YYYY-MM-DD-phase-N-<name>.md`, one bite-sized step per task
3. Work the plan test-first: red → watch it fail → green → refactor → tick the box in
   this file → commit → **push**, one task at a time (see
   [commit rhythm](#commit-rhythm--one-task-one-commit-pushed))
4. Atomic commits, `type: what and why`, pushed as they land — never batched
5. Close the phase against its Definition of Done **and** the shared one in
   [§7](#7-tdd-working-agreement); anything unchecked either gets done or gets written
   into this file as a known gap
6. Update this master plan if a contract changed, then merge

**Phase quick reference**

| # | Phase | Depends on | Milestone |
|---|---|---|---|
| 0 | Skeleton and test harness | — | M1 |
| 1 | CV and preferences | 0 | M1 |
| 2 | LLM layer | 0 | M2 |
| 3 | Role recommendations | 1, 2 | M2 |
| 4 | Store + Bundesagentur + `jobs-init.csv` | 1 | M3 |
| 5 | Remaining API sources | 4 | M3 |
| 6 | Scrapers | 4 | M5 |
| 7 | Enrichment → `jobs-enriched.csv` | 2, 4 | M3 |
| 8 | Web app | 7 | **M4 — ship line** |
| 9 | General work contacts | 4, 8 | M5 |
| 10 | Packaging and handover | 8 | M6 |
