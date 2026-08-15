# JobFinderV2

Job search tooling, rebuilt. LLM work in this repo runs on a pool of free
provider APIs rather than a single paid endpoint.

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

pool = Pool(build_providers(load_catalog()),
            validator=my_validator,              # (dict) -> (ok, reason)
            state_path="data/pool_state.json")
answer = pool.complete_json(prompt)              # dict, or raises PoolExhausted
```

See [docs/llm-backend.md](docs/llm-backend.md) for the conventions this repo
follows, and `python -m llmpool --help` for the CLI.

## Layout

| Path | What lives there |
|---|---|
| `scripts/` | One-off and diagnostic scripts, e.g. `llm_smoke.py` |
| `docs/` | Working notes and conventions |
| `data/` | Runtime state — pool health, caches. Gitignored. |
