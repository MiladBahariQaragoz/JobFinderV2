# LLM backend conventions

Every LLM call in JobFinderV2 goes through
[`llmpool`](https://github.com/MiladBahariQaragoz/FreeLLMPool), installed as a
git dependency in `requirements.txt`. Nothing here calls a provider SDK directly.

## Why a pool

Free tiers are individually unreliable: a few requests per minute, daily caps,
model names retired without notice, endpoints that 429 under load. The pool
turns that into one dependable backend — pacing, load spreading, graded back-off,
model-drift recovery, and health that persists in `data/pool_state.json` between
runs.

## Rules for code in this repo

1. **Build the pool once per run**, not per call. The token buckets, daily
   counters and health state only work if calls share one `Pool` instance.
2. **Always pass a `validator`.** It is the one project-specific hook:
   `(dict) -> (ok, reason)`. A junk answer costs the provider no cooldown — the
   pool just asks someone else — but only if the validator catches it.
3. **Always pass `state_path`.** Use `data/pool_state.json` so a new run does
   not re-probe what the last run proved dead.
4. **Bound the run.** Set `max_wait` per call and `run_deadline_seconds` for the
   whole job, so a batch cannot sleep indefinitely waiting for capacity.
5. **Batch with `run_batch`.** It keeps input order, returns failures as
   `BatchResult(ok=False, error=...)` instead of killing the run, and fires
   `on_result` as each item lands so partial work survives an interrupt.
6. **`complete_json` for structured output, `complete_text` for prose.** Both
   are thread-safe. `complete_json` raises `PoolExhausted` when nothing can
   answer.

```python
from llmpool import Pool, build_providers, load_catalog, run_batch

pool = Pool(
    build_providers(load_catalog()),
    validator=validator,
    state_path="data/pool_state.json",
    max_wait=3600,
    run_deadline_seconds=7200,
)

results = run_batch(pool, items, prompt_for, workers=8, on_result=save)
print(pool.summary())  # who actually did the work
```

## Keys

Keys live in `.env`, which is gitignored. `.env.example` is generated from the
provider catalog:

```bash
python -m llmpool env --out .env.example
```

The library itself reads `os.environ` and does not load `.env` — scripts call
`dotenv.load_dotenv()` first (see `scripts/llm_smoke.py`). The `llmpool` CLI
loads `.env` on its own.

## When enrichment breaks

Run these in order:

```bash
python -m llmpool doctor    # keys + live ping + drift, all in one
python -m llmpool drift     # do the configured model names still exist?
python -m llmpool models    # what can each key actually see?
```

A retired model name is by far the most likely cause of a sudden across-the-board
failure. The fix belongs in FreeLLMPool's `catalog.yaml` — one line of YAML in
that repo, not a workaround here.
