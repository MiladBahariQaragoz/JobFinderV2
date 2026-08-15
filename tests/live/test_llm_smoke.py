"""One real LLM call, end to end — opt-in, spends quota.

Run with: pytest -m live_llm

Answers the only question that matters live: does a real provider return JSON
that passes our validator through the real pool wiring?
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jobfinder.config import Settings
from jobfinder.llm.pool import build_pool
from jobfinder.llm.schema import FieldRule, make_validator

PROJECT_ROOT = Path(__file__).resolve().parents[2]

PROMPT = (
    "Return JSON with exactly two keys: 'title' (the job title in the text) and "
    "'seniority' (one of: junior, mid, senior). "
    "Text: 'We are hiring a Senior Backend Engineer to own our payments platform.'"
)

SMOKE_SPEC = {
    "title": FieldRule(kind="str"),
    "seniority": FieldRule(kind="str", enum=("junior", "mid", "senior")),
}


@pytest.mark.live_llm
def test_one_real_call_returns_valid_json():
    settings = Settings.load(PROJECT_ROOT)
    pool = build_pool(settings, make_validator(SMOKE_SPEC))

    answer = pool.complete_json(PROMPT)

    assert answer["seniority"] == "senior"
    assert "Engineer" in answer["title"]
