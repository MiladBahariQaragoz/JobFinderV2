---
title: JobFinderV2 Master Plan
date: 2026-08-15
type: master-plan
status: approved, not started
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
| **M3 — First real shortlist** | 4–5, 7 | Run a search and get a CSV of live Bavarian jobs, each explained in English |
| **M4 — The actual product** | 8 | Browse, filter, read, and mark jobs applied/deleted in a real UI |
| **M5 — Wider net** | 6, 9 | Get StepStone/Indeed/Xing results, plus a call-list of local kitchens and bakeries |
| **M6 — Handover** | 10 | Double-click one file on her own laptop and use it without help |

**If time gets short, ship M4 and stop.** Phases 6 and 9 are additive; nothing in
8 or 10 depends on them.

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
| `source` | Short code per adapter | `BA`, `AN`, `AZ`, `SS`, `ID`, `XI` |
| `dedupe_key` | `sha1(normalized_title + normalized_company + plz)` — catches the same job listed on three sites | `9f2c…` |
| `content_hash` | `sha1(description)` — changes only when the ad text changes, drives re-enrichment | `41ab…` |

**The re-run rule:** a search that finds a `job_id` already in the database updates
`last_seen_at` and nothing else. Enrichment is skipped unless `content_hash` changed
or the prompt version changed. This is what stops the app from spending her free LLM
quota on the same 200 jobs every morning.

### SQLite tables

| Table | Holds | Notes |
|---|---|---|
| `jobs` | one row per posting, raw facts from the source | never overwritten by the LLM |
| `job_descriptions` | full text, kept out of `jobs` so exports stay small | German original |
| `enrichment` | LLM-derived fields, keyed by `job_id` + `prompt_version` | re-enrichment appends, never destroys |
| `status` | her decisions: `new`, `interested`, `applied`, `rejected`, `deleted` + notes + dates | the only table she writes to |
| `contacts` | general-work places from Overpass: name, type, city, phone, email, website | separate flow, separate page |
| `runs` | one row per search run: spec, sources hit, counts, errors, duration | debuggability when something returns nothing |
| `source_state` | per-source cursors, last success, consecutive failures, cooldown | mirrors how llmpool remembers providers |

### `jobs-init.csv` (exported after every search)

`job_id, source, source_id, dedupe_key, title, company, city, plz, lat, lon,
employment_type_raw, is_minijob, is_parttime, is_fulltime, is_internship,
is_werkstudent, homeoffice, published_at, apply_url, source_url, has_description,
content_hash, first_seen_at, last_seen_at, status`

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
| **Adzuna** | ⚙️ optional | `api.adzuna.com/v1/api/jobs/de/search/{page}` with free `app_id`/`app_key` | Aggregates listings that include StepStone-sourced ads. Add only if she registers a key; adapter must no-op cleanly when the key is absent. |
| **OpenStreetMap Overpass** | ✅ verified `200` | `POST overpass-api.de/api/interpreter` | For general work. Neuburg an der Donau alone returned **60** restaurants/cafés/bakeries, **28 with a phone or email**. This is the cold-contact engine. |
| **StepStone** | 🔨 scraper | Search results page → listing pages | `robots.txt` disallows much of the site and forbids non-conforming robots. Included by explicit decision; treat as fragile. |
| **Indeed** | 🔨 scraper | Search results page → listing pages | Aggressive bot detection; expect it to be the first to break. Kill switch matters here. |
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

1. **One request at a time per host**, minimum 3 s apart with ±1 s jitter. No
   parallel fetching of a scraped site, ever.
2. **Cache every fetched page for 24 h** in `data/http-cache/`. A re-run must not
   re-fetch. Tests assert the second call hits the cache.
3. **A real identifying User-Agent** with a contact address. No pretending to be
   Chrome-on-someone-else's-machine.
