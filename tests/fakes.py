"""A fake llmpool Pool: canned answers, recorded calls, simulated failures."""

from __future__ import annotations


class FakePool:
    """Stands in for llmpool.Pool — never touches the network.

    Feed it a list of answers (dicts) and/or exceptions (e.g. PoolExhausted);
    each call to ``complete_json`` consumes the next one. Every prompt is
    recorded so tests can assert how often the pool was actually asked.
    """

    def __init__(self, answers: list | None = None):
        self.answers = list(answers or [])
        self.calls: list[str] = []

    def complete_json(self, prompt: str) -> dict:
        self.calls.append(prompt)
        if not self.answers:
            raise AssertionError("FakePool ran out of canned answers")
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def complete_text(self, prompt: str) -> str:
        self.calls.append(prompt)
        if not self.answers:
            raise AssertionError("FakePool ran out of canned answers")
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def summary(self) -> str:
        return f"FakePool answered {len(self.calls)} call(s)"
