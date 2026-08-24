---
title: Germany-wide towns, a typed filter, and full-time work
date: 2026-08-24
type: task-plan
status: in progress
---

# Germany-wide towns, a typed filter, and full-time work

Asked for on 2026-08-24, after the app had been used: the same tool should serve
someone looking for a **full-time job anywhere in Germany**, not only a student
looking for a Werkstudent contract within reach of Neuburg. Two things follow
from that, and one thing falls out of it.

1. **Many more towns.** Thirteen Bavarian towns is a shortlist for one person's
   commute, not a country. The list becomes every German town of any size worth
   naming.
2. **A town is found by typing the first letters of it.** Thirteen checkboxes
   were a list. A thousand are not, so the picker becomes: type two or three
   letters, see the towns that match, tick the one you meant.
3. **Full-time is a kind of work you tick**, alongside Werkstudent, minijob,
   part-time and internship — not a word you have to spell into a text box.

Everything below is test-first. Each task is one commit, ticked here and in
`docs/MASTER_PLAN.md` the moment it is green, and pushed.

## What must stay true

- **A town is never typed into the search.** A typo must be impossible to submit,
  which is why the filter box only ever *filters*; what the search receives is
  still a ticked checkbox with a canonical name.
- **The names are German.** Job sites are searched by town name, so the list
  says `München` and `Nürnberg`, never `Munich` or `Nuremberg`. The dataset's
  English exonyms are corrected by hand and asserted by a test.
- **A guessed Kleinanzeigen location id is worse than none.** Their location ids
  were recorded by hand for thirteen towns and cannot be derived for a thousand.
  Kleinanzeigen therefore searches the towns it knows and says which ones it
  skipped — it does not guess, and it no longer refuses the whole run.
- **The offline suite stays offline.** The city list is generated once, by a
  script, and committed as source. Nothing downloads a dataset at runtime.

## Task 1 — the town list becomes a country

`scripts/build_city_list.py` reads the GeoNames extract shipped by
`geonamescache` (a build-time dependency, in the `dev` extras, never imported by
the app) and writes `src/jobfinder/city_data.py`: every German town above 15,000
inhabitants, with its coordinates, its population and its state. Roughly 1,100
entries. The generated file is committed, so the offline suite and the frozen
exe both read plain Python and nothing is fetched at runtime.

The thirteen towns already in `cities.py` keep their exact spelling, their
coordinates and their Kleinanzeigen ids: `CITY_COORDS` becomes the generated
table, `KLEINANZEIGEN_LOCATIONS` stays hand-recorded and shrinks to a subset.

Test-first checklist:

- [ ] `test_the_generated_list_covers_every_german_state` — sixteen states present
- [ ] `test_the_thirteen_original_towns_survived_unchanged` — name, latitude and
      longitude identical to what Phase 4 recorded
- [ ] `test_the_big_cities_are_named_in_german` — `München`, `Nürnberg`, `Köln`,
      `Hannover`, `Braunschweig`, and no `Munich`/`Nuremberg`/`Cologne`
- [ ] `test_every_city_has_plausible_coordinates` — inside Germany's bounding box
      (replaces the Bavarian assertion)
- [ ] `test_the_list_is_large_enough_to_be_a_country` — more than 900 towns

## Task 2 — finding a town by the first letters of it

`jobfinder.cities.search_cities(query, limit)`: the towns whose name starts with
what was typed first, then the ones that merely contain it, each group by
population so the town someone means is the one at the top. Umlauts fold the way
`resolve_city` already folds them, so `mun` finds `München`.

`resolve_city`'s error can no longer list a thousand valid names; it names the
closest few instead.

Test-first checklist:

- [ ] `test_two_letters_are_enough_to_find_a_town`
- [ ] `test_the_biggest_match_comes_first` — `ber` puts Berlin above Bernau
- [ ] `test_a_prefix_beats_a_substring` — `burg` puts Burg above Augsburg
- [ ] `test_the_umlaut_free_spelling_finds_the_town` — `muenchen` and `munchen`
- [ ] `test_no_match_is_an_empty_list_not_an_error`
- [ ] `test_an_unknown_town_is_refused_with_the_nearest_names`

