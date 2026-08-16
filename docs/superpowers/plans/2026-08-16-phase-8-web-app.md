---
title: "Phase 8 — The app she actually uses"
date: 2026-08-16
type: phase-plan
status: complete — T1-T8 shipped, verified on her real store 2026-08-16
master-plan: docs/MASTER_PLAN.md#phase-8--the-app-she-actually-uses
---

# Phase 8 task plan

Map: [MASTER_PLAN §Phase 8](../../MASTER_PLAN.md). This file is the turn-by-turn
version. Test-first, one checklist item per commit, pushed as it lands.

**This is the milestone that makes the project real.** Everything to now built
a database she reads through CSV exports. After this, she opens a browser,
filters her 674 jobs, reads one page per job in English, and marks what she
applied to.

## What the store already holds (measured, not assumed)

Her database after Phase 7: 674 jobs across 4 sources (BA 447, Adzuna 202,
Xing 18, Kleinanzeigen 7), of which **20** carry an answer at `enrich.v1`.

> **Corrected 2026-08-16, at T8.** This section originally claimed "5 sources,
> 660+ enriched answers", and both halves were wrong when counted. Phase 7
> enriched the twenty postings its own done-when asked for and stopped; the
> rest of the store has never been through a batch. The list and job pages are
> built for that: an unenriched job reads "not read yet" with no fit score,
> which is the truth rather than a gap. Nothing in the plan below depended on
> the wrong number, but a premise nobody checked is exactly the kind of thing
> this document exists to stop.

Everything the list and job pages need exists — but not all of it exists
**queryably**:

- `german_level` and `fit_score` live inside `enrichment.answer` as JSON.
  Filtering and sorting on them means `json_extract` in SQL, not fetching and
  parsing 674 rows per request.
- `status` has no `applied_on` column. The plan's own test
  (`test_mark_applied_persists_and_sets_applied_on_date`) promises a date, and
  the schema has nowhere to put it.
- The `runs` journal has run-level counts but **no per-source progress** —
  §10's `Bundesagentur — 42 found, 7 new` lines exist only in CLI stdout
  today. §10 says progress is read from the database, so the journal, not the
  web app's memory, has to hold them.
- Nothing can cancel a run from outside its own thread. The runner's stop
  event is internal; §10's Cancel button needs a handle on it.

## What already exists (do not rebuild)

- `store/db.py` — WAL connections, idempotent migrations, the ALTER path for
  live databases. Schema v6 goes through the same machinery.
- `store/jobs.py` `upsert_job` — the re-run rule that makes soft-delete safe:
  a deleted job re-found by a search moves `last_seen_at` and nothing else.
- `search.py` `run_search_until_done` — legs, cursors, the run journal
  (`runs`), stale-run closing. The web app **calls this**, it does not
  reimplement it.
- `enrich/companion.py` — enrichment as a second worker over the same store.
- `enrich/fields.py` `ENRICHED_COLUMNS` — the one true field list; the job
  page renders those, in that vocabulary.
- `cli.py` — `jobfinder serve` joins it; the CLI commands stay as they are.
- `sources/registry.py` `SOURCE_LABELS` — plain-English source names.

## Decisions

1. **FastAPI + Jinja2 + HTMX + one CSS file, all vendored.** No CDN, no build
   step — `htmx.min.js` (v1.9.12), Geist and JetBrains Mono woff2 files live in
   `web/static/` and ship inside the package, because the Phase 10 `.exe` must
   work offline. Fonts fall back to system stacks if a file is missing.
2. **Schema v6, through the ALTER path her database already knows:**
   `status.applied_on TEXT`, `runs.enriched_count INTEGER DEFAULT 0`, and a
   new `run_sources` table `(run_id, source, found/new/duplicate counts,
   state, last_event_at)` that the search writer updates per stored page.
   Progress read from the database (§10) stops being a slogan and becomes a
   SELECT.
3. **The web layer reads; only `status` is hers to write.** One query module
   (`web/queries.py`) builds the list/detail SELECTs with `json_extract` for
   `german_level`/`fit_score`. Enrichment answers are read at the **current**
   prompt version; a job enriched only at an older version renders as
   un-enriched, which is the truth.
