---
title: "Phase 10 — Handover: one file she double-clicks"
date: 2026-08-17
type: phase-plan
status: in progress
master-plan: docs/MASTER_PLAN.md#phase-10--handover-one-file-she-double-clicks
---

# Phase 10 task plan

Map: [MASTER_PLAN § Phase 10](../../MASTER_PLAN.md#phase-10--handover-one-file-she-double-clicks).
Test-first, one checklist item per commit, pushed as it lands.

**What this phase is for.** Everything before it runs on the machine it was
written on. This one moves it to hers: no Python, no terminal, no virtualenv, no
`git pull`. A tool that only runs on the developer's laptop has not been
delivered, and the distance between "works here" and "she can use it" is this
phase.

Branched from `feat/phase-9-call-list` rather than `main`, because the call-list
is part of what ships and is not merged yet.

## What already exists (do not rebuild)

Counted and read before planning, because most of the Phase 10 deliverable list
was quietly finished by Phases 8 and 9:

- **The Search button exists.** `POST /run/start`, its own thread, a progress
  panel that survives a reload, and a Cancel — Phase 8. The same is true of
  Explain (`/run/enrich`) and the call-list (`/run/contacts`). The "normal
  session is open app → Search → wait → read" deliverable is shipped; what is
  missing is everything *around* it.
- **Refusals are already sentences with links.** `web/runs.py` `StartRefused`
  answers a missing key with "add a free key in Settings" and an unreadable CV
  with a link to the same page.
- **The Settings page already lists every provider and its signup URL**, read
  from `llmpool.missing_keys(catalog, env={})`, with a tick against the ones
  that have a key.
- **The CV can be uploaded, validated and backed up** — the "wanted next" work,
  including the `write_bytes` line-ending fix and `data/pool.yaml.bak`.
- **The app is already offline-capable.** HTMX and both fonts are local files
  under `web/static/vendor/`; `web/app.py` says why in its docstring.
- **`Settings.load` already reads `config.yaml`** and rejects unknown keys with
  a sentence naming the valid ones.

## What the machine says, measured 2026-08-17

- The suite is **970 tests in 71 s**, offline, no warnings.
- `data/` holds **66 MB**, and 63 MB of that is `http-cache/` (785 files) plus
  `http-recon/`. The database is **3.07 MB**, the three CSVs together **0.49 MB**.
  A naive "back up `data/`" would copy 66 MB five times over for 3.5 MB of
  irreplaceable state. **The backup takes what cannot be re-fetched and leaves
  the caches**, which is also what makes it fast enough to run before every run.
- PyInstaller is **not installed** in `.venv` and is not a runtime dependency of
  the app. It belongs in the dev extras and in the build script, never in
  `requirements.txt`.

## Decisions

1. **The wizard's marker is `config.yaml`, not a flag file.** "Has she set this
   up?" is answered by the file the setup writes, so there is one source of
   truth and deleting it re-runs the wizard — which is exactly the third
   done-when ("deleting `data/` and starting again works"). A separate
   `.setup_done` would be a second thing that can disagree with the first.
2. **Cities and employment types move into `Settings`.** They are hard-coded in
   `cli.py` today and read from there by the web app in four places. The wizard
   has to write them somewhere, and `config.yaml` is the file the app already
   reads. `DEFAULT_CITIES`/`DEFAULT_TYPES` stay as the defaults of the new
   fields, so nothing that imports them breaks.
3. **The key is written to `.env` and into this process's environment.** Writing
   the file alone would mean "restart the app for it to work", which is a
   sentence she should never have to read. `.env` is already gitignored and
   already what `Settings.load` reads on the next start.
4. **A pasted key is never echoed.** Not into the page, not into a log line, not
   into an error message. The wizard confirms *which provider* now has a key and
   says nothing else — the same rule the CV upload follows.
5. **The port is chosen, not assumed.** 8000 is a popular port and a second
   JobFinder window is the likeliest thing to be holding it. The launcher asks
   the operating system for the first free port from 8000 upwards and prints the
   one it got, because a browser opened at the wrong port is indistinguishable
   from a broken app.
6. **`sys.frozen` decides where `data/` lives**, and nothing else in the codebase
   learns about the exe. One function answers "what is the install root", the
   launcher passes its answer to `Settings`, and every other module goes on
   taking a `project_root` it does not question.
7. **The build is a spec file plus one importable module.** The lists PyInstaller
   needs (bundled templates, static files, hidden imports) live in
   `jobfinder/packaging.py` where a test can read them; `jobfinder.spec` is a
   thin file that imports them. A spec file cannot be unit-tested, so as little
   as possible lives in it.
8. **The updater replaces the exe and touches nothing else.** It keeps the
   previous exe beside the new one so a bad build is one rename away from being
   undone, and it refuses to run if the thing it was handed is not an exe. Her
   data, her CV and her keys are never inputs to it.

---

## T1 — A free port, chosen rather than assumed

- [x] `test_the_preferred_port_is_used_when_it_is_free`
- [x] `test_the_next_port_is_chosen_when_the_preferred_one_is_busy`
- [x] `test_a_wall_of_busy_ports_is_refused_with_a_sentence`

`launch.py` `choose_port(preferred, host)` binds to find out rather than asking
a list — the only way to know a port is free is to take it.

## T2 — Where the data lives when there is no project root

- [x] `test_the_install_root_is_the_working_directory_when_running_from_source`
- [x] `test_the_install_root_is_beside_the_exe_when_frozen`
- [x] `test_data_dir_resolves_next_to_the_exe_when_frozen`

`launch.py` `install_root()` reads `sys.frozen` and `sys.executable`. Nothing
else in the codebase learns that an exe exists (decision 6).

## T3 — A backup before every run, five kept

- [x] `test_a_backup_copies_the_database_and_the_csvs`
- [x] `test_a_backup_leaves_the_http_cache_alone`
- [x] `test_backup_rotation_keeps_five_and_deletes_the_sixth`
- [x] `test_a_first_run_with_nothing_to_copy_is_not_an_error`
- [x] `test_a_backup_that_cannot_be_written_never_fails_the_run`
- [x] `test_a_search_started_from_the_browser_backs_up_first` +
      `test_an_explanation_pass_backs_up_first_too` +
      `test_a_call_list_run_backs_up_first_too`
- [x] `test_a_search_from_the_command_line_backs_up_too` +
      `test_an_explanation_pass_from_the_command_line_backs_up_too` +
      `test_a_call_list_from_the_command_line_backs_up_too`
- [x] `test_a_dry_run_backs_up_nothing_because_it_changes_nothing`

`backup.py` `back_up_data(settings)` → `data/backups/<UTC stamp>/`. It runs at
the start of every run started from the browser and from the CLI. The measured
reason for choosing files rather than the directory is above: 3.5 MB of state
under 63 MB of re-fetchable cache.

## T4 — Export everything, one click

- [x] `test_export_everything_writes_all_three_csvs`
- [x] `test_export_everything_reports_what_it_wrote`
- [x] `test_exporting_an_empty_store_writes_headers_and_says_so`
- [x] `test_the_settings_page_offers_the_export`
- [x] `test_the_export_names_the_folder_she_can_open`
- [x] `test_the_export_includes_the_call_list`
- [x] `test_a_job_stored_after_the_last_run_reaches_the_csv`

`POST /settings/export` calls the three exporters that already exist
(`export_jobs`, `export_jobs_enriched`, `export_contacts`) and renders the row
counts and the paths. No new writer, no zip: the CSVs are what she opens in
Excel, and where they are is part of the answer.

## T5 — Cities and types belong to `Settings`

- [x] `test_the_default_cities_are_the_three_she_searches` +
      `test_the_default_types_are_the_three_she_can_take`
- [x] `test_config_yaml_can_override_the_cities`
- [x] `test_config_yaml_can_override_the_employment_types`
- [x] `test_the_search_form_offers_the_configured_cities`
- [x] `test_a_search_defaults_to_the_configured_cities`

The wizard needs somewhere to write her answers, and `config.yaml` is the file
`Settings.load` already reads (decision 2).

## T6 — The first-run wizard

- [x] `test_first_run_wizard_appears_when_no_config_exists`
- [x] `test_wizard_is_skipped_on_second_start`
- [x] `test_every_page_leads_to_the_wizard_until_it_is_finished`
- [x] `test_the_wizard_names_each_provider_and_its_signup_link`
- [x] `test_wizard_writes_env_and_config_and_never_logs_the_key`
- [x] `test_the_key_she_pasted_is_never_rendered_back`
- [x] `test_a_pasted_key_works_without_restarting_the_app`
- [x] `test_the_wizard_writes_the_cities_and_types_she_picked`
- [x] `test_the_wizard_can_be_finished_without_a_key`
- [x] `test_finishing_the_wizard_lands_her_on_the_search_page`
- [x] `test_an_unknown_city_is_refused_with_the_names_that_work`
- [x] `test_the_static_files_are_served_during_the_wizard`
- [x] `test_the_wizard_keeps_a_key_that_was_already_in_the_env_file`

`/setup`, GET and POST. The redirect is middleware rather than a check in each
route: a page she can reach before setting up is a page that has to explain
itself, and there are eleven of them.

## T7 — The errors she might actually hit

- [x] `test_no_internet_produces_a_readable_page_not_a_traceback`
- [x] `test_an_unexpected_failure_renders_the_error_page_not_a_stack_trace`
- [x] `test_the_error_page_says_what_to_do_next`
- [x] `test_a_page_that_does_not_exist_is_a_sentence_too`
- [x] `test_missing_api_key_renders_a_sentence_and_a_link_not_a_traceback` —
      Phase 8's, and it is the "missing keys names the signup links" box in
      MASTER_PLAN: the Settings page lists every provider with its link

The refusals that already exist (no key, no CV) are Phase 8's. What is missing
is the last line of defence: an exception nobody predicted must still reach her
as a page with a next step on it.

## T8 — The launcher, and the console window she sees

- [ ] `test_the_launcher_says_which_address_to_open`
- [ ] `test_the_launcher_opens_the_browser_at_the_port_it_got`
- [ ] `test_the_launcher_says_how_to_stop_it`
- [ ] `test_the_launcher_creates_the_data_directory_when_it_is_missing`
- [ ] `test_the_launcher_says_something_readable_when_the_port_wall_is_hit`
- [ ] `test_healthcheck_answers_ok`

`launch.py` `main()` is what `JobFinder.exe` runs and what `jobfinder serve`
calls, so the thing she double-clicks is the thing that is tested. `/healthz`
exists for the build smoke test — a started server that answers is the only
proof a build works.

## T9 — The build

- [ ] `test_the_bundle_includes_every_template`
- [ ] `test_the_bundle_includes_the_static_files_the_app_serves_offline`
- [ ] `test_the_bundle_names_the_hidden_imports_uvicorn_needs`
- [ ] `test_the_spec_file_reads_its_lists_from_the_packaging_module`
- [ ] `tests/live/test_built_exe.py` — the built exe starts and answers `/healthz`

`packaging.py` holds the lists; `jobfinder.spec` imports them;
`scripts/build_exe.py` runs PyInstaller with the spec and prints where the exe
landed.

## T10 — The update path

- [ ] `test_an_update_replaces_the_exe`
- [ ] `test_an_update_keeps_the_previous_exe_as_a_rollback`
- [ ] `test_an_update_leaves_the_data_directory_untouched`
- [ ] `test_an_update_refuses_something_that_is_not_an_exe`
- [ ] `test_an_update_refuses_to_overwrite_a_running_exe_readably`

`packaging.py` `apply_update(new_exe, install_dir)`, with `scripts/update.ps1`
as the two-line wrapper she or I actually run.

## T11 — `docs/HER_README.md`

- [ ] `test_her_readme_names_every_page_in_the_nav`
- [ ] `test_her_readme_has_no_developer_instructions_in_it`

One page, English, screenshots of the real app. The guard tests exist because a
README that stops matching the app is worse than none — the same reason
`test_plan_checkboxes.py` exists.

## T12 — Run it for real

- [ ] Build the exe and start it from a directory that has never held a venv
- [ ] Delete `config.yaml` and watch the wizard come back
- [ ] Complete a search from the built exe, with the browser it opened itself
- [ ] Apply an update over a running install and confirm `data/` survived
- [ ] Write the measured numbers into this file

## Definition of done

- [ ] Every behaviour above had a failing test first, and the failure was watched
- [ ] `pytest` green, no network, no warnings
- [ ] `ruff check` and `ruff format --check` clean
- [ ] MASTER_PLAN's Phase 10 boxes ticked against what was measured
- [ ] Atomic commits on `feat/phase-10-handover`, pushed as they land
