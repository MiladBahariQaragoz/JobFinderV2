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
4. **The CV is uploaded, validated, and only then written.** The text is parsed
   before anything on disk is touched, and `pool.yaml` is replaced only if that
   succeeds — a bad paste must never destroy the CV she already had. The old
   file is kept as `pool.yaml.bak` for exactly that reason. (Corrected at B5:
   this originally said the upload lands in a temp file first. It does not, and
   should not — a temp file is one more thing to leak, and it would put its own
   name in her error sentences.)
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

- [x] `test_pending_enrichment_count_counts_only_jobs_with_an_ad_text`
- [x] `test_pending_enrichment_count_ignores_jobs_already_answered_at_this_version`
- [x] `test_pending_enrichment_count_is_zero_on_an_empty_store`

`store/enrichment.py` gains `pending_enrichment_count(connection, prompt_version)`.
`jobs_needing_enrichment` already selects exactly the right rows, but it
*fetches* them — the panel needs the number, not 839 rows, on every poll.

### A2 — `RunManager` can start an enrichment pass on its own thread

- [x] `test_start_enrich_runs_the_companion_and_journals_an_enrich_run`
- [x] `test_start_enrich_is_refused_while_an_enrichment_is_already_running`
- [x] `test_start_enrich_is_allowed_while_a_search_is_running`
- [x] `test_cancel_enrich_stops_the_pass_and_keeps_what_it_saved`
- [x] `test_cancel_enrich_does_not_cancel_a_running_search`
- [x] `test_enrich_refusal_names_the_missing_key_and_links_to_settings`
- [x] `test_enrich_refusal_names_the_unreadable_cv_and_links_to_settings`
- [x] `test_an_enrichment_that_dies_leaves_a_sentence_not_a_traceback`

`start_enrich(limit=...)` builds the companion through the existing factory
(so both refusals come for free), starts it, and joins it on a second thread
handle. The thread's body is `companion.start()` → `companion.finish()`; the
companion already does the batching, the journalling and the CSV append.

`limit` is new to the companion: it drains until nothing is left today, so a
bound is the difference between 50 calls and 839. It caps total sent, not per
batch.

- [x] `test_companion_stops_after_the_limit_is_reached`
- [x] `test_companion_without_a_limit_keeps_the_old_behaviour`

### A3 — `POST /run/enrich` and `POST /run/enrich/cancel`

- [x] `test_post_run_enrich_starts_a_pass_and_returns_the_panel`
- [x] `test_post_run_enrich_honours_the_limit_she_typed`
- [x] `test_post_run_enrich_without_a_key_renders_the_refusal_not_a_500`
- [x] `test_post_run_enrich_cancel_stops_it_and_returns_the_panel`
- [x] `test_a_plain_form_post_redirects_back_to_the_enrich_page`

Same shape as `/run/start`: HTMX gets `_progress.html`, a plain post gets a 303.

### A4 — The Enrich page says what it will spend before spending it

- [x] `test_the_enrich_form_names_how_many_jobs_have_no_answer_yet`
- [x] `test_the_enrich_form_says_one_call_per_job_before_she_presses_it`
- [x] `test_the_enrich_form_offers_a_limit_defaulting_to_fifty`
- [x] `test_a_fully_enriched_store_offers_no_button_and_says_so`
- [x] `test_a_live_enrichment_shows_its_count_and_a_cancel_button`
- [x] `test_the_enrich_panel_survives_a_reload_mid_pass`
- [x] `test_an_interrupted_enrichment_says_pressing_it_again_continues`
- [x] `test_the_nav_links_to_the_enrich_page`

The Enrich surface is its own page (`/enrich`), for the reason searching got
one: the two buttons cost different things, and side by side she cannot see
which. Its progress partial is `_enrich_progress.html`, polling `/enrich/progress`
on the same 1-second trigger — the search panel keeps its own so a search and an
enrichment pass can be watched at once without either swapping the other away.

**Named "Explain", not "Enrich", everywhere she can see.** The panel already
said `Explaining jobs in English as they arrive` before this work, and that is
the sentence that says what the button does. `enrich` stays in the URLs, the
run journal and the code, where it is the word the rest of the repo uses.

### A5 — Run it for real and record what it did

Two real passes against her 859-job store on 2026-08-17, both started from the
browser, both spending real free-tier calls.

- [x] **A bounded pass, `limit=10`.** 10 jobs sent, 10 answers landed, 2 m 24 s
      wall (08:03:55 → 08:06:19 UTC), run row `done`, `enriched_count` 10.
      The store went from 20 answers to 30 and `jobs-enriched.csv` came out at
      30 data rows — the CSV and the database agreeing job for job. The panel
      moved 0 → 3 → 5 → 10 while it ran, and the waiting count came down in
      step (837 → 834 → 832 → 827).
- [x] **Cancel mid-pass, `limit=20`.** Pressed after 5 answers. The run row
      ended `interrupted` with `enriched_count` 16, the store held 46 answers,
      and the CSV held exactly the same 46 job ids — nothing lost, nothing
      duplicated. The page then offered the form again above a banner saying 16
      were kept and that pressing Explain again picks up where it left off.
- [x] **Reload mid-pass.** `/enrich/progress` was polled every few seconds
      through both passes; every response carried the current count rather than
      restarting the story, and the whole `/enrich` page reloaded to the same
      state.
- [x] **The count on the button is right.** It says **837**, not the 839
      MASTER_PLAN quotes. Both are honest, and 837 is the useful one: 859 jobs,
      **857** of which have ad text, 20 already answered. Two postings carry no
      text at all, and a pass can never explain those — the queue query has
      always excluded them, so the naive `859 − 20` overstates what a pass can
      do by exactly those two.