4. **`max German level` filters honestly.** Levels order `none < A1 < … < C2`;
   selecting max B1 excludes C1/C2 **and `unclear`** — a job that cannot say
   what it needs cannot promise it fits her bound. The empty state says so.
5. **Runs start, resume and cancel from the UI.** A small `RunManager`
   (`web/runs.py`) owns one daemon thread per search, reusing the CLI's
   adapter factory and `run_search_until_done`. `run_search` gains a
   `stop_event` parameter: the Cancel button sets it, the runner stops between
   pages, the run row ends `interrupted` (not `done`), and everything already
   stored is kept — §9 makes that free. The companion gains `cancel()` the
   same way.
6. **Enrichment from the UI needs her keys, and says so.** The Search button
   starts search + enrichment when keys exist and a CV parses; a missing key
   renders one sentence plus a link to the Settings page (§10's
   missing-API-key rule) — never a traceback, and the search itself still
   starts, because a search needs no LLM.
7. **Distance is her home to the job, computed in Python.** `jobs.lat/lon`
   against Neuburg an der Donau (§1), haversine, rounded to whole km, sorted
   in Python after the SQL page is fetched — the list is 50 rows a page and
   674 rows total; SQLite does the filtering, Python does the trigonometry.
8. **Skeleton, empty and error states ship with the success state.** The list
   response always carries skeleton rows matching the real row layout; an
   empty result names the filters that produced it and the one to loosen; the
   progress panel is an HTMX-polled partial so a reload mid-run shows the
   same state from the database.
9. **Plain English everywhere (§10).** `Bundesagentur — 42 found, 7 new`, not
   `GET /pc/v6/jobs 200`. No emoji, ever — a template-grep test holds that
   line. Numbers (fit, km, dates, counts) render in the mono face.
10. **Her German level for the three-step scale** reads from `pool.yaml`
    (German entry) when it parses, else defaults to A2 (§1: "limited"). The
    scale reads comfortable / stretch / out of reach and works in greyscale.

## Tasks

### T1 — this plan doc
Commit: `docs: phase-8 task plan grounded in what the store can already answer`.

### T2 — schema v6 + the journal and cancel hooks the UI needs
`store/db.py` v6 (`status.applied_on`, `runs.enriched_count`, `run_sources`);
`search.py` writes per-source progress rows per page and takes `stop_event`
(an external stop ends the run `interrupted`); `store/status.py` —
`set_status` (valid transitions, `applied_on` on applied), `set_notes`;
companion journals a `runs` row of kind `enrich` and gains `cancel()`.
Tests: `tests/store/test_status.py`,
`test_cancel_event_ends_the_run_interrupted_between_pages`,
`test_each_page_updates_the_run_sources_row`,
`test_companion_journals_its_progress_and_cancel_ends_it`.
Commit: `feat: schema v6 — applied dates, per-source progress, cancellable runs`.

### T3 — the app skeleton, localhost-only, `jobfinder serve`
`web/app.py` `create_app(settings)` with Jinja2 templates, static files,
`web/templates/base.html` (fonts, HTMX, the CSS), the progress panel slot;
`SERVER_HOST = "127.0.0.1"`; `jobfinder serve [--port] [--no-browser]` starts
uvicorn and opens the browser. Tests: `tests/web/test_app.py`
`test_server_binds_localhost_only`, `test_serve_command_starts_and_answers`.
Commit: `feat: the FastAPI app, localhost-only, served by jobfinder serve`.

### T4 — the list page: filters, sorting, the three states
`web/queries.py` (the SELECTs) + `routes.py` `/` and `/jobs/rows` with
filters (city, type, max German, min fit, source, status), sorts (fit, date,
distance), 50-row pages, distance from home, 14-day greying, skeleton and
empty states. Tests (exact plan names):
`test_index_lists_only_non_deleted_jobs`, `test_filter_by_city_returns_only_that_city`,
`test_filter_by_max_german_level_excludes_c1_when_she_selects_b1`,
`test_filter_combination_city_and_type_and_fit`, `test_sort_by_fit_score_descending`,
`test_every_list_page_renders_a_skeleton_state`,
`test_empty_result_page_names_the_filters_that_were_applied`.
Commit: `feat: the job list — filtered, sorted, honest about being empty`.