4. **Honor `Retry-After` and back off exponentially** on 429/503, then trip the
   source's kill switch after 3 consecutive failures and move on. One dead source
   never fails the run.
5. **Public pages only.** No login, no session cookies, no CAPTCHA-solving service,
   no proxy rotation. If a page needs an account, the adapter skips it.
6. **Per-source kill switch** in config; `sources.stepstone.enabled: false` is a
   one-line fix when a site changes and she needs results today.
7. **Total request budget per run** (default 200) so a bug cannot turn into a flood.

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

- [ ] `test_killing_a_search_after_two_pages_keeps_both_pages_on_disk`
- [ ] `test_resumed_search_starts_at_the_stored_cursor_not_page_one`
- [ ] `test_network_error_mid_run_marks_run_interrupted_with_counts`
- [ ] `test_pool_exhausted_mid_batch_keeps_every_completed_enrichment`
- [ ] `test_resume_after_quota_exhaustion_skips_already_enriched_jobs`
- [ ] `test_invalid_llm_answer_leaves_the_job_unenriched_not_half_written`
- [ ] `test_each_enrichment_is_appended_to_the_csv_before_the_next_one_starts`
- [ ] `test_csv_is_readable_mid_run_and_holds_every_finished_job`
- [ ] `test_export_crash_leaves_previous_csv_intact` (write to tmp, fail, assert old file)
- [ ] `test_stale_running_run_is_marked_interrupted_on_next_start`
- [ ] `test_second_full_run_with_no_changes_makes_zero_llm_calls_and_zero_new_rows`
- [ ] `test_wal_mode_is_enabled_on_every_connection`

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

- [ ] `test_search_progress_is_persisted_and_survives_a_page_reload`
- [ ] `test_progress_endpoint_reports_current_source_and_counts`
- [ ] `test_cancel_stops_the_run_and_keeps_completed_work`
- [ ] `test_every_list_page_renders_a_skeleton_state`
- [ ] `test_empty_result_page_names_the_filters_that_were_applied`
- [ ] `test_missing_api_key_renders_a_sentence_and_a_link_not_a_traceback`
- [ ] `test_interrupted_run_banner_offers_resume_with_the_right_counts`
- [ ] `test_no_emoji_in_any_template` (a grep test — cheap, and it holds the line)
- [ ] `test_numbers_render_in_the_monospace_class`

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
- [x] `test_settings_reads_secrets_from_env_not_config` — a key in `config.yaml` is
      rejected outright, `.env` is loaded, and an already-set variable wins over it
- [x] `test_no_network_fixture_blocks_outbound_socket` — proves the guard actually bites:
      `create_connection`, raw `connect`, the host named in the error, localhost still allowed
- [x] `test_live_marker_is_registered` — both markers registered, live tests deselected
      by default, `pytest -m live` selects them, and the live lane really can reach out
- [x] `test_record_fixture_writes_pretty_json_to_expected_path` — plus verbatim HTML,
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

- [ ] `test_validator_accepts_a_well_formed_answer`
- [ ] `test_validator_rejects_missing_required_key_with_named_reason`
- [ ] `test_validator_rejects_prose_masquerading_as_json`
- [ ] `test_validator_rejects_out_of_range_enum_value` (e.g. `german_level: "fluent"`)
- [ ] `test_cache_returns_stored_answer_without_calling_the_pool` — assert the fake
      recorded zero calls
- [ ] `test_cache_misses_when_prompt_version_changes`
- [ ] `test_cache_misses_when_content_hash_changes`
- [ ] `test_pool_exhausted_is_surfaced_as_a_handled_error_not_a_crash`
- [ ] `test_build_pool_raises_a_readable_error_when_no_provider_keys_exist`
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

