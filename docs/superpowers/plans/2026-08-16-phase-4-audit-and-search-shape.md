---
title: Phase 4 audit — what was verified, what was wrong, what changed
date: 2026-08-16
type: audit
status: done
---

# Phase 4 audit

Phase 4 was marked done on 2026-08-16 with every checklist and "done when" box
ticked. This is the re-check of that claim: what was verified independently,
the one defect it found, and the decisions taken in response.

Source of truth remains `docs/MASTER_PLAN.md` § Phase 4, §8 (etiquette) and
§9 (resume).

## What was verified, and how

| Claim | How it was checked | Result |
|---|---|---|
| The offline suite passes | `pytest` | 193 passed, 5 deselected |
| The live contract holds | `pytest -m live` | 4 passed — endpoint answers, `X-API-Key` still accepted |
| Lint and format are clean | `ruff check` / `ruff format --check` | clean |
| Every checklist test exists | each name from the MASTER_PLAN checklist grepped in `tests/` | all present; 6 live under different names (see below) |
| A real run writes `jobs-init.csv` | the `runs` journal plus a fresh `jobfinder search` | run recorded `done`, CSV written |
| A second run adds 0 rows | re-ran `jobfinder search`, compared the store | 42 jobs before and after, `new_count = 0` |
| `last_seen_at` moves, `first_seen_at` does not | queried both spans around the re-run | `last_seen_at` 09:02:52 → 09:07:29, `first_seen_at` unchanged |
| The CSV survives Excel and Windows | read the raw bytes | BOM present, CRLF only, no blank rows, 41 of 42 rows carry umlauts intact |
| A killed run loses nothing | the `runs` journal from the original kill test | row marked `interrupted` with 7 found, rows still in the store |

Six checklist names did not match the plan text literally, because the tests
are nested in classes that already supply the context — for example
`TestDedupe::test_same_job_on_two_sources_shares_the_dedupe_key` for the
plan's `test_dedupe_key_matches_same_job_from_two_sources`. The coverage is
real; only the names differ. The MASTER_PLAN checklist keeps the descriptive
names on purpose, so no test was renamed to match it.

## The defect: employment types were intersected, not offered as alternatives

`build_queries` treated `werkstudent` and `internship` as modifiers stamped
onto every query it built, because those two types have no `arbeitszeit` code
of their own and have to travel in the `was` search term. The result was that
her default search — werkstudent, minijob and part-time across three cities —
sent `was=Werkstudent` on the minijob and part-time queries too.

That asks the API for a Werkstudent job that is *also* a minijob, rather than
for either kind of job. Measured live on 2026-08-16:

| Query | `maxErgebnisse` |
|---|---|
| Ingolstadt, `arbeitszeit=mj`, `was=Werkstudent` | 1 |
| Ingolstadt, `arbeitszeit=mj` | 116 |
| Neuburg an der Donau, `arbeitszeit=mj` | 115 |

All 42 jobs a default run had stored were Werkstudent postings. Not one
Reinigungskraft, Warenverräumer, Aushilfe or Küchenhilfe — precisely the work
MASTER_PLAN names as the reason the Bundesagentur was built first.

The suite did not catch this because the test that covered the combination,
`test_keyword_and_type_keyword_combine`, asserted the intersecting behaviour
as if it were correct. A passing suite described the bug accurately.

## Decision 1 — employment types are alternatives

Each employment type now builds its own query. A type the API can filter
carries only its `arbeitszeit` code and no search term; `werkstudent` and
`internship`, which have no code, carry only their `was` term. Her own
keywords still combine with the type word, and a keyword that already says
"Werkstudent" is not doubled.

Her default search therefore sends nine queries instead of six — three cities
× (`was=Werkstudent`, `arbeitszeit=mj`, `arbeitszeit=tz`). Overlap between
them costs nothing: postings upsert under their `job_id`.

Rejected alternative: keeping one query per city and filtering the employment
type client-side. It would need the unfiltered result set for every city,
which is far more requests for the same answer, and §8 makes request count the
scarce resource.

## Decision 2 — the request budget is raised, and a search continues itself

Splitting the types multiplied the work a default search does. At the old
budget of 200 requests a run stopped a fraction of the way through and left
her to type `--resume` by hand, several times, to finish one search — the
budget is per process and in memory, so nothing restarted on its own.

Two changes, deliberately paired:

- `request_budget` is now **800 per leg** (`config.py`), enough to get through
  a city's postings at the polite 3–4 s spacing §8 requires.
- `run_search_until_done` runs legs until the search is finished, building the
  adapters — and therefore the HTTP client, and therefore the budget — fresh
  for each leg, re-entering at the stored cursor.

The pairing is the point. Auto-continue without a bound would turn the budget
into no limit at all, which is exactly what §8 forbids, so the loop stops on
any of four conditions:

| Condition | Why it stops |
|---|---|
| The leg finished the search | Nothing left to do |
| The leg stored nothing | A budget spent without progress would loop forever |
| Her Ctrl-C, or any source error | She stopped it, or a host is refusing — §8 says do not retry into it |
| `max_search_legs` reached (default 6) | The backstop a bug cannot argue with |

Only a spent budget continues automatically. `SearchSummary.budget_exhausted`
exists to keep that distinction explicit rather than matching on error text,
and `SearchSummary.legs` reports how many rounds a search needed so the
summary can say so.

Each guard was checked by breaking it deliberately and confirming a test
failed — the three loop tests pass against the implementation, so watching
them fail first required removing the guard they protect.

## What changed

| Commit | Change |
|---|---|
| `864ba3e` | `fix: employment types are alternatives, not one stacked filter` |
| `fb43eb6` | `feat: continue a search automatically when a leg's budget runs out` |
| `4f11398` | `feat: raise the request budget and run searches unattended` |

209 tests pass, `ruff` and `ruff format` clean. Verified live afterwards: a
scoped run (`--cities Ingolstadt --types minijob --keywords Reinigungskraft`)
stored 8 real minijob postings with full descriptions in 29 s, run recorded
`done`.

## Still open

Not defects in what Phase 4 promised, but known and deliberately left:

- **A cold run is silent.** `run_search` takes an `on_page` callback for
  exactly this and the CLI passes nothing, so a run with no warm cache prints
  nothing until it finishes — minutes, given a detail fetch per posting at
  3–4 s spacing. §10's panic rule wants counts on screen while it works. The
  hook exists; only the CLI side is missing.
- **`--resume` with nothing to resume says "0 jobs found"** instead of saying
  there was nothing to continue. The stored cursor from a finished run points
  past the last query, so the run is correct and the sentence is not.
- **A detail fetch per posting dominates the cost of a search.** Roughly 51
  requests per page of 50: one search call and one detail call each. Phase 7
  reads those descriptions anyway, so moving the fetch into enrichment would
  cut a search to a few dozen requests. Deferred rather than decided — it
  changes what `has_description` means at the end of Phase 4.

## For Phase 5

Two facts from this audit apply to every source that follows:

- Employment types are alternatives at the query layer. Any new adapter maps
  them the same way — one query per type it can filter, and the rest as search
  terms, never stacked into one request.
- A source's own budget is spent per leg, not per search. `run_search_until_done`
  rebuilds every adapter between legs, so an adapter must hold no state that
  has to survive its client.