### T5 — the job page and her actions on it
`/jobs/{job_id}` rendering every `ENRICHED_COLUMNS` field, German level with
its evidence phrase and three-step scale, the German original in a collapsed
`<details>`, stale greying; POST `/jobs/{id}/status` and `/jobs/{id}/notes`.
Tests: `test_job_page_renders_every_enriched_field_present_in_the_row`,
`test_job_page_renders_when_enrichment_is_missing`,
`test_mark_applied_persists_and_sets_applied_on_date`,
`test_delete_soft_deletes_and_survives_a_new_search_run`,
`test_notes_are_saved_and_shown_after_reload`,
`test_german_original_is_present_but_collapsed`.
Commit: `feat: one page per job, in English, with her decisions on it`.

### T6 — the live progress surface
`web/runs.py` RunManager (start/resume/cancel, one thread, journal-backed);
`/progress` partial: determinate-enough bar (found/new counters, elapsed,
jobs per minute), per-source lines from `run_sources`, Cancel, interrupted-run
banner with Resume and its counts; the Settings page and the missing-key
sentence. Tests: `test_progress_endpoint_reports_current_source_and_counts`,
`test_search_progress_is_persisted_and_survives_a_page_reload`,
`test_cancel_stops_the_run_and_keeps_completed_work`,
`test_interrupted_run_banner_offers_resume_with_the_right_counts`,
`test_missing_api_key_renders_a_sentence_and_a_link_not_a_traceback`.
Commit: `feat: search from the browser, narrated from the database`.

### T7 — the visual rules, held by tests, and the end-to-end smoke
`test_no_emoji_in_any_template` (grep), `test_numbers_render_in_the_monospace_class`
(render a row, assert the score/km/date are in the mono class),
`tests/web/test_playwright_smoke.py`
`test_playwright_smoke_filter_open_job_mark_applied` — skips cleanly when
Playwright is not installed, drives a real browser against a real server on
127.0.0.1.
Commit: `test: the visual rules and one real end-to-end path`.

### T8 — done-when on her real data, docs, merge
`jobfinder serve` against her 674-job database: browse, filter, open jobs,
mark one applied, confirm restart survival and a 1 000-row page time; tick
the MASTER_PLAN boxes; CLAUDE.md commands; merge.

**Done, and it earned its place.** Driving the real app found four defects that
616 green tests did not, every one of them on a path the tests exercised
through a seam rather than end to end:

| Found | Why no test caught it | Commit |
|---|---|---|
| `jobfinder serve` died on startup — `uvicorn.run()` has no `callback_notify` | The three serve tests injected a fake serve; the HTTP test built its own uvicorn config. Nothing called `_uvicorn_serve` | `fix: jobfinder serve really starts…` |
| `callback_notify` would have reopened her browser tab every second, and deadlocks the loop it is awaited on | It is uvicorn's own heartbeat, not a one-shot ready hook — only a real server shows that | same |
| "The work" and "You need" rendered a heading over an empty list | Every fixture answer had duties and requirements. Her real store had an ad too short to have any | `fix: a section the ad says nothing about says so…` |
| The empty state offered filters she had not set, and a caveat that was untrue of her search | The test asserted the named filters appeared, not that unnamed ones stayed away | `fix: the empty state offers the filters she set…` |
| `started_at`, `last_progress_at` and `finished_at` were one frozen stamp, so §9's stale rule would close a healthy long run | Tests froze `now` deliberately and asserted counts, never that the clock moved | `fix: the run journal keeps time…` |

Measured on the way through: 1 348-job list page in 413 ms (row pages
103–125 ms); a live search narrating `104 found, 15 new` with per-source lines;
a mid-run reload returning the same run with current counts; Cancel leaving
282 found / 68 new kept and an `interrupted` row behind the Resume banner.

## Done when (mirrored from MASTER_PLAN)

- She uses it for one real search session without asking a question
- During a four-minute search she can tell, at every moment, that it is working
  and roughly how far along it is — and a mid-run browser reload proves it
- Every action survives a restart of the app
- The list stays responsive at 1 000 jobs
- Nothing on screen is in German except the original ad and job titles
