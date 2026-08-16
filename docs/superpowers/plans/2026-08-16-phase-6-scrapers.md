---
title: "Phase 6 — Scrapers: Kleinanzeigen, StepStone, Indeed, Xing"
date: 2026-08-16
type: phase-plan
status: in progress — T1-T9 done, T10 (source health) next
master-plan: docs/MASTER_PLAN.md#phase-6--scrapers-kleinanzeigen-stepstone-indeed-xing
---

# Phase 6 task plan

Map: [MASTER_PLAN §Phase 6](../../MASTER_PLAN.md). This file is the turn-by-turn
version. Everything test-first, one checklist item per commit, pushed as it lands.

## Recon, verified live 2026-08-16 from this machine

Facts recorded before any code, the way §6 of the master plan demands. Every
request carried the project UA and §8 pacing.

### Kleinanzeigen — works

- Location-scoped, offers-only browse:
  `https://www.kleinanzeigen.de/s-jobs/{slug}/anzeige:angebote/c102l{id}` —
  27 ads per page, every ad in the chosen city. The `anzeige:angebote` path
  segment **excludes Gesuche at the source**; the wanted-ads browse lives
  under `anzeige:gesuche` and never gets requested.
- List page: `article.aditem` with `data-adid` (the id) and `data-href` (the
  ad URL); title in `.text-module-begin a.ellipsis`; plz + city in
  `.aditem-main--top--left` (`"85053 Ingolstadt"`); preview text in
  `.aditem-main--middle--description`. **No ItemList/JobPosting JSON-LD on
  list pages** — the 27 ld+json blocks are WebSite + ImageObjects.
- Detail page: `#viewad-title`, `#viewad-locality`
  (`"86343 Bayern - Königsbrunn"`), `#viewad-extra-info` (date, `07.08.2026`),
  `#viewad-description` (full text), `#viewad-contact` (seller; a message-form
  route — `tel:` links appear only when a phone number is published). No
  JSON-LD here either — selectors are the primary path, not the fallback.
- Pagination: follow the site's own `a.pagination-next` href
  (`/s-jobs/{slug}/anzeige:angebote/seite:2/c102l{id}`) — robust to segment
  reordering. Build page-1 URLs ourselves; never parse page numbers.
- The location autocomplete API (`/s-ort-empfehlungen.json`) answers 400/403
  to us. Ids therefore live in a **hand-recorded map**, verified against the
  location picker's own SEO links (Bayern page → Landkreis page → city):
  Neuburg ad Donau `l6603`, Ingolstadt `l7586`, München `l6411`, Erlangen
  `l6791`, Nürnberg (Mittelfr) `l6810`, Würzburg `l7667`, Ansbach `l6095`,
  Regensburg `l7636`, Augsburg `l7518`, Landshut `l6388`, Bamberg `l6885`,
  Bayreuth `l7483`, Passau `l7441`. A live test asserts each still returns
  ads in its city — the master plan's own answer to id drift.
- Keyword trap, re-confirmed: `/s-jobs/ingolstadt/c102` is a **nationwide
  keyword search** (first ad: Königsbrunn). Only the `c102l{id}` form pins
  the location.

### Xing — works, SEO pages only

- robots.txt for `User-agent: *` disallows `/jobs/search/` and `/search/`
  but not the SEO pages. We use exactly those, public, nothing behind login.
- Keyword + city: `https://www.xing.com/jobs/{keyword}-{cityslug}` — 200,
  ~19 job links. `?page=2` returns the same links: **single page, no
  pagination**. Location-only pages exist too (`/jobs/m-ingolstadt`).
- List anchors are empty links: `a[href^="/jobs/"]` ending in a numeric id,
  title in `aria-label`.
- Detail pages carry a full schema.org **JobPosting JSON-LD** — title,
  description (HTML), datePosted, employmentType, hiringOrganization.name,
  jobLocation. This is the JSON-LD-first path the master plan wants.

### StepStone — transport-blocked from this network

- Every request — robots.txt, sitemap, search, detail — is reset/timed out
  at the transport level (curl exit 56, urllib timeouts), IPv4 and IPv6
  alike. This is TLS-fingerprint filtering of non-browser clients, not a URL
  problem: the SEO pages exist and are server-rendered (verified through a
  different fetch path): `/jobs/{keyword}/in-{city}`, job links
  `/stellenangebote--{slug}--{id}-inline.html`.
- Consequence: the adapter is built (URL building, JSON-LD-first parsing,
  health tracking) and **shipped disabled by default**. §8 rule 4 forbids
  impersonating a browser, so the answer is the kill switch, not a workaround.
  Its parse path cannot be fixture-tested from this network — recorded here
  as a known gap, re-record when a page can be fetched.

### Indeed — 403 to us

- `de.indeed.com/jobs?q=Aushilfe&l=Ingolstadt` → 403 with their standard
  block page (recorded as a fixture — a real response, and the input the
  adapter will actually see). The RSS feed is retired (404). Same decision
  as StepStone: built, disabled by default, fails softly through the
  SourceUnavailable path that already exists.

### Both blocked boards

