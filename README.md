# JobFinderV2

A local job-search assistant for one person: it turns a CV into search terms,
collects live postings from German job APIs and job boards, explains each one in
English (including how much German it really needs), and tracks what has been
applied to. LLM work runs on a pool of free provider APIs rather than a single
paid endpoint.

**Start here:** [docs/MASTER_PLAN.md](docs/MASTER_PLAN.md) — the phase-by-phase
build plan, data contracts, verified source list, and definition of done for each
stage.

## Setup

```bash
python -m venv .venv
```

Activate it — the command differs per shell:

| Shell | Command |
|---|---|
| Windows cmd | `.venv\Scripts\activate.bat` |
| PowerShell | `.venv\Scripts\Activate.ps1` |
| Git Bash / Unix | `source .venv/Scripts/activate` (`.venv/bin/activate` on Unix) |

```bash
pip install -r requirements.txt
```

Then add at least one API key:

```bash
cp .env.example .env            # template lists every supported provider
python -m llmpool doctor        # keys + live ping + model drift
python scripts/llm_smoke.py     # end-to-end check: real call, validated answer
```

`.env.example` is generated — regenerate it with `python -m llmpool env --out .env.example`
whenever the provider catalog changes.

## Using it

Fill in `pool.yaml` from `pool.template.yaml` — that is the CV everything else
reads — then:

```bash
jobfinder profile validate          # does the CV parse, and what is in it
jobfinder suggest-roles             # job titles worth searching for, from the CV
jobfinder sources check             # which job sites still answer today
jobfinder search                    # collect postings  -> data/jobs-init.csv
jobfinder enrich                    # explain them in English -> data/jobs-enriched.csv
jobfinder search --enrich           # both at once: postings explained as they arrive
jobfinder serve                     # open the app in a browser — this is the product
```

`jobfinder serve` is the one to reach for. It starts a local server on
`127.0.0.1` (nothing listens beyond this machine, there is no login because
there is no second user) and opens a browser at it. From there: the whole store
as a filterable list, one page per job with its English answer and the German
original a click away, and *Applied* / *Interested* / *Not for me* / *Delete*
with a notes box. Searches start from that page too, narrated with per-source
counts while they run, and Cancel is always safe to press — everything already
fetched is on disk.

| Flag | What it does |
|---|---|
| `--port N` | serve somewhere other than 8000 |
| `--no-browser` | start the server, open nothing |
| `--root PATH` | use a different project root, and so a different `data/` |

Useful flags:

| Flag | Command | What it does |
|---|---|---|
| `--cities`, `--types`, `--keywords` | `search` | narrow the search; defaults cover Neuburg, Ingolstadt and Munich |
| `--dry-run` | `search` | print the exact URLs, send nothing, store nothing |
| `--resume` | `search` | continue the newest interrupted run |
| `--limit N` | `enrich` | explain at most N postings this run |
| `--force` | `enrich` | explain postings again even when they already have an answer |

Both long-running commands are safe to interrupt. Every posting and every
answer is committed to SQLite and appended to its CSV the moment it completes,
so Ctrl-C costs only the item in flight, and re-running skips everything
already done rather than re-spending an LLM call on it.

### What enrichment gives you

One row per posting in `data/jobs-enriched.csv`: an English summary, the
duties and requirements, a fit score against the CV with reasons and gaps, the
application route (email, portal or phone), and **how much German the job
actually needs**.

That last field is the one with a rule behind it. `german_level` is either a
CEFR level backed by `german_evidence` — the phrase from the ad, checked
against the ad text — or `unclear`. A job whose posting never states a language
requirement reads `unclear`, even when the requirement is obvious from the
work. An honest "we cannot tell" beats a plausible guess you would plan a week
around.

## The LLM backend

[FreeLLMPool](https://github.com/MiladBahariQaragoz/FreeLLMPool) (`llmpool`) is
installed straight from git as a dependency. It pools sixteen free provider
tiers into one backend: it paces requests under each tier's published limits,
spreads load, backs off correctly on 429s and outages, rotates away from retired
model names, and persists provider health between runs.

Blank keys are skipped, so a partial set still gives a working pool. Start with
one — [Groq](https://console.groq.com/keys) is the fastest and needs no card.

```python
from llmpool import Pool, build_providers, load_catalog

pool = Pool(
    build_providers(load_catalog()),
    validator=my_validator,  # (dict) -> (ok, reason)
    state_path="data/pool_state.json",
)
answer = pool.complete_json(prompt)  # dict, or raises PoolExhausted
```

See [docs/llm-backend.md](docs/llm-backend.md) for the conventions this repo
follows, and `python -m llmpool --help` for the CLI.

## Layout

| Path | What lives there |
|---|---|
| `src/jobfinder/sources/` | One adapter per job site, behind a shared interface |
| `src/jobfinder/store/` | SQLite schema, upserts, and the CSV exports |
| `src/jobfinder/enrich/` | The enrichment batch, its CSV mapping, and the search companion |
| `src/jobfinder/llm/` | Pool construction, answer contracts, prompts, answer cache |
| `src/jobfinder/web/` | The browser app: routes, queries, templates, and the fonts and htmx it ships with so it works offline |
| `scripts/` | One-off and diagnostic scripts, e.g. `llm_smoke.py` |
| `docs/` | Working notes and conventions |
| `data/` | Runtime state — the database, CSVs, pool health, caches. Gitignored. |

## Tests

```bash
pytest                  # offline: unit, contract, store, CLI. No network.
pytest -m live          # opt-in: hits the real internet
pytest -m live_llm      # opt-in: spends a real LLM call
ruff check . && ruff format --check .
```

The offline suite is guarded: any outbound connection from an unmarked test
fails loudly, so a test that needs real data reads a recorded fixture instead
(`scripts/record_fixture.py` writes them).