- [ ] `test_cv_digest_excludes_address_email_and_phone` — privacy, tested not assumed
- [ ] `test_cv_digest_includes_skill_groups_and_education_level`
- [ ] `test_roles_parsed_from_fake_answer_into_objects`
- [ ] `test_role_without_german_title_is_rejected_by_the_validator`
- [ ] `test_search_keywords_are_deduplicated_and_lowercased`
- [ ] `test_suggestions_are_cached_and_second_run_makes_no_call`
- [ ] `test_suggest_roles_cli_renders_a_table_from_stored_suggestions`
- [ ] `test_empty_cv_produces_a_helpful_message_not_an_empty_table`

### Done when

- [ ] Run against her real CV, the German titles are ones a German recruiter would
      actually use (`Werkstudent Datenanalyse`, not a literal translation)
- [ ] Each suggestion carries keywords that go straight into the Phase 4 search
- [ ] Second run is instant and costs nothing

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
- External-URL fallback: when `stellenangebotsBeschreibung` is empty, fetch `externeURL`
  and extract readable text
- `src/jobfinder/store/`: schema + migrations, `upsert_job`, `touch_last_seen`,
  `export.py` writing `jobs-init.csv` as `utf-8-sig`
- `jobfinder search --dry-run` prints the exact URLs it would call

### Test-first checklist

- [ ] `test_spec_with_minijob_maps_to_ba_angebotsart_and_arbeitszeit_params`
- [ ] `test_spec_with_three_cities_produces_three_queries_with_correct_umkreis`
- [ ] `test_ba_fixture_parses_into_raw_postings_with_expected_fields`
- [ ] `test_ba_posting_id_is_source_prefixed_referenznummer`
- [ ] `test_ba_minijob_flag_is_read_from_istGeringfuegigeBeschaeftigung`
- [ ] `test_detail_fetch_base64_encodes_the_reference_number`
- [ ] `test_empty_description_triggers_external_url_fallback` (fixture: the real
      `jobboard.compleet.com` shape)
