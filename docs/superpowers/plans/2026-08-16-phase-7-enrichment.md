---
title: "Phase 7 — Enrichment: German ad in, English answer out"
date: 2026-08-16
type: phase-plan
status: in progress — T1-T9 done, T10 (her real data) next
master-plan: docs/MASTER_PLAN.md#phase-7--enrichment-german-ad-in-english-answer-out
---

# Phase 7 task plan

Map: [MASTER_PLAN §Phase 7](../../MASTER_PLAN.md). This file is the turn-by-turn
version. Test-first, one checklist item per commit, pushed as it lands.

**This is the phase the product exists for.** Everything so far collects German
text she cannot read. After this, she opens a CSV — and soon a page — and knows
what the job is, how much German it needs, whether she can do it, and how to
apply.

## What she is enriching, measured today

Her store holds **674 jobs** after Phase 6: 447 Bundesagentur, 202 Adzuna, 18
Xing, 7 Kleinanzeigen. Three facts about that pile shape this phase:

- **Every row has some text** (674 of 674), median 1 117 characters, longest
  6 124, shortest 50. About 925 000 characters in total — one pass over the
  whole store, at roughly a third of a token per character, is the size of the
  bill her free tier has to cover.
- **236 of those 674 are teaser-length** (≤520 characters): all 202 Adzuna
  rows, 33 Bundesagentur ads that carry only an `externeURL`, and one Xing
  listing. Just over a third of the store cannot support an evidenced answer.
- **386 of 447 BA rows have no `apply_url`** — the application route has to
  come out of the ad text or it does not exist.

So enrichment must produce something useful from a teaser *and* something
evidenced from a full ad, and must never let the first pretend to be the second.

## What already exists (do not rebuild)

- `llm/pool.py` `build_pool(settings, validator)` — one Pool per run, state
  path, `max_wait`, `run_deadline_seconds` from settings.
- `llm/schema.py` `make_validator(spec)` + `FieldRule` — compose field rules
  into the `(answer) -> (ok, reason)` hook llmpool calls. `ROLES_SPEC` is the
  worked example.
- `llm/cache.py` — `cache_key(prompt_version, content_hash, spec_fingerprint)`,
  `LLMCache`, `complete_json_cached`. Content-hash keyed, so a re-ask is free.
- `roles.py` `build_cv_digest(resume)` — her CV as prompt text with the address,
  email and phone stripped, and a test that proves it.
- `tests/fakes.py` `FakePool` — canned answers, records calls, can raise
  `PoolExhausted`.
- `store/db.py` `enrichment` table: `(job_id, prompt_version, answer, enriched_at)`,
  primary key `(job_id, prompt_version)`.

## Decisions

1. **One call per job, not one per field.** German level, duties, requirements,
   fit and application route come back in a single JSON object. Splitting them
   would multiply her quota use by six for no gain in quality.
2. **`german_level` must be evidenced or `unclear`.** §5 forbids a guess: the
   validator rejects any level other than `unclear` that arrives without a
   `german_evidence` phrase. A teaser will usually yield `unclear`, and that is
   the honest answer, not a failure.
3. **English is checked, not hoped for.** `summary_en` and the other `_en`
   fields go through a cheap German-marker test (`und`, `der`, `die`, `für`,
   `mit`, `Sie`…). A model that answers in German is rejected with a reason and
   the pool asks someone else. Heuristic, deliberately: a language detector is
   a dependency this project does not need.
4. **`enrichment` gains `content_hash`** (schema v5). Skip logic is "enriched at
   this `prompt_version` **and** the ad text has not changed since", and without
   the hash on the row that second half cannot be asked. Re-enrichment inserts a
   new row rather than overwriting — §5 says an old answer is never destroyed.
5. **The CSV is appended per result, before the next job is sent.** §9's rule.
   A full sorted re-export runs at the end through the existing atomic writer.
6. **Enrichment runs alongside search** (§9, added in v0.3.0): the store is the
   queue, `jobfinder search --enrich` starts both, `busy_timeout` and one
   connection per thread make it safe. Either command alone is unchanged.
7. **Her quota is the budget that matters.** `llm_budget` bounds a run;
   `PoolExhausted` stops cleanly with what she has and a sentence about
   resuming, never a traceback.

## Tasks

### T1 — this plan doc ✅
Commit: `docs: phase-7 task plan grounded in what her store actually holds`.

### T2 — the answer contract: `ENRICHMENT_SPEC` + validator ✅
`tests/unit/test_llm_schema.py`. The shape from §5 as `FieldRule`s, plus the
two rules that are this project's and not the model's:
- a `german_level` outside `none/A1…C2/unclear` is rejected naming the value;
- any level except `unclear` without a `german_evidence` phrase is rejected;
- an answer whose `summary_en` reads as German is rejected;
- `fit_score` outside 0–100 is rejected; list fields must be lists.
Commit: `feat: the enrichment answer contract, evidence required`.

### T3 — `llm/prompts/enrich.v1.md` ✅
The prompt: her CV digest, the ad's title/company/city/type flags, the full
German text, and the JSON shape demanded field by field. States plainly that
`german_level` must quote the ad or say `unclear`, and that every `_en` field
is English. `tests/unit/test_llm_prompting.py`: the rendered prompt contains
the description and the digest, and never her address, email or phone.
Commit: `feat: the enrichment prompt — one German ad, one English answer`.

