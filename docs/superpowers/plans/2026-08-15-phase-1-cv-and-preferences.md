# Phase 1 — Her CV and her preferences

Task-level plan for `docs/MASTER_PLAN.md` Phase 1. Branch: `feat/phase-1-cv-and-preferences`.

## Steps

1. **cities.py** — `CITY_NAMES`, `CITY_COORDS`, `resolve_city(name)` that folds umlauts
   (`Muenchen` → `München`), `City` dataclass with `radius_km=25` default.
   Tests: unknown city lists the valid ones; radius default + override.
2. **profile.py** — `ProfileError` (one actionable sentence, YAML line where known),
   `load_profile(path) -> Resume`. Parses basics / languages / experience / projects /
   education / skill_groups / certifications with the template's conventions
   (`YYYY-MM` or `present`, bullet tags, skill group items).
   - Required basics: `name`, `email`, `location` — error names the field and the
     line of the offending section (via `yaml.compose` node marks).
   - Languages: raw level kept; `normalize_language_level` maps
     `Mother tongue|Native…` → `C2`, `Fluent` → `C1`, `Basic` → `A2`, `A1..C2` as-is.
   - Experience dates validated (`YYYY-MM`, month 01–12, or `present`); errors name
     the entry `id`.
   - `years_of_experience()` for the summary.
3. **search_spec.py** — `EmploymentType` literals (`minijob`, `werkstudent`, `parttime`,
   `fulltime`, `internship`), `GermanLevel` ordered enum (`none..C2`),
   `SearchSpec(mode, employment_types, cities, radius_km, keywords, max_german_level)`.
   Rejects: empty employment types, empty cities, unknown city, unknown type,
   `resume` mode without a `Resume` passed in. `general` mode needs no resume.
4. **cli.py + Settings.pool_path** — `jobfinder profile validate` (green summary:
   name, languages, 3 largest skill groups, years of experience) and
   `jobfinder profile show` (full readable dump). `ProfileError` → one sentence,
   exit 1. Settings gains `pool_path` property.
5. Tick MASTER_PLAN Phase 1 boxes, merge, push.

## Test-first checklist (from MASTER_PLAN)

- [ ] `test_parses_the_blank_template_without_crashing`
- [ ] `test_missing_required_basics_names_the_field_and_the_line`
- [ ] `test_language_levels_parse_including_mother_tongue`
- [ ] `test_experience_dates_accept_yyyy_mm_and_present`
- [ ] `test_invalid_date_reports_the_entry_id_not_a_stack_trace`
- [ ] `test_unknown_city_lists_the_valid_ones`
- [ ] `test_city_radius_defaults_to_25km_and_can_be_overridden`
- [ ] `test_search_spec_rejects_empty_employment_types`
- [ ] `test_general_mode_does_not_require_a_resume`
- [ ] `test_resume_mode_requires_a_readable_pool_yaml`

## Out of scope

PDF/DOCX parsing (her CV is transcribed into `pool.yaml` once, by hand);
anything LLM (Phase 2); anything that hits the network.
