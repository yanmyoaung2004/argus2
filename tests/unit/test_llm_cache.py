from __future__ import annotations

import time

import pytest

from argus.services.memory.llm_cache import LLMCache


@pytest.fixture
def cache() -> LLMCache:
    return LLMCache(db_path=":memory:", ttl=3600)


class TestLLMCache:
    def test_get_miss_returns_none(self, cache: LLMCache) -> None:
        assert cache.get("hello", "model-x") is None

    def test_set_and_get(self, cache: LLMCache) -> None:
        cache.set("hello", "model-x", "world")
        assert cache.get("hello", "model-x") == "world"

    def test_different_prompt_miss(self, cache: LLMCache) -> None:
        cache.set("hello", "model-x", "world")
        assert cache.get("goodbye", "model-x") is None

    def test_different_model_miss(self, cache: LLMCache) -> None:
        cache.set("hello", "model-x", "world")
        assert cache.get("hello", "model-y") is None

    def test_expired_entry_returns_none(self, cache: LLMCache) -> None:
        cache._ttl = 0
        cache.set("hello", "m", "world")
        time.sleep(0.01)
        assert cache.get("hello", "m") is None

    def test_clear_expired(self, cache: LLMCache) -> None:
        cache._ttl = 0
        cache.set("prompt-a", "m", "resp-a")
        cache.set("prompt-b", "m", "resp-b")
        time.sleep(0.01)
        cleared = cache.clear_expired()
        assert cleared >= 2
        assert cache.get("prompt-a", "m") is None

    def test_overwrite_existing(self, cache: LLMCache) -> None:
        cache.set("hello", "m", "world")
        cache.set("hello", "m", "updated")
        assert cache.get("hello", "m") == "updated"
