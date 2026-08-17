---
title: "Phase 9 — General work: a call-list, not a job board"
date: 2026-08-17
type: phase-plan
status: in progress
master-plan: docs/MASTER_PLAN.md#phase-9--general-work-a-call-list-not-a-job-board
---

# Phase 9 task plan

Map: [MASTER_PLAN § Phase 9](../../MASTER_PLAN.md#phase-9--general-work-a-call-list-not-a-job-board).
The turn-by-turn version: test-first, one checklist item per commit, pushed as
it lands.

**What this phase is for.** Every other source in this app finds places that
*posted* something. This one finds the far larger number of restaurants, cafés,
bakeries and hotel kitchens that never post at all and hire when someone calls
or walks in. The product is a contact list and the nerve to use it — not a feed.

## What Overpass actually answers, measured 2026-08-17 from this machine

Probed before a line of this was written, because the whole phase rests on it.
Query shape: `nwr(around:6000, <city centre>)["<key>"="<value>"]`, one request
per tag, `out tags center`.

**Neuburg an der Donau, 6 km:**

| | count |
|---|---|
| unique places | **118** |
| with a name | 110 |
| **with a phone or an email** | **34** |
| phone | 32 |
| email | 14 |
| website but neither | 10 |

By kind: restaurant 35, cafe 21, fast_food 12, bakery 11, bar 10, hotel 8,
butcher 8, pub 5.

Five facts that change the design, none of which was in MASTER_PLAN:

1. **`amenity=hotel` returns nothing. Hotels are `tourism=hotel`** — 9 of them
   in Neuburg. MASTER_PLAN's tag list would have silently missed every hotel
   kitchen, which is one of the best fits in the whole list for someone with
   little German.
2. **`amenity=pub` is worth having** (5 more places) and is not in the plan's
   list either.
3. **18 of the 118 are `way`s, not `node`s.** A `node`-only query — the obvious
   one — loses 15 % of the list, because a POI mapped as a building is a way.
   `nwr` is required.
4. **The canonical endpoint is not usable right now.**
   `overpass-api.de/api/interpreter` returned `504` on **every** attempt over
   four minutes, while its own announced backends answered the same query in
   under a second: `gall.openstreetmap.de`, `z.overpass-api.de`,
   `lz4.overpass-api.de`. `api/status` reported "2 slots available", so this is
   not us being rate-limited — the round-robin front door is simply broken.
   A single hard-coded host would make this phase look permanently dead.
5. **429 and 504 are the normal case, not the exception.** Firing nine tag
   queries back to back, six of them failed at least once and one
   (`shop=supermarket`) failed four times across three endpoints. This is a
   donated public server: it needs real spacing, real backoff, and a failure
   that costs one tag rather than the run.

Phone numbers arrive in at least two shapes — `'+49 8431 2078'` and
`'+4984312079'` — so E.164 normalisation is not optional if she is going to tap
one on a phone.

## What already exists (do not rebuild)

- **The `contacts` table**, created in schema v1 and unused since: `contact_id`,
  `name`, `kind`, `city`, `street`, `phone`, `email`, `website`,
  `back_of_house_score`, `osm_id`, `first_seen_at`, `last_contacted_at`,
  `outcome`, `notes`. Phase 9 was anticipated; the columns are waiting.
- `sources/http.py` `PoliteClient` — per-host spacing, a shared budget, disk
  caching, `Retry-After`, retries, `SourceUnavailable`. **It has `get` and
  `get_json` and no `post`**, and Overpass wants a POST body.
- `cities.py` `resolve_city` / `City.with_radius` — the city centres and radii
  this phase queries around, already verified for the job sources.
- `store/export.py` — the atomic `*.tmp` + `os.replace` CSV pattern and the
  `utf-8-sig`, `newline=""` encoding rule (§5).
- `store/status.py` — the shape her decisions take: validate, upsert, stamp a
  date once and never rewrite it. Contact outcomes follow it exactly.
- `web/` — nav, filters, the `settings-list` row, the empty and error states,
  and the progress panel machinery a contacts run can reuse.
- `llm/` — `Pool`, the content-hash cache, `load_prompt`, and the validator
  contract. §2's rule holds: every call cached and skippable.

## Decisions

1. **One request per tag value per city, spaced, with endpoint fallback.** Not
   one big union query: measured above, the union `504`s while the small ones
   succeed, and a per-tag request means a failed tag costs one kind of place
   instead of the whole city. The adapter carries the list of endpoints from
   fact 4 and moves down it on failure.
2. **`PoliteClient` grows a `post`.** Overpass takes its query as a POST body.
   Everything else about the request — spacing, budget, cache key, retries,
   `Retry-After` — is the same machinery, and reimplementing it beside itself
   would be how one source ends up ignoring §8.
3. **A place with no contact route is not stored.** MASTER_PLAN says excluded,
   and the reason is sharper than tidiness: this list exists to be worked
   through, and a row she cannot act on is a row she has to skip every time she
   opens the page. The 10 website-only places in Neuburg are the exception —
   they get one imprint fetch, and are stored only if it finds an address.
4. **`back_of_house_score` is a small, readable heuristic, not a model call.**
   Kitchens, bakeries and hotels score high; bars and counter-service low. It
   decides row order, and a number she cannot predict is worse than a number
   she can argue with. It is also free, which matters when the LLM budget is
   spent on the things only a model can write.
5. **The German phone script is generated per *kind of place*, not per place.**
   MASTER_PLAN says per-place. Measured against her real list, per-place would
   spend **34 calls in Neuburg alone** to produce 34 scripts differing only in
   a name — and the free-tier rule is the constraint the whole project is built
   around. So: one script per kind (8 kinds), cached, with the place name and
   city substituted at render time. The same for the email draft. If a kind's
   script ever needs to differ per place, that is a per-place call worth making
   then, on evidence.
6. **Nothing is sent.** MASTER_PLAN's out-of-scope line, restated because it is
   load-bearing: the email is a draft she reads, edits and sends from her own
   address. The page offers a `mailto:` and a copy button, and the app never
   holds an outbound mail credential.

---

## T1 — `PoliteClient` can POST

- [x] `test_a_post_sends_its_body_and_returns_the_response`
- [x] `test_a_post_waits_between_requests_to_the_same_host` (fake clock)
- [x] `test_a_post_counts_against_the_same_request_budget`
- [x] `test_two_posts_with_different_bodies_are_cached_separately`
- [x] `test_a_cached_post_is_not_sent_again`
- [x] `test_a_post_honours_retry_after`
- [x] `test_a_post_that_keeps_failing_raises_source_unavailable`

The cache key has to include the body: two Overpass queries go to one URL and
must not answer each other.

## T2 — The Overpass adapter, over a recorded fixture

- [x] `test_the_fixture_parses_places_with_and_without_contact_details`
- [x] `test_a_place_with_no_name_is_skipped`
- [x] `test_a_place_with_no_contact_route_at_all_is_excluded`
- [x] `test_a_place_with_only_a_website_is_kept_for_the_imprint_step`
- [x] `test_both_the_plain_and_the_contact_prefixed_tags_are_read`
- [x] `test_ways_are_parsed_as_well_as_nodes` (18 of her 118)
- [x] `test_hotels_come_from_the_tourism_tag_not_the_amenity_one`
- [x] `test_the_street_and_house_number_become_one_address_line`
- [x] `test_a_contact_id_is_stable_across_runs` (OSM type + id)
- [x] `test_a_place_seen_in_two_tag_queries_appears_once`
- [x] `test_a_failing_tag_costs_that_tag_and_not_the_city`
- [x] `test_a_failing_endpoint_falls_through_to_the_next_one`
- [x] `test_every_request_carries_the_identifying_user_agent`

The fixture is the Neuburg payload recorded on 2026-08-17 — 118 places, real
tags, real gaps. Recorded, never hand-written (§7).

## T3 — Phone numbers she can actually dial

- [x] `test_a_spaced_german_number_becomes_e164`
- [x] `test_an_already_e164_number_is_left_alone`
- [x] `test_a_national_number_gains_the_country_code`
- [x] `test_a_note_in_brackets_is_not_dialled`
- [x] `test_a_second_number_after_a_semicolon_takes_the_first`
- [x] `test_something_that_is_not_a_number_is_dropped_not_mangled`

## T4 — `back_of_house_score`

- [x] `test_a_bakery_and_a_hotel_outrank_a_bar`
- [x] `test_a_restaurant_outranks_counter_service`
- [x] `test_a_cuisine_bonus_is_never_a_requirement`
- [x] `test_a_place_with_an_email_scores_above_an_identical_one_without`
- [x] `test_the_score_is_stable_for_the_same_tags`
- [x] `test_every_kind_the_query_returns_has_a_score`

## T5 — Storing contacts, and her decisions about them

- [x] `test_a_contact_is_stored_with_its_kind_city_and_route`
- [x] `test_re_running_updates_a_contact_rather_than_duplicating_it`
- [x] `test_a_note_survives_a_later_re_run_of_the_source`
- [x] `test_marking_called_stamps_the_day_once_and_never_rewrites_it`
- [x] `test_an_outcome_note_is_saved_and_read_back`
- [x] `test_an_unknown_outcome_is_refused_with_a_sentence`
- [x] `test_marking_no_moves_it_out_of_the_queue`
- [x] `test_a_contact_is_committed_immediately` (§9)

## T6 — `contacts.csv`

- [x] `test_the_columns_are_the_ones_the_contract_names`
- [x] `test_umlauts_and_esszet_survive`
- [x] `test_a_crash_mid_export_leaves_the_previous_file_intact`
- [x] `test_the_export_carries_her_outcome_and_notes`

## T7 — The German phone script and the email draft

- [x] `test_a_script_is_five_lines_of_german_each_with_an_english_gloss`
- [x] `test_a_rendered_script_names_the_place_and_the_city`
- [x] `test_the_prompt_says_she_is_a_student_looking_for_a_minijob`
- [x] `test_a_rendered_email_names_the_place_and_her_availability`
- [x] `test_an_email_has_a_subject_and_a_greeting`
- [x] `test_one_call_per_kind_is_made_not_one_per_place`
- [x] `test_a_second_place_of_the_same_kind_spends_no_call`
- [x] `test_a_refused_kind_is_not_stored`
- [x] `test_a_spent_quota_keeps_the_kinds_already_written`
- [x] `test_only_her_first_name_is_sent`

## T8 — Imprint lookup, for the website-only places

- [x] `test_an_email_is_extracted_from_a_saved_imprint_page`
- [x] `test_the_lookup_is_skipped_when_an_email_already_exists`
- [x] `test_a_site_that_answers_without_an_email_yields_nothing`
- [x] `test_an_obfuscated_at_sign_is_recovered` (`name (at) domain.de`)
- [x] `test_only_one_page_is_fetched_once_it_answers`
- [x] `test_a_site_that_does_not_answer_costs_only_that_place`

## T9 — The Contacts page

- [x] `test_the_page_lists_contacts_best_first`
- [x] `test_the_page_shows_the_phone_the_kind_and_the_street`
- [x] `test_the_page_offers_the_script_for_that_place`
- [x] `test_an_email_place_offers_a_mailto`
- [x] `test_marking_it_survives_a_restart_of_the_app`
- [x] `test_a_marked_place_leaves_the_queue_but_can_be_found_again`
- [x] `test_an_empty_call_list_says_how_to_build_it`
- [x] `test_everything_except_the_script_is_english`
- [x] `test_the_nav_links_to_the_contacts_page`
- [ ] `test_a_contacts_run_starts_from_the_browser_and_narrates`

## T10 — The CLI command, and one live contract test

- [x] `test_the_command_stores_contacts_and_writes_the_csv`
- [x] `test_it_says_what_it_found_per_city`
- [x] `test_a_city_with_no_places_says_so_rather_than_nothing`
- [x] `tests/live/test_overpass_contract.py` — Neuburg still returns places with
      contact details, and the endpoint list still has a working member

## T11 — Run it for real, and record what it did

- [ ] Build the list for Neuburg, Ingolstadt and Munich; record the counts, the
      wall time, and how many places were reachable
- [ ] Confirm ≥ 50 contactable places across the three, ranked
- [ ] Open the page, read one script, and mark one contact "Called"; confirm it
      persists and leaves the queue
- [ ] Confirm `contacts.csv` matches the store row for row

## Definition of done

- [ ] Every behaviour above had a failing test first, and the failure was watched
- [ ] `pytest` green, no network, no warnings
- [ ] `ruff check` and `ruff format --check` clean
- [ ] MASTER_PLAN's Phase 9 boxes ticked against what was measured, and its tag
      list corrected — `tourism=hotel`, not `amenity=hotel`
- [ ] Atomic commits on `feat/phase-9-call-list`, pushed as they land