### T4 — `enrich/fields.py`: answer → the `jobs-enriched.csv` row ✅
Pure mapping, no I/O. Lists join with `|` (§5: never commas). Every column in
§5's `jobs-enriched.csv` line is produced, in that order, including
`provider_used` and `prompt_version`.
`tests/enrich/test_fields.py`: a fake answer maps onto every column; pipe
fields survive a CSV round trip; a missing optional field becomes empty, not
the string "None".
Commit: `feat: map an enrichment answer onto the CSV contract`.

### T5 — `store/enrichment.py`: save one answer, know what to skip ✅
Schema v5 adds `enrichment.content_hash` **and `enrichment.provider_used`**
through the ALTER path — §5's CSV asks who answered, and llmpool has no
per-call provider attribution, so the runner has to carry it onto the row
itself. Verified against a copy of her real 674-job database.
- `save_enrichment(connection, job_id, prompt_version, content_hash, answer)`
  inserts one row and commits;
- `jobs_needing_enrichment(connection, prompt_version, limit)` returns jobs
  with a description and no row at this version **or** a changed
  `content_hash`;
- a new prompt version leaves the old row in place.
`tests/store/test_enrichment.py`.
Commit: `feat: store an enrichment and know which jobs still need one`.

### T6 — `enrich/runner.py`: the batch, resumable by construction ✅
`run_enrichment(connection, pool, settings, limit)` over `run_batch`:
`on_result` writes the row **and** appends the CSV line before the next answer
lands; a failing item is recorded and the batch continues; `PoolExhausted`
ends the run with counts and a resumable message; the `llm_budget` caps how
many are sent. `tests/enrich/test_runner.py` with `FakePool`:
- kill after 3 of 10 → exactly 3 rows and 3 CSV lines on disk;
- one junk answer does not end the batch and leaves that job unenriched;
- a second run enriches nothing and makes zero calls.
Two things the writing found, both now tested:
- `LLMCache` opened a thread-bound SQLite connection, so every call made from
  a `run_batch` worker failed before reaching a provider. It is now shared
  safely behind one lock.
- The answer cache is keyed on the **whole prompt**, not the ad text. Measured
  on her store: 60 of 674 postings are identical down to the title and company
  and cost one call between them; keying on the text alone would have "saved"
  166 by answering one shop's ad with another shop's answer. `--force` reads
  past the cache, or it would re-save yesterday's answer.

Commit: `feat: enrich in batches, saving each answer as it lands`.

### T7 — `jobfinder enrich [--limit N] [--force]` ✅
Progress in her words (`143 of 400 jobs explained`), the per-run summary, the
final export, and a readable line for a spent quota. `--force` re-enriches at
the current version. `tests/unit/test_cli_enrich.py` with fakes. `llm_workers`
joins Settings (default 4) — the pool paces itself per provider, so more
workers would only mean more of them queueing.
Commit: `feat: jobfinder enrich, narrated and resumable`.

### T8 — `jobfinder search --enrich` ✅
The §9 promise: enrichment as a second worker over the same store while the
search is still writing to it, its own connection, its own narration. Either
command alone must behave exactly as before.
`tests/unit/test_cli_search.py` + `tests/unit/test_search.py`.
Three things the writing found, all now tested:
- A job that fails must be retried on the next **run**, not the next poll two
  seconds later — `EnrichmentRun.failed_job_ids` feeds `run_enrichment(skip=…)`
  so one unanswerable ad cannot eat an evening of her quota.
- The companion reaches the database before the search has created it, so it
  migrates on its own connection.
- `PRAGMA journal_mode = WAL` is refused while another connection holds a write
  lock, and SQLite does **not** consult the busy handler for it, so
  `busy_timeout` cannot cover it. Two connections opening a brand-new file at
  once — exactly what `--enrich` does — could therefore raise on a first run.
  `connect()` now sets a short setup timeout, tolerates losing that race, and
  the CLI migrates once before starting the companion so the race is avoided
  rather than merely survived.

Commit: `feat: enrich while the search is still running`.

### T9 — one real posting, end to end ✅
`tests/live/test_enrich_one_real_posting.py`, marked `live_llm`: one stored
Bundesagentur ad through the real pool, answer passes the validator, the
German level is evidenced by a phrase that appears in the ad.
What the live run taught, and what it did not:
- A real BA posting writes "Gute Deutschkenntnisse (mindestens B1-Niveau)"
  with a **non-breaking space**, and the model copies it back with an ordinary
  one. A naive substring check calls that faithful quotation a fabrication, so
  the evidence comparison normalises case and whitespace on both sides.
- `evidence_supports_the_level(answer, description)` now enforces the half of
  §5 the field rules cannot see: evidence must be traceable to the ad, not
  merely non-empty. An answer whose level is not backed is stored with
  `german_level: "unclear"` rather than discarded — the summary, duties and fit
  are still what she asked for — and the downgrade is counted in
  `EnrichmentRun.unevidenced_levels` and reported, never done silently.

Commit: `test: one real posting enriched end to end`.

### T10 — done-when on her real data
Enrich 20 real Bavarian postings. Read five against their ads. Hand-check
`german_level` on ten, including three kitchen or retail ads where the
requirement is implicit. Measure what a teaser-only Adzuna row produces
against what a full BA ad produces, and write both into this file. Interrupt
and resume; re-run and confirm zero calls. Tick the MASTER_PLAN boxes, merge.

## Done when (mirrored from MASTER_PLAN)

- 20 real Bavarian postings enriched; she reads five and confirms the English
  summaries match the ads
- `german_level` right on a hand-checked sample of ten, including at least
  three kitchen/retail ads where the requirement is implicit
- Interrupting the batch and re-running resumes without re-spending calls
- A full re-run with no new jobs makes **zero** provider calls