The kill switch is not theoretical on her laptop: `test_three_consecutive_
failures_disable_the_source` is the mechanism that makes a blocked board a
one-line summary entry instead of a hung run. `jobfinder sources check`
becomes the honest way to ask "does StepStone answer from here today?".

## Decisions

1. **Source codes**: `KA` (Kleinanzeigen), `SS`, `ID`, `XI` — `KA` joins
   §5's code list; MASTER_PLAN updated with this phase.
2. **Defaults**: `enabled_sources` gains `kleinanzeigen` and `xing`.
   `stepstone` and `indeed` are opt-in via config.yaml — they are blocked on
   this network and would burn minutes of timeouts per run; the kill switch
   covers the case where she enables them somewhere they do answer.
3. **Queries are alternatives** (Phase 4 audit rule): each employment type
   maps to one search term per city — minijob→`minijob`, werkstudent→
   `werkstudent`, parttime→`teilzeit`, fulltime→`vollzeit`, internship→
   `praktikum`. Her `keywords`, when present, add their own queries.
4. **Extraction**: one shared module extends `sources/extract.py` —
   JSON-LD `JobPosting` first (Xing emits it), CSS selectors second (bs4,
   new dependency), `extract_readable_text` last. Kleinanzeigen is
   selector-first because that is what the site actually offers.
5. **Parallel search** lands here, per the pacing record: one worker thread
   per source, per-host throttle already shared, one SQLite connection per
   worker (`connect()` per thread — §8 rule 2), counts merged under a lock.
6. **Health**: `source_state.consecutive_failures` increments per failed
   run of a source; at 3 the source gets a 24 h `cooldown_until` and the
   summary says why. A successful page resets the counter.

## Tasks

Shared groundwork, then sources in the master plan's order (Kleinanzeigen
first — it is the one that pays rent).

- [x] T1 `record_fixture.py --html` — flag that saves a page byte-for-byte
      and prints a warning when the body is not HTML (the JSON path stays
      as is). Test first.
- [x] T2 Record fixtures: `kleinanzeigen/list_ingolstadt.html`,
      `kleinanzeigen/detail_minijob.html`, `xing/list_aushilfe_ingolstadt.html`,
      `xing/detail_aushilfe.html`, `indeed/blocked.html` (the 403 body).
- [x] T3 `sources/extract.py`: `jsonld_jobpostings(html)`, `html_to_text`,
      `looks_like_login_wall`. Tests against the recorded Xing detail page
      and a real blocked page.
- [x] T4 `sources/wording.py`: employment-type word lists (the Phase 6
      minijob vocabulary: `Minijob`, `450 €`, `520 €`, `Aushilfe`,
      `geringfügig`) + `search_term_for(employment_type)` + slugs. Tests.
- [x] T5 `cities.py`: `KLEINANZEIGEN_LOCATIONS` map + lookup. Test: unknown
      city has no id and is skipped loudly (the adapter's job, tested there;
      here: the map covers every `CITY_NAMES` entry, so a new city cannot
      be added silently without an id).
- [x] T6 `sources/kleinanzeigen.py`: list parsing (25+ urls from one page),
      detail parsing, minijob flag from wording, gesuche excluded, unknown
      city skipped loudly, pagination via `pagination-next`, MAX_PAGES cap.
- [x] T7 `sources/xing.py`: SEO URL building, list anchors → (url, title),
      detail via JSON-LD, no pagination.
- [x] T8 `sources/stepstone.py` + `sources/indeed.py`: URL building tested
      as pure logic; parsing over the shared extractor; the recorded 403
      drives `test_unparseable_page_records_a_failure_and_returns_nothing`.
- [x] T9 Registry: four new sources, kinds `scraper`, labels, defaults,
      `SOURCE_CODES`. Tests: registry runs only enabled, scraper delay is
      the 3 s one.
- [ ] T10 Health: consecutive-failure counting, cooldown write, skip with
      reason at build time, reset on success. The three checklist tests.
- [ ] T11 Parallel `run_search`: thread per adapter, own connection per
      worker, merged counts, `test_two_different_hosts_are_fetched_at_the_
      same_time`, `test_scraper_never_issues_parallel_requests_to_one_host`
      (two adapters, one host, one throttle — the v0.3.0 rule at adapter
      scale).
- [ ] T12 `jobfinder sources check`: one known query per scraper, plain
      English verdict per source. CLI test with fakes.
- [ ] T13 Live tests: `test_kleinanzeigen_location_ids.py` (each mapped id
      returns ads located in its city), `test_scrapers_smoke.py` (one query
      per site, ≥1 parseable result or a clean "blocked" verdict).
- [ ] T14 Definition of Done sweep: full suite, ruff, MASTER_PLAN ticks and
      §5/§8 updates, config example, this file closed out.

## Known gaps this phase ships with

- StepStone and Indeed cannot be recorded from this network (transport
  block / 403). Their adapters exist, are disabled by default, and their
  fail-softly path is tested against the real blocked response. Re-record
  fixtures from a network they answer on, then enable.
- Kleinanzeigen detail pages expose no structured data; if they redesign,
  the selector fixture is the thing to re-record (`sources check` says so).
