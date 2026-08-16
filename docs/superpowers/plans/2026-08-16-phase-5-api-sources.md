---
title: Phase 5 — Arbeitnow, Adzuna, the registry, and cross-source dedupe
date: 2026-08-16
type: phase-plan
status: in progress
---

# Phase 5 task plan

Branch: `feat/phase-5-api-sources`. Source of truth: `docs/MASTER_PLAN.md`
§ Phase 5, §5 (data contracts), §8 (etiquette), §9 (resume). One task = one
commit, the MASTER_PLAN box ticked in the same commit, pushed immediately.

This phase also owns the three items the Phase 4 audit left open (see
`2026-08-16-phase-4-audit-and-search-shape.md`, "Still open"): the silent cold
run, the lying `--resume` message, and the detail-fetch cost decision.

## Verified API facts (probed live 2026-08-16 — do not re-derive)

### Arbeitnow

- `GET https://www.arbeitnow.com/api/job-board-api` — no key, no query
  parameters except `?page=N` (1-based). Response is `{data, links, meta}`.
- `data[]` fields: `slug` (stable, ends in a numeric id — the `source_id`),
  `company_name`, `title`, `description` (**HTML**, not plain text — goes
  through `extract_readable_text` before hashing), `url` (the Arbeitnow job
  page — `source_url`), `tags[]`, `job_types[]` (free text), `location` (a
  plain city string like `"München"` — **no plz, no coordinates, no radius**),
  `remote` (bool), `created_at` (unix epoch seconds).
- Pagination: `meta.per_page` is **175**. `links.next` is the only end signal —
  `links.last` is `null`, there is no total. Stop when `data` is empty or
  `links.next` is null. Jobs are ordered newest first and refreshed hourly.
- `job_types` is free text: `"Working Student"`, `"Working student"`,
  `"Part time"`, `"Part Time"`, `"Full-time"`, `"Intern"`, `"Trainee"`, plus
  German values and noise. **35 of 175 jobs on the recorded page have an empty
  `job_types`** — a fallback rule is mandatory, not optional.
- Bavaria is well represented: 25 of 175 entries on page 1 were `München`.
- No employment-type or keyword filter exists server-side — city, type and
  keyword filtering are all client-side, on one pass over the pages.

### Adzuna

- No `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` in `.env` as of 2026-08-16. MASTER_PLAN
  says: enabled only when the keys exist; absent keys mean **skipped**, not an
  error. Nothing can be recorded or verified live without a key, so this phase
  ships the skip logic and the query builder only — parsing code and its
  fixture-backed tests wait until she registers a key (recorded as a known gap
  in MASTER_PLAN, not silently skipped).

## Decisions (written down so they are not re-argued mid-phase)

1. **Employment types stay alternatives at the query layer** (Phase 4 audit,
   "For Phase 5"): Arbeitnow cannot filter by type server-side, so its
   "queries" are one walk over the pages with a client-side predicate — a job
   passes when it matches **any** selected type. Type matching: normalised
   `job_types` substrings (`working student` → werkstudent, `part time` →
   parttime, `full time` → fulltime, `intern` → internship); minijob has no
   signal in `job_types` and is detected from title wording ("Minijob",
   "450 €", "520 €", "geringfügig", "Aushilfe" — the Phase 6 wording list).
   Empty `job_types` falls back to title wording hints; a job with neither is
   excluded when specific types are selected.
2. **City matching is exact on the canonical name**, casefolded
   (`"München"` matches; `"Munich"` does not — Arbeitnow writes German names).
   Radius **cannot** apply: the API returns no coordinates. Her keywords, when
   given, filter on title + tags casefolded, never on description text.
3. **Arbeitnow pages are capped** at `MAX_PAGES = 10` (newest ~1 750 postings)
   on top of the request budget — `links.last` is null, so without a cap a full
   walk is unbounded, and §8 makes request count the scarce resource.
