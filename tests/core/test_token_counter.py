"""Tests for token counter with caching."""

import pytest
from backend.core.context.token_counter import TokenCounter


class TestTokenCounter:

    def test_count_returns_int(self):
        tc = TokenCounter()
        result = tc.count("Hello, world!")
        assert isinstance(result, int)
        assert result > 0

    def test_cache_hit(self):
        tc = TokenCounter()
        text = "This is a test string for caching"
        result1 = tc.count(text)
        result2 = tc.count(text)
        assert result1 == result2
        assert len(tc._cache) == 1

    def test_lru_eviction(self):
        tc = TokenCounter(cache_size=3)
        tc.count("text_a")
        tc.count("text_b")
        tc.count("text_c")
        assert len(tc._cache) == 3

        tc.count("text_d")  # Should evict oldest
        assert len(tc._cache) == 3

    def test_empty_string(self):
        tc = TokenCounter()
        assert tc.count("") == 0

    def test_clear(self):
        tc = TokenCounter()
        tc.count("hello")
        tc.count("world")
        cleared = tc.clear()
        assert cleared == 2
        assert len(tc._cache) == 0
