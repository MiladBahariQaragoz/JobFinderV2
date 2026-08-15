"""Smoke test for the LLM backend.

Proves the llmpool dependency is installed, that at least one provider key in
.env works, and that a real JSON completion comes back and passes a validator.

Run it after adding or rotating keys:

    python scripts/llm_smoke.py

Exit code 0 means the pool answered. Anything else means the backend is not
usable yet, and the message says which part is missing.
"""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv
from llmpool import Pool, PoolExhausted, build_providers, load_catalog, missing_keys

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "data" / "pool_state.json"

PROMPT = (
    "Return JSON with exactly two keys: 'title' (the job title in the text) and "
    "'seniority' (one of: junior, mid, senior). "
    "Text: 'We are hiring a Senior Backend Engineer to own our payments platform.'"
)


def validator(answer: dict) -> tuple[bool, str]:
    """Keep an answer only if it has the shape the pipeline expects."""
    if not isinstance(answer.get("title"), str):
        return False, "no title"
    if answer.get("seniority") not in {"junior", "mid", "senior"}:
        return False, "seniority not one of junior/mid/senior"
    return True, "ok"


def main() -> int:
    load_dotenv(ROOT / ".env")
    catalog = load_catalog()
    providers = build_providers(catalog)

    if not providers:
        print("No providers have keys.\n")
        print("  cp .env.example .env   # then fill in at least one key")
        for name, env_var, signup in missing_keys(catalog):
            print(f"  {name:<12} {env_var:<28} {signup}")
        return 1

    print(f"{len(providers)} provider(s) with keys: {', '.join(p.name for p in providers)}\n")

    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    pool = Pool(providers, validator=validator, state_path=STATE_PATH, max_wait=120)

    try:
        answer = pool.complete_json(PROMPT)
    except PoolExhausted as exc:
        print(f"Pool exhausted: {exc}")
        print("Run `python -m llmpool doctor` to see which providers are healthy.")
        return 1

    print(f"answer: {answer}")
    print(f"\n{pool.summary()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
