---
title: Request pacing, and the groundwork for doing work in parallel
date: 2026-08-16
type: change-record
status: done — shipped as v0.3.0
---

# Request pacing and concurrency groundwork

Not a phase. A cross-cutting change to how the app spends wall time, prompted
by one question: if every request waits 3–4 seconds, why is a search allowed to
do them one at a time, and why does enrichment wait for the search to finish?

Source of truth for the rules this changed: `docs/MASTER_PLAN.md` §8 (etiquette)
and §9 (incremental saving). This document records what was measured, what was
decided, and what was deliberately left for Phase 6.

## The question, and what the numbers said

The proposal was cross-source parallelism: fetch different sites at the same
time, each keeping its own 3-second gap. That is allowed by §8 — rule 1 forbids
parallel fetching **of one host**, not of the internet — and the throttle was
already keyed per host. What blocked it was the runner: `run_search` walks
`for adapter in adapters:` strictly in order.

Measured against a real Ingolstadt minijob run (119 Bundesagentur requests on
one host, 10 Arbeitnow requests on another):

| | wall time |
|---|---|
| Sequential, as built | ≈ 7.5 min |
| Cross-source parallel | ≈ 7.0 min |
| Sequential, 1 s gap for API hosts | ≈ 2.7 min |

**92 % of a run's requests go to one host**, so parallelising across sources
saves about 35 seconds. The gap itself was the expensive part — and the 3-second
figure is scraper etiquette, applied by default to a documented, keyed API that
is not a scraped site.

So the order of work inverted: pace first, parallelise later, when Phase 6 has
four scrapers on four hosts and the arithmetic changes (four sources × 60
requests is 14 minutes serial against 3.5 in parallel).

## What shipped

### 1. Pacing by host kind

`api_delay_seconds` (1.0) and `scraper_delay_seconds` (3.0) join `Settings`.
`SOURCE_KINDS` in the registry declares what each source talks to; the registry
is the only place that knows which sources are scraped, so it is the place that
picks the pace. The client factory builds each adapter's client accordingly.
Phase 6's scrapers arrive as `"scraper"` and keep the careful gap.

Neither the Bundesagentur nor Arbeitnow documents a rate limit, so 1 s is a
judgment call — backed by the `Retry-After` handling, the exponential backoff
and the kill switch that already existed, and by her ability to slow any of it
down from `config.yaml`.

**Measured live**: a cold Augsburg minijob search spent 268 requests in 402 s
(1.50 s each — the 1 s gap plus mean jitter), returned 263 jobs, and saw no 429
and no failed source. The same search at the old pace would have taken 15.6
minutes instead of 6.7.

### 2. The gap belongs to the host, not the client

Every adapter is built with its own `PoliteClient` — its own budget, its own
cache handle — and each one kept its own `_next_allowed` dictionary. Two
adapters pointed at one host would each have thought the host was free. Nothing
does that today, which is precisely why it had to be fixed before anything
fetches in parallel: the failure would have been silent, with no test failing
and only a blocked IP to show for it.

`HostThrottle` now holds host → next-free-time behind a lock, shared by every
client in the process. A slot is claimed under the lock and slept for outside
it, so one slow host cannot queue the others behind it. Clients that want
isolation — the tests, mostly — pass their own instance.

### 3. The store waits for its turn

Enrichment is meant to run while a search is still storing jobs. WAL lets
readers through a write, but two writers still take turns, and the second must
wait rather than raise `database is locked`. `connect()` now sets
`busy_timeout` to 15 s explicitly, and the test that proves it runs a real
second writer on its own thread with its own connection.

## Two things this got wrong on the way, kept here on purpose

- **The claim that a second writer fails immediately today was false.** It went
  into MASTER_PLAN §8 as justification before it was tested. Python's `sqlite3`
  driver applies a 5-second busy timeout of its own, so concurrent writes
  already worked; writing the test first is what caught it. The change is still
  worth having — a durability rule her data depends on should not rest on a
  driver default a Python release could change — but it is a smaller gap than
  it was written up as, and §8 now says so.
- **The first draft of that test committed a connection from another thread**,
  and sqlite3 rejected it for exactly the reason the one-connection-per-thread
  rule exists. The rule earned its place in §8 by breaking the test written to
  demonstrate it.

## What was deliberately not done

`run_search` is still sequential. Parallel fetching lands with **Phase 6**,
where four scrapers on four hosts make it worth roughly 4x, and both
prerequisites it needs are now in place. Its tests are already listed in
MASTER_PLAN's Phase 6 checklist:

- `test_two_adapters_pointed_at_one_host_share_a_single_throttle`
- `test_two_different_hosts_are_fetched_at_the_same_time`

Enrichment running alongside a search is **Phase 7**, described in
[§9](../../MASTER_PLAN.md#enrichment-does-not-wait-for-the-search-to-finish):
the store is the queue, `jobfinder search --enrich` starts both, and either
command alone must still behave exactly as it does today.

One more measurement worth carrying into Phase 6: of the 268 requests in the
Augsburg run, **262 were detail fetches**. Search pages are cheap; detail pages
are the run. Skipping them for jobs already stored (Phase 5, T11) was worth more
than any concurrency change, and it is the number to watch when the scrapers
start fetching listing pages one ad at a time.

