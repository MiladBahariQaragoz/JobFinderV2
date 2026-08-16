"""Content-hash cache so nothing is enriched twice.

Keyed by ``sha1(prompt_version + content_hash + spec_fingerprint)`` — a new
prompt version, changed job text, or a changed spec all miss the cache; anything
else must hit it and cost no provider call.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from llmpool import Pool


def cache_key(prompt_version: str, content_hash: str, spec_fingerprint: str) -> str:
    """A stable sha1 of everything an answer depends on."""
    digest = hashlib.sha1(f"{prompt_version}\x1f{content_hash}\x1f{spec_fingerprint}".encode())
    return digest.hexdigest()


def fingerprint(obj) -> str:
    """A stable sha1 of any JSON-able object — the 'spec' part of a cache key."""
    canonical = json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(canonical.encode()).hexdigest()


class LLMCache:
    """SQLite-backed answer store. One row per cache key, JSON-encoded answers.

    Safe to share across threads: enrichment runs `run_batch` with several
    workers over one cache. sqlite3 refuses a connection used off its creating
    thread, so the connection is opened without that check and every statement
    is serialised behind one lock instead — the calls are microseconds long and
    the workers spend their time waiting on providers, not on this.
    """

    def __init__(self, db_path: Path):
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS llm_cache ("
            " key TEXT PRIMARY KEY,"
            " answer TEXT NOT NULL,"
            " created_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
        self._db.commit()

    def get(self, key: str) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT answer FROM llm_cache WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def put(self, key: str, answer: dict) -> None:
        payload = json.dumps(answer, ensure_ascii=False)
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO llm_cache (key, answer) VALUES (?, ?)",
                (key, payload),
            )
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def __enter__(self) -> LLMCache:
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()


def complete_json_cached(pool: Pool, cache: LLMCache, *, prompt: str, key: str) -> dict:
    """Ask the pool once per key: cache first, provider second, store on return.

    ``PoolExhausted`` propagates — it is a handled domain error the caller turns
    into a resumable message — and nothing is written on the way out.
    """
    cached = cache.get(key)
    if cached is not None:
        return cached

    answer = pool.complete_json(prompt)
    cache.put(key, answer)
    return answer