4. **Cross-source dedupe merges into the existing row.** A new posting whose
   `dedupe_key` matches a job already stored from another source does **not**
   insert a second row: the existing job keeps its `job_id`, `first_seen_at`
   and her status (the identity she may already have applied under); the
   alternate source is appended to a new `jobs.also_seen_on` column; and
   "richest record wins" means fields the existing row lacks are backfilled
   from the newcomer (description + `content_hash` + `has_description`,
   `apply_url` when missing). Her status is never overwritten by a merge.
5. **`also_seen_on` is a contract change**: it is added to the `jobs` table
   (schema v3, with an `ALTER TABLE` path for existing databases) and appended
   to the `jobs-init.csv` column list in MASTER_PLAN §5.
6. **Per-source budget = one `PoliteClient` per adapter.** The registry builds
   each adapter with its own client, so each source spends
   `settings.request_budget` per leg independently — matching the audit's
   "a source's own budget is spent per leg" and keeping one hungry source from
   starving another. `run_search_until_done` already rebuilds adapters between
   legs, so no adapter may hold state that must survive its client.
7. **The three audit leftovers land here, as tasks T9–T11** (below), including
   an explicit written decision on detail-fetch cost rather than another
   deferral.

## Tasks

### T1 — this plan doc
Commit: `docs: phase-5 task plan with verified Arbeitnow facts`.

### T2 — `sources/registry.py`: adapters from settings
`tests/unit/test_registry.py` (fake adapters + fake client factory):
- `build_adapters(settings, client_factory)` returns one adapter per enabled
  source in fixed order (ba, arbeitnow, adzuna), each with its **own** client;
- a source named in `enabled_sources` but unknown → readable error naming the
  valid names;
- adzuna with no keys in the environment → absent from the list, reported as
  skipped, never as an error;
- default `enabled_sources` becomes `("ba", "arbeitnow")` (config test updated);
  CLI `_default_client_factory` replaced by the registry.
Commit: `feat: source registry — one adapter and one budget per enabled source`.

### T3 — per-source counts in the run summary
`tests/unit/test_search.py` + `tests/unit/test_cli_search.py`:
- `run_search` accumulates `per_source: {source: SourceCounts(found, new,
  duplicates, errors)}`; a raising source lands in that source's `errors` and
  the run continues (the registry-level guarantee, tested through the runner);
- `jobfinder search` prints one line per source in her words —
  `Bundesagentur — 42 found, 7 new` — plus `Arbeitnow — skipped (disabled)`
  when a configured source is off.
Commit: `feat: per-source counts in the run summary`.

### T4 — `sources/arbeitnow.py`: the adapter
`tests/sources/test_arbeitnow.py` against the recorded fixture
(`tests/fixtures/arbeitnow/job_board_page1.json`, 175 real entries):
- fixture parses into `RawPosting`s: `AN:{slug}` ids, HTML description
  extracted to text, epoch `created_at` → ISO `published_at`, `remote` →
  homeoffice;
- entries outside her cities are filtered out (client-side city predicate);
- type predicate: `working student` job_types pass a werkstudent spec; a
  `Full Time`-only job does not; empty `job_types` + werkstudent title passes;
  neither signal → excluded when types are selected;
- minijob wording in the title sets `is_minijob`;
- pagination: page param from `?page=`, stops when `data` empty or
  `links.next` null, capped at `MAX_PAGES`; resume cursor (`start_page`)
  re-enters at the stored page.
Commit: `feat: Arbeitnow adapter — one pass, client-side filters`.

### T5 — Arbeitnow live contract
`tests/live/test_arbeitnow_contract.py` (marked `live`): endpoint answers 200,
`data[0]` still carries `slug`/`title`/`location`/`job_types`/`created_at`,
`links.next` shape unchanged. Shape only, never counts.
Commit: `test: live Arbeitnow contract — shape only`.

### T6 — `sources/adzuna.py`: optional key, clean skip
`tests/sources/test_adzuna.py` (no network, no fixture — parsing is deferred
until a key exists):
- adapter reports skipped (not error) when `ADZUNA_APP_ID`/`ADZUNA_APP_KEY`
  are absent; registry omits it (covered in T2, asserted here end to end);
