"""The LLM cache — nothing is enriched twice, no matter what interrupted it."""

from __future__ import annotations

import pytest
from llmpool import PoolExhausted
from tests.fakes import FakePool

from jobfinder.llm.cache import LLMCache, cache_key, complete_json_cached

ANSWER = {"roles": [{"title_de": "Werkstudent Datenanalyse"}]}


@pytest.fixture
def cache(tmp_path):
    with LLMCache(tmp_path / "cache.db") as open_cache:
        yield open_cache


def test_cache_returns_stored_answer_without_calling_the_pool(cache):
    pool = FakePool([ANSWER])

    first = complete_json_cached(pool, cache, prompt="p", key=cache_key("v1", "h1", "f1"))
    second = complete_json_cached(pool, cache, prompt="p", key=cache_key("v1", "h1", "f1"))

    assert first == second == ANSWER
    assert len(pool.calls) == 1  # the second answer came from the cache


def test_cache_misses_when_prompt_version_changes(cache):
    pool = FakePool([ANSWER, ANSWER])

    complete_json_cached(pool, cache, prompt="p", key=cache_key("v1", "h1", "f1"))
    complete_json_cached(pool, cache, prompt="p2", key=cache_key("v2", "h1", "f1"))

    assert len(pool.calls) == 2


def test_cache_misses_when_content_hash_changes(cache):
    pool = FakePool([ANSWER, ANSWER])

    complete_json_cached(pool, cache, prompt="p", key=cache_key("v1", "h1", "f1"))
    complete_json_cached(pool, cache, prompt="p", key=cache_key("v1", "h2", "f1"))

    assert len(pool.calls) == 2


def test_cache_survives_reopening_the_database(tmp_path):
    db_path = tmp_path / "cache.db"
    with LLMCache(db_path) as first:
        first.put("k", ANSWER)

    with LLMCache(db_path) as reopened:
        assert reopened.get("k") == ANSWER


def test_pool_exhausted_is_surfaced_as_a_handled_error_not_a_crash(cache):
    pool = FakePool([PoolExhausted("every provider is out of quota")])

    with pytest.raises(PoolExhausted):
        complete_json_cached(pool, cache, prompt="p", key=cache_key("v1", "h1", "f1"))

    # nothing half-written is stored — the job stays unenriched, retried later
    assert cache.get(cache_key("v1", "h1", "f1")) is None


def test_cache_closes_its_connection_on_context_manager_exit(tmp_path, sqlite_leaks):
    with LLMCache(tmp_path / "cache.db") as cache:
        cache.put("k", ANSWER)

    assert sqlite_leaks() == []


def test_cache_keys_differ_on_every_component():
    keys = {
        cache_key("v1", "h1", "f1"),
        cache_key("v2", "h1", "f1"),
        cache_key("v1", "h2", "f1"),
        cache_key("v1", "h1", "f2"),
    }

    assert len(keys) == 4
    assert all(len(key) == 40 for key in keys)  # sha1 hex digest


def test_the_cache_can_be_read_and_written_from_a_worker_thread(tmp_path):
    """Enrichment runs `run_batch` with several workers, all sharing one cache.

    sqlite3 refuses a connection used off its creating thread, so without this
    every enrichment call fails before it ever reaches a provider.
    """
    from concurrent.futures import ThreadPoolExecutor

    with LLMCache(tmp_path / "cache.db") as cache:

        def store_and_read(index: int):
            key = f"key-{index}"
            cache.put(key, {"answer": index})
            return cache.get(key)

        with ThreadPoolExecutor(max_workers=4) as executor:
            answers = list(executor.map(store_and_read, range(8)))

    assert answers == [{"answer": index} for index in range(8)]