**One defect, found only by using it.** Cancel stops the pass *between* batches,
so on her real store the press took ~90 seconds to take effect — and for all of
that time the panel went on saying `Explaining jobs in English`, with the Cancel
button still sitting there. Nothing was wrong underneath; it just looked like
the press had been ignored, which is §10's rule broken from the other side. The
panel now says `Stopping — N jobs explained so far`, drops the Cancel button,
and explains that the jobs already sent are still coming back. Held by
`test_cancel_is_acknowledged_while_the_sent_jobs_are_still_landing`.

**One thing worth knowing about the answers.** The pass logged
`german_level 'B1' was justified by a phrase that is not in the ad — recorded as
'unclear'` for one job. That is the evidence rule from Phase 7 working: the
runner checks the quote against the ad text and downgrades the claim rather than
trusting the model. It appears in the run's `errors` list, not as a failure.

---

## B — Her CV, from the browser

### B1 — The template is downloadable

- [x] `test_get_pool_template_serves_the_file_as_an_attachment`
- [x] `test_the_template_download_is_utf8_and_keeps_its_umlauts`

`pool.template.yaml` ships in the repo root today. It is served from
`/settings/cv/template` so she never has to find it on disk.

### B2 — An upload is validated before it replaces anything

- [x] `test_a_valid_upload_is_written_to_pool_yaml`
- [x] `test_a_valid_upload_keeps_the_previous_file_as_a_backup`
- [x] `test_an_invalid_upload_leaves_the_existing_pool_yaml_untouched`
- [x] `test_an_invalid_upload_shows_the_profile_error_sentence`
- [x] `test_an_upload_that_is_not_yaml_at_all_is_refused_readably`
- [x] `test_an_empty_upload_is_refused_readably`
- [x] `test_the_upload_is_never_logged` (her name and address are in it)

### B3 — The Settings page shows whether a CV is there, and what it says

- [x] `test_settings_says_no_cv_yet_and_offers_the_template`
- [x] `test_settings_summarises_the_cv_it_found`
- [x] `test_settings_names_the_field_and_line_when_the_cv_will_not_parse`
- [x] `test_settings_never_renders_her_address_or_phone_number`

The summary is the one `jobfinder profile validate` prints — name withheld:
languages, years of experience, education, skills count. Enough to recognise
that the right file landed, nothing that needs to be on a screen someone else
might see.

### B4 — Role suggestions can be asked for from the browser

- [x] `test_suggest_roles_button_appears_once_a_cv_is_present`
- [x] `test_post_suggest_roles_stores_and_renders_the_titles`
- [x] `test_suggest_roles_without_a_key_refuses_with_a_link_not_a_500`
- [x] `test_stored_suggestions_are_shown_without_spending_a_call`
- [x] `test_a_suggested_role_links_into_the_search_form_as_a_keyword`

### B5 — Run it for real

Against her actual `pool.yaml` on 2026-08-17, with a byte-exact copy kept aside
first so nothing here could cost her the file.

- [x] **The summary matches the CLI, field for field.** `jobfinder profile
      validate` prints Persian (Native proficiency), English (Fluent), German
      (Basic); Engineering & Simulation 11, General PC & Office 9,
      Sustainability & Environment 7; 3.4 years. The Settings page shows exactly
      those, plus `4 roles`.
- [x] **Nothing identifying reaches the page.** Her email and her location are
      both in `pool.yaml` and neither appears in the rendered HTML; checked by
      searching the response for each value read straight out of the file.
- [x] **Upload round trip, byte for byte.** Uploading her own file back through
      the browser left `pool.yaml` byte-identical to the copy taken beforehand,
      and `pool.yaml.bak` byte-identical to it as well.
- [x] **A broken upload cost her nothing.** A file with only a name in it was
      refused with `pool.yaml: 'basics' … is missing 'email', 'location'.
      Required fields: name, email, location.` and the line "Your previous CV is
      untouched" — and her CV was still byte-identical afterwards.
- [x] **Role suggestions, one real call.** Ten roles came back, each with a
      German title, an English gloss and a reason, and each linking to
      `/search?keywords=…`; following one put `Werkstudent Umwelttechnik` into
      the search form's keyword field. They are stored, so the page re-renders
      them without spending anything.
- [x] **Fit scores are on the list.** 46 of 46 stored answers carry one, and the
      list sorted by fit leads with 88, 70, 58, 58, 55.

**One defect, and it was the CV file itself.** The first round trip came back
*not* byte-identical: `write_text` translates newlines on Windows, so her CRLF
file was written back with every line ending turned into `\r\r\n` — 258 of them
— and the next upload would have doubled them again. The backup had the same
disease in reverse (an LF file came back CRLF). Both now go through
`write_bytes`, held by `test_a_windows_file_is_written_back_unchanged`,
`test_a_unix_file_is_written_back_unchanged_too` and a parametrised
`test_the_backup_is_a_faithful_copy_of_what_it_replaced`. This is the
"Windows reality" row of the cross-cutting table, which is in the plan precisely
because it is the failure nobody notices until the file is already wrong.

**Two layout defects, found in the browser rather than in the HTML.** The
`CV in place` badge was being wrapped down the right-hand edge by her long CV
headline, and each suggested role ran its reason straight on from its English
gloss as one paragraph. Both were CSS: the status cell no longer wraps, a
sentence cell opts back in with `.wrap`, and `.meta` inside a settings row is a
block. The row's action is now an explicit `Search for this` link rather than a
title that happened to be clickable.

**Decision 4 in this file was written wrong and the code does better.** It says
the upload "lands in a temp file"; it does not. `parse_profile` validates the
text before anything touches the disk, so there is no temporary file to leak or
clean up, and the error sentences still name `pool.yaml` rather than whatever
the upload arrived as.

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
