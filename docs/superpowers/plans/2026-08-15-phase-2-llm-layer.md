# Phase 2 — The LLM layer

Task-level plan for `docs/MASTER_PLAN.md` Phase 2. Branch: `feat/phase-2-llm-layer`.

## Steps

1. **llm/schema.py** — declarative field specs → validator functions of the shape
   llmpool expects: `(dict) -> (ok, reason)`. Unknown keys tolerated; missing or
   invalid keys rejected with a reason naming the key. Handles non-dict answers
   (prose masquerading as JSON) and enum/range rules. The `roles.v1` spec lives here.
2. **llm/prompts/** — prompt files as Markdown, filename carries the version
   (`roles.v1.md`). `load_prompt(name)` returns text + parsed version string.
   The version string is part of the cache key and later lands in the database.
3. **llm/cache.py** — SQLite table `llm_cache(key PRIMARY KEY, answer TEXT,
   created_at)`; `cache_key(prompt_version, content_hash, spec_fingerprint)`
   = `sha1` of the three; `complete_json_cached(pool, cache, …)` checks the cache
   before the pool and stores validated answers on the way back.
4. **llm/pool.py** — `build_pool(settings, validator)`; one Pool per run,
   `state_path` from settings, `max_wait`/`run_deadline_seconds` from settings
   (new `Settings` fields with defaults 3600 / 7200). Empty provider list raises
   a one-sentence error naming the fix (`cp .env.example .env` + doctor).
5. **tests/fakes.py** — `FakePool`: canned answers in order, records every call,
   can raise `PoolExhausted` or return junk.
6. **tests/live/test_llm_smoke.py** (marker `live_llm`) — one real call, valid
   JSON back.
7. Tick MASTER_PLAN Phase 2 boxes, merge, push.

## Test-first checklist (from MASTER_PLAN)

- [ ] `test_validator_accepts_a_well_formed_answer`
- [ ] `test_validator_rejects_missing_required_key_with_named_reason`
- [ ] `test_validator_rejects_prose_masquerading_as_json`
- [ ] `test_validator_rejects_out_of_range_enum_value`
- [ ] `test_cache_returns_stored_answer_without_calling_the_pool`
- [ ] `test_cache_misses_when_prompt_version_changes`
- [ ] `test_cache_misses_when_content_hash_changes`
- [ ] `test_pool_exhausted_is_surfaced_as_a_handled_error_not_a_crash`
- [ ] `test_build_pool_raises_a_readable_error_when_no_provider_keys_exist`
- [ ] `tests/live/test_llm_smoke.py` (marked `live_llm`)

## Out of scope

Streaming, function calling, embeddings; the roles prompt content itself (Phase 3
fills `roles.v1.md` with real instructions — Phase 2 ships the loader and a stub).