- query builder: `where` = city name, `distance` = radius km, employment
  types as **alternatives** (one query per type: `part_time=1` / `full_time=1`,
  werkstudent/internship as `what` terms), `results_per_page`, `page` —
  values recorded for live verification the day a key is registered.
Commit: `feat: Adzuna adapter — optional key, clean skip, query builder`.

### T7 — cross-source dedupe: `also_seen_on` + richest-record merge
`tests/store/test_jobs.py` + `tests/store/test_db.py` + `tests/store/test_export.py`:
- schema v3: `also_seen_on` column added; an existing v2 database migrates
  without losing rows (ALTER TABLE path — `CREATE TABLE IF NOT EXISTS` alone
  cannot evolve a live database);
- same job (`dedupe_key`) from BA then Arbeitnow → **one** row, existing
  identity kept, `also_seen_on` gains `AN`;
- richest record wins: a newcomer with a description backfills
  description/`content_hash`/`has_description` and a missing `apply_url`; her
  status row is untouched;
- re-run rule intact: same `job_id` again still only moves `last_seen_at`;
- `jobs-init.csv` gains the `also_seen_on` column, umlaut round-trip still
  holds.
Commit: `feat: cross-source dedupe — richest record wins, alternates recorded`.

### T8 — run summary reconciles with the database
`tests/unit/test_search.py`: after a mixed run (two sources, one duplicate
across sources, one failing source), every per-source count equals what
`SELECT ... GROUP BY source` says, and found = new + duplicates per source.
Ticks `test_run_summary_counts_match_the_database`.
Commit: `test: run summary counts reconcile with the store`.

### T9 — audit leftover 1: a cold run narrates itself
`tests/unit/test_cli_search.py`: `jobfinder search` passes an `on_page`
printer to the runner — every stored page prints one plain line (source,
found/new/already-known counts), flushed, so a cold run with an empty cache is
never silent for minutes (§10 panic rule; the full progress surface is still
Phase 8's). Also print a line when a leg auto-continues (the `on_leg` hook
exists).
Commit: `feat: narrate each page as a search runs`.

### T10 — audit leftover 2: `--resume` with nothing to continue says so
`tests/unit/test_cli_search.py`:
- `--resume` after a finished run (cursor past the last query, 0 found) prints
  that the last search already finished and everything it found is in the
  list — not `Search finished: 0 jobs found`;
- `--resume` with no stored cursor at all says nothing was interrupted and a
  fresh search was run instead.
Commit: `fix: --resume with nothing to continue says so, not "0 jobs found"`.

### T11 — audit leftover 3: detail fetches only for jobs not already known
`tests/unit/test_search.py` with a fake adapter that counts `fetch_detail`:
- a re-run of the same pages performs **zero** `fetch_detail` calls for
  already-known `job_id`s while still moving `last_seen_at` (the re-run rule
  unchanged);
- new postings still get their detail fetched before the first insert.
**Decision recorded in MASTER_PLAN** (this task closes it): moving the detail
fetch into enrichment is *rejected for now* — Phase 5's merge needs
descriptions at search time to pick the richest record, and `has_description`
is a Phase 4 contract; Phase 7 revisits the idea only if live budgets prove
it necessary.
Commit: `feat: skip detail fetches for jobs already known`.

### T12 — done-when on real data
Real `jobfinder search` with all enabled sources: per-source summary lines,
duplicate rate across BA/Arbeitnow measured from a real run and written into
this plan, disabling a source in `config.yaml` visibly changes the summary and
nothing breaks. Tick the Phase 5 done-when boxes, merge, push.

## Done when (mirrored from MASTER_PLAN)

- One `jobfinder search` covers all enabled API sources and prints a
  per-source summary
- Disabling a source in `config.yaml` visibly changes the summary and nothing
  breaks
- Duplicate rate across sources is measured and reported, not guessed
