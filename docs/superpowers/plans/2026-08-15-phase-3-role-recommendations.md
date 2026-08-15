# Phase 3 — Role recommendations from her CV

Task-level plan for `docs/MASTER_PLAN.md` Phase 3. Branch: `feat/phase-3-role-recommendations`.

## Steps

1. **roles.v1.md** — the real prompt: CV digest in, 8–12 role objects out
   (`title_de`, `title_en`, `why`, `search_keywords`, `typical_employment_types`,
   `german_level_typical`, `confidence`). Written for German recruiter vocabulary.
2. **roles.py** — `build_cv_digest(resume)`: skill groups, education, experience
   summaries, languages. **Never** her address, phone or email — tested, not
   assumed. `suggest_roles(settings, pool_factory)` → runs the prompt through
   `complete_json_cached`, normalises (dedupe + lowercase keywords), validates,
   stores `data/suggested_roles.json` (prompt_version + created_at + roles).
   Empty CV (no skill groups and no experience) → helpful message, not an empty
   table.
3. **CLI** — `jobfinder suggest-roles [--json] [--top N] [--refresh]`: renders a
   readable table from stored suggestions; `--refresh` re-runs the LLM.
4. Tick MASTER_PLAN Phase 3 boxes, merge, push.

## Test-first checklist (from MASTER_PLAN)

- [ ] `test_cv_digest_excludes_address_email_and_phone`
- [ ] `test_cv_digest_includes_skill_groups_and_education_level`
- [ ] `test_roles_parsed_from_fake_answer_into_objects`
- [ ] `test_role_without_german_title_is_rejected_by_the_validator`
- [ ] `test_search_keywords_are_deduplicated_and_lowercased`
- [ ] `test_suggestions_are_cached_and_second_run_makes_no_call`
- [ ] `test_suggest_roles_cli_renders_a_table_from_stored_suggestions`
- [ ] `test_empty_cv_produces_a_helpful_message_not_an_empty_table`

## Out of scope

Ranking roles by market demand (Phase 5 shows live posting counts per keyword —
the honest version of that).
