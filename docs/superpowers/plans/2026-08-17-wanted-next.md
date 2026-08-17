---
title: "Wanted next — the Enrich button, her CV, and a posting-date filter"
date: 2026-08-17
type: feature-plan
status: in progress
master-plan: docs/MASTER_PLAN.md#wanted-next--asked-for-after-using-the-app
---

# Wanted next — task plan

Map: [MASTER_PLAN § Wanted next](../../MASTER_PLAN.md#wanted-next--asked-for-after-using-the-app).
Three things she named after clicking through the finished Phase 8. This file is
the turn-by-turn version: test-first, one checklist item per commit, pushed as
it lands.

The three are ordered by how much of the product they unlock, not by size:

1. **The Enrich button** — 839 of her 859 jobs have no English answer, and no
   way to get one without a terminal. This is the one that makes the shipped
   app become the product it describes.
2. **Her CV, from the browser** — `pool.yaml` is the input to the fit score and
   the role suggestions, and today it can only be edited as a file beside the
   source code.
3. **A posting-date filter** — needs a data fix first, so it comes last.

## What the store actually holds (measured 2026-08-17, not assumed)

Counted against her real `data/jobfinder.db` before writing a line of this:

- **859 jobs**, sources `BA` 516, `AZ` 260, `XI` 39, `KA` 27, `AN` 17
- **20 enriched**, 839 not — the number MASTER_PLAN quotes, still true
- `published_at` present on **859 of 859**, in three shapes:
  `2026-07-01` (BA, KA, XI), `2026-06-20T12:20:44Z` (AZ),
  `2026-08-16T02:09:29+00:00` (AN)
- stored range **2022-12-15 → 2026-08-16** — ads far older than they look are
  already in her list
- the newest run row is an `interrupted` search: 258 found, 117 new

That third shape (`+00:00`) is one MASTER_PLAN did not record — it names two.
A string comparison across all three is wrong at more than the boundary:
`'2026-08-16' < '2026-08-16T02:09:29Z'` is true, so "posted today" would drop
every plain-date ad posted today.

## What already exists (do not rebuild)

- `enrich/companion.py` `EnrichmentCompanion` — polls the store for jobs
  needing an answer, journals a `runs` row of kind `enrich`, counts every answer
  through `note_enriched`, and already has `cancel()` and `finish()`. **The
  store is the queue**, so enrichment needs no handover from a search.
- `web/runs.py` `RunManager` — one daemon thread, a `StartRefused` carrying a
  sentence and a link, and `production_companion_factory` which already builds
  the companion or refuses with "no key" / "no readable CV".
- `web/routes.py` `_progress_context` — reads `latest_run(kind="enrich")` and
  hands the template `enrichment` + `enrich_state` already.
- `_progress.html` — renders `Explaining jobs in English as they arrive — N
  explained so far` when an enrich run is live, and owns the 1-second poll.
- `store/enrichment.py` `jobs_needing_enrichment` / `already_enriched_count` —
  the queue query and the count, both prompt-version aware.
- `profile.py` `load_profile` — parses `pool.yaml` and answers every failure
  with one sentence naming the field and the line (Phase 1).
- `roles.py` `suggest_roles` / `stored_suggestions` / `build_cv_digest`.
- `store/db.py` — `ADDED_COLUMNS` + `migrate()`, the ALTER path a live
  database with 859 rows in it needs.
- `web/queries.py` `JobFilters` — now holds tuples per filter, with `_picked`
  validating each value.

## Decisions

1. **Enrichment gets its own `RunManager` slot, not the search's.** A search
   and an enrichment pass do not contend (§9: one waits on job-site hosts, the
   other on LLM providers), so `POST /run/enrich` must not be refused because a
   search is running, and cancelling one must not cancel the other. The manager
   grows a second thread handle rather than a second manager, so `is_running()`
   keeps meaning "a search is running" and gains `is_enriching()`.
2. **The cost is announced before it is spent, in the same panel.** The
   cross-cutting free-tier rule says a run says how many calls it will make
   before making them. So the Enrich button carries a count read from the store
   (`839 jobs have no English answer yet`) and a `limit` she can lower, and the
   default is **not** "all of them" — it is 50, one visible batch, because the
   honest default for a free tier is the one that leaves her quota alive.
3. **Resume is the same button.** §9 already makes a second pass skip what the
   first stored, so there is nothing to resume *to* — pressing Enrich again
   continues. The panel says so rather than growing a second control.
4. **The CV is uploaded, validated, and only then written.** The upload lands
   in a temp file, `load_profile` parses it, and `pool.yaml` is replaced only
   if that succeeds — a bad paste must never destroy the CV she already had.
   The old file is kept as `pool.yaml.bak` for exactly that reason.
5. **`published_on` is a new column, not a rewrite of `published_at`.** The raw
   value stays exactly as the source gave it (it is what the job page shows);
   the comparable date is derived once, on the way in, by one function every
   adapter reaches through `RawPosting.published_on`. Schema v7 adds the column
   and backfills all 859 rows with the same function, so stored and incoming
   rows can never disagree.
6. **The date filter is a bound, not a range.** "posted within 3 days / a week
   / a month / any" — four options, one query parameter, the same
   `_picked`-style validation as the rest. A from/to range is a second
   question and nobody asked it.

---

## A — The Enrich button

### A1 — The store can say what a pass would cost

- [ ] `test_pending_enrichment_count_counts_only_jobs_with_an_ad_text`
- [ ] `test_pending_enrichment_count_ignores_jobs_already_answered_at_this_version`
- [ ] `test_pending_enrichment_count_is_zero_on_an_empty_store`

`store/enrichment.py` gains `pending_enrichment_count(connection, prompt_version)`.
`jobs_needing_enrichment` already selects exactly the right rows, but it
*fetches* them — the panel needs the number, not 839 rows, on every poll.

### A2 — `RunManager` can start an enrichment pass on its own thread

- [ ] `test_start_enrich_runs_the_companion_and_journals_an_enrich_run`
- [ ] `test_start_enrich_is_refused_while_an_enrichment_is_already_running`
- [ ] `test_start_enrich_is_allowed_while_a_search_is_running`
- [ ] `test_cancel_enrich_stops_the_pass_and_keeps_what_it_saved`
- [ ] `test_cancel_enrich_does_not_cancel_a_running_search`
- [ ] `test_enrich_refusal_names_the_missing_key_and_links_to_settings`
- [ ] `test_enrich_refusal_names_the_unreadable_cv_and_links_to_settings`
- [ ] `test_an_enrichment_that_dies_leaves_a_sentence_not_a_traceback`

`start_enrich(limit=...)` builds the companion through the existing factory
(so both refusals come for free), starts it, and joins it on a second thread
handle. The thread's body is `companion.start()` → `companion.finish()`; the
companion already does the batching, the journalling and the CSV append.

`limit` is new to the companion: it drains until nothing is left today, so a
bound is the difference between 50 calls and 839. It caps total sent, not per
batch.

- [ ] `test_companion_stops_after_the_limit_is_reached`
- [ ] `test_companion_without_a_limit_keeps_the_old_behaviour`

### A3 — `POST /run/enrich` and `POST /run/enrich/cancel`

- [ ] `test_post_run_enrich_starts_a_pass_and_returns_the_panel`
- [ ] `test_post_run_enrich_honours_the_limit_she_typed`
- [ ] `test_post_run_enrich_without_a_key_renders_the_refusal_not_a_500`
- [ ] `test_post_run_enrich_cancel_stops_it_and_returns_the_panel`
- [ ] `test_a_plain_form_post_redirects_back_to_the_enrich_page`

Same shape as `/run/start`: HTMX gets `_progress.html`, a plain post gets a 303.

### A4 — The Enrich page says what it will spend before spending it

- [ ] `test_the_enrich_form_names_how_many_jobs_have_no_answer_yet`
- [ ] `test_the_enrich_form_says_one_call_per_job_before_she_presses_it`
- [ ] `test_the_enrich_form_offers_a_limit_defaulting_to_fifty`
- [ ] `test_a_fully_enriched_store_offers_no_button_and_says_so`
- [ ] `test_a_live_enrichment_shows_its_count_and_a_cancel_button`
- [ ] `test_the_enrich_panel_survives_a_reload_mid_pass`
- [ ] `test_an_interrupted_enrichment_says_pressing_it_again_continues`
- [ ] `test_the_nav_links_to_the_enrich_page`

The Enrich surface is its own page (`/enrich`), for the reason searching got
one: the two buttons cost different things, and side by side she cannot see
which. Its progress partial is `_enrich_progress.html`, polling `/enrich/progress`
on the same 1-second trigger — the search panel keeps its own so a search and an
enrichment pass can be watched at once without either swapping the other away.

### A5 — Run it for real and record what it did

- [ ] Press it against her real store with `limit=10`, watch the count move,
      and record the calls spent, the answers landed, and the wall time here
- [ ] Cancel one mid-pass; confirm the run row ends `interrupted`, the answers
      already saved are still there, and `jobs-enriched.csv` matches the store
- [ ] Reload the browser mid-pass; confirm the count is current, not restarted

---

## B — Her CV, from the browser

### B1 — The template is downloadable

- [ ] `test_get_pool_template_serves_the_file_as_an_attachment`
- [ ] `test_the_template_download_is_utf8_and_keeps_its_umlauts`

`pool.template.yaml` ships in the repo root today. It is served from
`/settings/cv/template` so she never has to find it on disk.

### B2 — An upload is validated before it replaces anything

- [ ] `test_a_valid_upload_is_written_to_pool_yaml`
- [ ] `test_a_valid_upload_keeps_the_previous_file_as_a_backup`
- [ ] `test_an_invalid_upload_leaves_the_existing_pool_yaml_untouched`
- [ ] `test_an_invalid_upload_shows_the_profile_error_sentence`
- [ ] `test_an_upload_that_is_not_yaml_at_all_is_refused_readably`
- [ ] `test_an_empty_upload_is_refused_readably`
- [ ] `test_the_upload_is_never_logged` (her name and address are in it)

### B3 — The Settings page shows whether a CV is there, and what it says

- [ ] `test_settings_says_no_cv_yet_and_offers_the_template`
- [ ] `test_settings_summarises_the_cv_it_found`
- [ ] `test_settings_names_the_field_and_line_when_the_cv_will_not_parse`
- [ ] `test_settings_never_renders_her_address_or_phone_number`

The summary is the one `jobfinder profile validate` prints — name withheld:
languages, years of experience, education, skills count. Enough to recognise
that the right file landed, nothing that needs to be on a screen someone else
might see.

### B4 — Role suggestions can be asked for from the browser

- [ ] `test_suggest_roles_button_appears_once_a_cv_is_present`
- [ ] `test_post_suggest_roles_stores_and_renders_the_titles`
- [ ] `test_suggest_roles_without_a_key_refuses_with_a_link_not_a_500`
- [ ] `test_stored_suggestions_are_shown_without_spending_a_call`
- [ ] `test_a_suggested_role_links_into_the_search_form_as_a_keyword`

### B5 — Run it for real

- [ ] Upload her actual `pool.yaml` through the browser, confirm the summary
      matches `jobfinder profile validate`, and that the backup exists
- [ ] Upload a deliberately broken copy; confirm the good file survived
- [ ] Confirm fit scores appear on the list once a CV is present

---

## C — A posting-date filter

### C1 — One function turns every stored shape into a comparable date

- [ ] `test_a_plain_date_is_already_comparable`
- [ ] `test_a_zulu_timestamp_becomes_its_date`
- [ ] `test_an_offset_timestamp_becomes_its_date` (the `+00:00` shape)
- [ ] `test_a_local_offset_timestamp_is_converted_before_the_date_is_taken`
- [ ] `test_junk_and_none_become_none_rather_than_raising`
- [ ] `test_raw_posting_exposes_published_on_from_published_at`

`dates.py` `published_on(raw)` → `YYYY-MM-DD | None`. Every adapter reaches it
through `RawPosting.published_on`, so no adapter has to remember.

### C2 — Schema v7 stores it, and backfills the 859 rows already there

- [ ] `test_upsert_stores_the_comparable_date_beside_the_raw_one`
- [ ] `test_migrating_a_v6_database_backfills_published_on`
- [ ] `test_migrating_twice_changes_nothing`
- [ ] `test_a_row_with_an_unparseable_date_backfills_to_null_not_a_crash`

### C3 — The filter

- [ ] `test_posted_within_a_week_excludes_an_older_ad`
- [ ] `test_posted_within_a_week_includes_a_plain_date_ad_from_today`
      (the bug a string comparison would have shipped)
- [ ] `test_posted_within_any_is_no_filter_at_all`
- [ ] `test_a_job_with_no_date_is_excluded_when_a_bound_is_set`
- [ ] `test_an_unknown_bound_is_dropped_like_any_stale_link`
- [ ] `test_the_bound_survives_paging`
- [ ] `test_the_bound_is_named_in_the_active_filters_line`
- [ ] `test_the_empty_state_offers_to_loosen_the_date_bound`

### C4 — Run it for real

- [ ] Filter her store by each bound and record the counts here, against
      counts taken straight from SQL — the filter and the database must agree

---

## Definition of done for this file

- [ ] Every behaviour above had a failing test first, and the failure was watched
- [ ] `pytest` green, no network, no warnings
- [ ] `ruff check` and `ruff format --check` clean
- [ ] Each of the three sections demonstrated on her real 859-job store, with
      the measured numbers written back into this file
- [ ] MASTER_PLAN's "Wanted next" section updated to say what shipped
- [ ] Atomic commits on `feat/wanted-next`, pushed as they land