## Task 3 — Kleinanzeigen skips what it cannot reach

A town with no recorded location id is skipped, and named in the run's own
report. Refusing the entire source — today's behaviour — would mean one town
outside Bavaria silently costs every other town its Kleinanzeigen results.
A run where *no* town is mapped still refuses, because that is a search that
cannot do anything.

Test-first checklist:

- [ ] `test_an_unmapped_town_is_skipped_not_refused` — mapped towns still queried
- [ ] `test_the_skipped_towns_are_reported` — names available to the runner
- [ ] `test_a_run_with_no_mapped_town_at_all_still_refuses`

## Task 4 — the picker: type, see matches, tick one

One partial, `_town_picker.html`, used by the Search page, the Call page and the
first-run wizard. It holds:

- the chosen towns, as ticked checkboxes named `cities` — unchanged, so the
  forms that read them are unchanged;
- a filter box that is **not** part of the submitted search;
- the matches for what has been typed, as unticked checkboxes.

Two routes serve it, both HTMX, no hand-written JavaScript beyond one attribute
that stops Enter from submitting the form early:

- `GET /cities/options` — the matches for `q`, the current selection included so
  a town already chosen is not offered twice;
- `POST /cities/toggle` — ticking or unticking anything re-renders the whole
  picker, which is what keeps a chosen town from vanishing with the next
  keystroke.

Test-first checklist:

- [ ] `test_the_chosen_towns_are_ticked_when_the_page_opens`
- [ ] `test_typing_two_letters_offers_matching_towns`
- [ ] `test_the_filter_box_is_not_submitted_as_a_town`
- [ ] `test_ticking_a_match_keeps_it_after_the_next_keystroke`
- [ ] `test_unticking_a_chosen_town_removes_it`
- [ ] `test_the_page_does_not_render_a_thousand_checkboxes`
- [ ] `test_the_towns_she_ticks_are_still_the_ones_searched` (unchanged rule)
- [ ] the same three pages: Search, Call, and the wizard

## Task 5 — full-time is a tick, not a spelling

`Job types` stops being a text box on the Search page and in the wizard, and
becomes five checkboxes: Werkstudent, minijob, part-time, **full-time**,
internship. The wizard's copy stops reading as though the user were a student.
`config.yaml` is unchanged — the same list of words, now produced by ticking.

Test-first checklist:

- [ ] `test_full_time_is_offered_as_a_checkbox`
- [ ] `test_the_kinds_of_work_are_not_a_text_box`
- [ ] `test_the_kinds_ticked_are_the_kinds_searched`
- [ ] `test_the_wizard_writes_the_kinds_ticked`
- [ ] `test_ticking_nothing_falls_back_to_the_configured_kinds`

## Task 6 — "distance" means distance from where you live

`HOME_CITY` is a constant resolved at import: Neuburg an der Donau. For anyone
else it makes the distance column and the distance sort wrong. It becomes the
first town in `settings.cities`, resolved per request, with Neuburg surviving
only as the default in `Settings`.

Test-first checklist:

- [ ] `test_distance_is_measured_from_the_first_configured_town`
- [ ] `test_a_store_with_no_configured_town_still_sorts` (falls back, never raises)

## Task 7 — the handover

- [ ] `docs/MASTER_PLAN.md` — a Wanted-next entry recording what changed and why
- [ ] `docs/HER_README.md` — the town picker screenshot and its sentence
- [ ] `pytest`, `ruff check`, `ruff format --check` all green
- [ ] `python scripts/build_exe.py` — a fresh `dist/JobFinder.exe`
- [ ] `pytest -m live tests/live/test_built_exe.py` — the built exe answers
- [ ] `python scripts/llm_smoke.py` — the real provider keys still work
- [ ] a real search in the built exe, in a town outside Bavaria