- [ ] `test_http_client_waits_between_requests_to_the_same_host` (fake clock)
- [ ] `test_http_client_serves_second_identical_request_from_cache`
- [ ] `test_request_budget_stops_the_run_and_records_it_in_runs_table`
- [ ] `test_upsert_same_job_twice_leaves_one_row_and_updates_last_seen`
- [ ] `test_dedupe_key_matches_same_job_from_two_sources`
- [ ] `test_export_csv_is_utf8_sig_and_umlauts_survive_a_round_trip`
- [ ] `test_export_csv_has_no_blank_lines_on_windows` (the `newline=""` bug)
- [ ] `test_source_failure_records_error_and_does_not_abort_the_run`
- [ ] The search-side resume tests from [§9](#tests-owned-by-phases-4-7-and-9-listed-together-because-the-rule-is-shared):
      per-page saving, cursor resume, interrupted-run marking, atomic export
- [ ] `tests/live/test_ba_contract.py` — endpoint answers, `referenznummer` and
      `stellenangebotsTitel` still exist, `X-API-Key` still accepted

### Done when

- [ ] A real run for her cities returns live postings and writes `jobs-init.csv`
- [ ] Running it again immediately adds **0** new rows and updates `last_seen_at`
- [ ] The CSV opens in Excel with correct umlauts and no empty rows
- [ ] Killing the run mid-way loses nothing already written

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

- [ ] `test_arbeitnow_fixture_parses_into_raw_postings`
- [ ] `test_arbeitnow_results_outside_her_cities_are_filtered_out`
- [ ] `test_arbeitnow_pagination_stops_at_the_last_page`
- [ ] `test_adzuna_adapter_is_skipped_cleanly_without_keys`
- [ ] `test_registry_runs_only_enabled_sources`
- [ ] `test_registry_continues_after_one_source_raises`
- [ ] `test_same_job_from_ba_and_arbeitnow_collapses_to_one_row_with_both_sources`
- [ ] `test_richest_record_wins_when_merging` (the one with a description)
- [ ] `test_run_summary_counts_match_the_database`
- [ ] `tests/live/test_arbeitnow_contract.py`

### Done when

- [ ] One `jobfinder search` covers all enabled API sources and prints a per-source summary
- [ ] Disabling a source in `config.yaml` visibly changes the summary and nothing breaks
- [ ] Duplicate rate across sources is measured and reported, not guessed

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

- [ ] `test_kleinanzeigen_fixture_yields_25_listing_urls_from_one_page`
- [ ] `test_kleinanzeigen_listing_parses_title_location_date_and_body`
- [ ] `test_kleinanzeigen_minijob_wording_sets_the_minijob_flag`
      ("Minijob", "450 €", "520 €", "Aushilfe", "geringfügig")
- [ ] `test_kleinanzeigen_gesuche_ads_are_excluded` — people *seeking* work, not offering it
- [ ] `test_unknown_city_has_no_kleinanzeigen_location_id_and_is_skipped_loudly`
- [ ] `tests/live/test_kleinanzeigen_location_ids.py` — each mapped id still returns ads
      whose location matches the intended city
- [ ] `test_stepstone_fixture_yields_expected_listing_urls`
- [ ] `test_stepstone_listing_page_parses_title_company_city_description`
- [ ] `test_jsonld_extraction_is_preferred_over_css_selectors`
- [ ] `test_missing_jsonld_falls_back_to_selectors_on_a_real_saved_page`
- [ ] `test_unparseable_page_records_a_failure_and_returns_nothing` (never a crash)
- [ ] `test_three_consecutive_failures_disable_the_source`
- [ ] `test_disabled_source_is_skipped_on_the_next_run_until_reset`
- [ ] `test_scraper_respects_min_delay_between_requests` (fake clock)
- [ ] `test_scraper_never_issues_parallel_requests_to_one_host`
- [ ] `test_429_response_honors_retry_after_then_gives_up`
- [ ] `test_login_walled_page_is_detected_and_skipped_not_retried`
- [ ] `test_user_agent_header_identifies_the_tool`
- [ ] `tests/live/test_scrapers_smoke.py` — one query per site, marked `live`,
      asserts ≥1 parseable result

### Done when

- [ ] Each scraper returns real listings for "Werkstudent München" and "Aushilfe Küche
      Ingolstadt"
- [ ] Kleinanzeigen returns ads for Neuburg, Ingolstadt and Munich with the right
      locations, and the minijob flag is right on a hand-checked sample of ten
- [ ] Turning all three off leaves the app fully working on API sources
- [ ] A deliberately corrupted fixture produces a clean "source failed" line, no traceback
- [ ] A full run makes no more requests than the budget allows, at human pace

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

### Test-first checklist

- [ ] `test_enrichment_prompt_includes_the_full_description_and_her_cv_digest`
- [ ] `test_fake_answer_maps_onto_every_enriched_csv_column`
- [ ] `test_german_level_outside_the_enum_is_rejected`
- [ ] `test_german_level_without_evidence_is_rejected` — no unsupported guesses
- [ ] `test_answer_in_german_is_rejected_by_the_validator` (summary must be English)
- [ ] `test_pipe_separated_list_fields_survive_a_csv_round_trip`
- [ ] `test_already_enriched_job_is_not_sent_again`
- [ ] `test_changed_description_triggers_re_enrichment`
- [ ] `test_new_prompt_version_triggers_re_enrichment_and_keeps_the_old_row`
- [ ] `test_batch_persists_each_result_as_it_lands` (kill after 3 of 10 → 3 saved)
- [ ] `test_one_failing_item_does_not_end_the_batch`
- [ ] `test_pool_exhausted_stops_cleanly_with_a_resumable_message`
- [ ] `test_enrich_limit_respects_the_llm_budget`
- [ ] The enrichment-side resume tests from [§9](#tests-owned-by-phases-4-7-and-9-listed-together-because-the-rule-is-shared):
      quota exhaustion keeps completed work, resume skips it, no half-written answers
- [ ] `tests/live/test_enrich_one_real_posting.py` (marked `live_llm`)

### Done when

- [ ] 20 real Bavarian postings enriched; she reads five and confirms the English
      summaries match the ads
- [ ] `german_level` is right on a hand-checked sample of ten, including at least
      three kitchen/retail ads where the requirement is often implicit
- [ ] Interrupting the batch and re-running resumes without re-spending calls
- [ ] A full re-run with no new jobs makes **zero** provider calls

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

- [ ] `test_index_lists_only_non_deleted_jobs`
- [ ] `test_filter_by_city_returns_only_that_city`
- [ ] `test_filter_by_max_german_level_excludes_c1_when_she_selects_b1`
- [ ] `test_filter_combination_city_and_type_and_fit`
- [ ] `test_sort_by_fit_score_descending`
- [ ] `test_job_page_renders_every_enriched_field_present_in_the_row`
- [ ] `test_job_page_renders_when_enrichment_is_missing` — never a 500 on a fresh job
- [ ] `test_mark_applied_persists_and_sets_applied_on_date`
- [ ] `test_delete_soft_deletes_and_survives_a_new_search_run`
- [ ] `test_notes_are_saved_and_shown_after_reload`
- [ ] `test_german_original_is_present_but_collapsed`
- [ ] `test_server_binds_localhost_only`
- [ ] `test_playwright_smoke_filter_open_job_mark_applied` (one end-to-end path)
- [ ] Plus every test in [§10](#tests-for-the-above-owned-by-phase-8)

### Done when

- [ ] She uses it for one real search session without asking a question
- [ ] During a four-minute search she can tell, at every moment, that it is working
      and roughly how far along it is — and a mid-run browser reload proves it
- [ ] Every action survives a restart of the app
- [ ] The list stays responsive at 1 000 jobs
- [ ] Nothing on screen is in German except the original ad and job titles

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

- [ ] `test_overpass_fixture_parses_places_with_and_without_contact_details`
- [ ] `test_places_without_any_contact_route_are_excluded`
- [ ] `test_contact_id_is_stable_across_runs` (OSM id based)
- [ ] `test_bakery_and_hotel_kitchen_outrank_a_bar_in_back_of_house_score`
- [ ] `test_phone_numbers_are_normalized_to_e164`
- [ ] `test_duplicate_place_across_two_city_queries_appears_once`
- [ ] `test_imprint_lookup_extracts_an_email_from_a_saved_page`
- [ ] `test_imprint_lookup_is_skipped_when_an_email_already_exists`
- [ ] `test_call_script_is_german_with_english_gloss_lines` (FakePool)
- [ ] `test_email_draft_names_the_place_and_her_availability`
- [ ] `test_contact_outcome_persists_and_filters_the_list`
- [ ] `tests/live/test_overpass_contract.py` — Neuburg still returns places with contacts

### Done when

- [ ] ≥ 50 contactable places across Neuburg, Ingolstadt and Munich, ranked
- [ ] She can print or open the list and start calling, script in hand
- [ ] Marking one "Called — come by Tuesday" persists and moves it out of the queue

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

- [ ] `test_free_port_is_chosen_when_default_is_busy`
- [ ] `test_first_run_wizard_appears_when_no_config_exists`
- [ ] `test_wizard_writes_env_and_config_and_never_logs_the_key`
- [ ] `test_wizard_is_skipped_on_second_start`
- [ ] `test_missing_keys_error_page_names_the_signup_links`
- [ ] `test_no_internet_produces_a_readable_page_not_a_traceback`
- [ ] `test_search_button_starts_a_run_and_streams_progress`
- [ ] `test_backup_rotation_keeps_five_and_deletes_the_sixth`
- [ ] `test_data_dir_resolves_next_to_the_exe_when_frozen` (PyInstaller `sys.frozen`)
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
