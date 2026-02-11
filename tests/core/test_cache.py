"""Tests for backend.core.utils.cache."""

import asyncio
import time
from unittest.mock import patch

import pytest
from backend.core.utils.cache import (
    CacheStats,
    TTLCache,
    cached,
    get_cache,
    get_all_cache_stats,
    invalidate_cache,
    _default_key_builder,
    _caches,
)


# ---------------------------------------------------------------------------
# CacheStats
# ---------------------------------------------------------------------------


class TestCacheStats:
    """Tests for the CacheStats dataclass."""

    def test_initial_values(self):
        stats = CacheStats()
        assert stats.hits == 0
        assert stats.misses == 0
        assert stats.evictions == 0

    def test_hit_rate_zero_total(self):
        stats = CacheStats()
        assert stats.hit_rate == 0.0

    def test_hit_rate_all_hits(self):
        stats = CacheStats(hits=10, misses=0)
        assert stats.hit_rate == 1.0

    def test_hit_rate_mixed(self):
        stats = CacheStats(hits=3, misses=7)
        assert stats.hit_rate == pytest.approx(0.3)

    def test_hit_rate_all_misses(self):
        stats = CacheStats(hits=0, misses=5)
        assert stats.hit_rate == 0.0


# ---------------------------------------------------------------------------
# TTLCache
# ---------------------------------------------------------------------------


class TestTTLCache:
    """Tests for the TTLCache class."""

    @pytest.fixture
    def cache(self):
        return TTLCache(maxsize=10, ttl_seconds=60, name="test")

    async def test_get_miss(self, cache):
        hit, value = await cache.get("nonexistent")
        assert hit is False
        assert value is None
        assert cache.stats.misses == 1

    async def test_set_and_get(self, cache):
        await cache.set("key1", "value1")
        hit, value = await cache.get("key1")
        assert hit is True
        assert value == "value1"
        assert cache.stats.hits == 1

    async def test_ttl_expiration(self, cache):
        # Use a very short TTL
        short_cache = TTLCache(maxsize=10, ttl_seconds=0, name="short")
        await short_cache.set("key1", "value1")
        # TTL is 0 seconds, so it should be expired immediately
        # (time.time() - timestamp >= 0 is always true when ttl=0)
        hit, value = await short_cache.get("key1")
        assert hit is False
        assert value is None
        assert short_cache.stats.evictions == 1

    async def test_ttl_expiration_with_mock(self, cache):
        await cache.set("key1", "value1")
        # Advance time past TTL
        with patch("backend.core.utils.cache.time") as mock_time:
            mock_time.time.return_value = time.time() + 120  # 2 min past TTL (60s)
            hit, value = await cache.get("key1")
        assert hit is False
        assert value is None

    async def test_lru_eviction(self):
        cache = TTLCache(maxsize=3, ttl_seconds=60, name="small")
        await cache.set("a", 1)
        await cache.set("b", 2)
        await cache.set("c", 3)
        # Cache is full; adding "d" should evict "a" (oldest)
        await cache.set("d", 4)
        hit, _ = await cache.get("a")
        assert hit is False
        hit, value = await cache.get("d")
        assert hit is True
        assert value == 4
        assert cache.stats.evictions >= 1

    async def test_lru_order_updated_on_get(self):
        cache = TTLCache(maxsize=3, ttl_seconds=60, name="lru")
        await cache.set("a", 1)
        await cache.set("b", 2)
        await cache.set("c", 3)
        # Access "a" to move it to end (most recently used)
        await cache.get("a")
        # Now "b" is the oldest; adding "d" should evict "b"
        await cache.set("d", 4)
        hit_a, _ = await cache.get("a")
        hit_b, _ = await cache.get("b")
        assert hit_a is True
        assert hit_b is False

    async def test_overwrite_existing_key(self, cache):
        await cache.set("key1", "old")
        await cache.set("key1", "new")
        hit, value = await cache.get("key1")
        assert hit is True
        assert value == "new"

    async def test_invalidate_existing_key(self, cache):
        await cache.set("key1", "value1")
        removed = await cache.invalidate("key1")
        assert removed is True
        hit, _ = await cache.get("key1")
        assert hit is False

    async def test_invalidate_nonexistent_key(self, cache):
        removed = await cache.invalidate("nonexistent")
        assert removed is False

    async def test_clear_returns_count(self, cache):
        await cache.set("a", 1)
        await cache.set("b", 2)
        await cache.set("c", 3)
        count = await cache.clear()
        assert count == 3

    async def test_clear_empty_cache(self, cache):
        count = await cache.clear()
        assert count == 0

    async def test_clear_makes_cache_empty(self, cache):
        await cache.set("a", 1)
        await cache.clear()
        hit, _ = await cache.get("a")
        assert hit is False

    def test_get_stats_structure(self, cache):
        stats = cache.get_stats()
        assert stats["name"] == "test"
        assert stats["size"] == 0
        assert stats["maxsize"] == 10
        assert stats["ttl_seconds"] == 60
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["evictions"] == 0
        assert "hit_rate" in stats

    async def test_get_stats_updated_after_operations(self, cache):
        await cache.set("a", 1)
        await cache.get("a")  # hit
        await cache.get("b")  # miss
        stats = cache.get_stats()
        assert stats["size"] == 1
        assert stats["hits"] == 1
        assert stats["misses"] == 1

    async def test_various_value_types(self, cache):
        """Cache should store any Python object."""
        await cache.set("str", "hello")
        await cache.set("int", 42)
        await cache.set("list", [1, 2, 3])
        await cache.set("dict", {"key": "val"})
        await cache.set("none", None)

        _, v = await cache.get("str")
        assert v == "hello"
        _, v = await cache.get("int")
        assert v == 42
        _, v = await cache.get("list")
        assert v == [1, 2, 3]
        _, v = await cache.get("dict")
        assert v == {"key": "val"}
        hit, v = await cache.get("none")
        assert hit is True
        assert v is None


# ---------------------------------------------------------------------------
# get_cache / get_all_cache_stats
# ---------------------------------------------------------------------------


class TestCacheRegistry:
    """Tests for the global cache registry functions."""

    @pytest.fixture(autouse=True)
    def clean_registry(self):
        """Isolate tests from the global _caches dict."""
        saved = dict(_caches)
        _caches.clear()
        yield
        _caches.clear()
        _caches.update(saved)

    def test_get_cache_creates_new(self):
        cache = get_cache("test_new", maxsize=50, ttl_seconds=120)
        assert isinstance(cache, TTLCache)
        assert cache.name == "test_new"
        assert cache.maxsize == 50
        assert cache.ttl == 120

    def test_get_cache_returns_same_instance(self):
        c1 = get_cache("shared")
        c2 = get_cache("shared")
        assert c1 is c2

    def test_get_cache_different_names_different_instances(self):
        c1 = get_cache("cache_a")
        c2 = get_cache("cache_b")
        assert c1 is not c2

    def test_get_all_cache_stats(self):
        get_cache("stats_a")
        get_cache("stats_b")
        all_stats = get_all_cache_stats()
        assert "stats_a" in all_stats
        assert "stats_b" in all_stats
        assert isinstance(all_stats["stats_a"], dict)

    def test_get_all_cache_stats_empty(self):
        all_stats = get_all_cache_stats()
        assert all_stats == {}


# ---------------------------------------------------------------------------
# _default_key_builder
# ---------------------------------------------------------------------------


class TestDefaultKeyBuilder:
    """Tests for the _default_key_builder function."""

    def test_returns_string(self):
        key = _default_key_builder(("a",), {"b": 1})
        assert isinstance(key, str)

    def test_same_args_same_key(self):
        k1 = _default_key_builder(("hello",), {"n": 5})
        k2 = _default_key_builder(("hello",), {"n": 5})
        assert k1 == k2

    def test_different_args_different_key(self):
        k1 = _default_key_builder(("a",), {})
        k2 = _default_key_builder(("b",), {})
        assert k1 != k2

    def test_different_kwargs_different_key(self):
        k1 = _default_key_builder((), {"x": 1})
        k2 = _default_key_builder((), {"x": 2})
        assert k1 != k2

    def test_is_md5_hex(self):
        key = _default_key_builder(("test",), {})
        assert len(key) == 32  # MD5 hex digest length


# ---------------------------------------------------------------------------
# cached decorator
# ---------------------------------------------------------------------------


class TestCachedDecorator:
    """Tests for the @cached decorator."""

    @pytest.fixture(autouse=True)
    def clean_registry(self):
        saved = dict(_caches)
        _caches.clear()
        yield
        _caches.clear()
        _caches.update(saved)

    async def test_basic_caching(self):
        call_count = 0

        @cached("test_basic", ttl=60)
        async def compute(x: int) -> int:
            nonlocal call_count
            call_count += 1
            return x * 2

        result1 = await compute(5)
        result2 = await compute(5)
        assert result1 == 10
        assert result2 == 10
        assert call_count == 1  # second call was cached

    async def test_different_args_not_cached(self):
        call_count = 0

        @cached("test_diff_args", ttl=60)
        async def compute(x: int) -> int:
            nonlocal call_count
            call_count += 1
            return x * 2

        await compute(1)
        await compute(2)
        assert call_count == 2

    async def test_custom_key_builder(self):
        call_count = 0

        @cached("test_key_builder", ttl=60, key_builder=lambda q, **kw: f"query:{q}")
        async def search(query: str, limit: int = 10) -> str:
            nonlocal call_count
            call_count += 1
            return f"results for {query}"

        r1 = await search("hello", limit=5)
        r2 = await search("hello", limit=20)  # Same key due to key_builder
        assert r1 == r2
        assert call_count == 1

    async def test_failing_key_builder_falls_back(self):
        @cached("test_fallback", ttl=60, key_builder=lambda: None)  # wrong signature
        async def compute(x: int) -> int:
            return x * 2

        # Should not raise, falls back to default key builder
        result = await compute(5)
        assert result == 10

    async def test_decorator_attaches_cache(self):
        @cached("test_attach", ttl=60)
        async def compute(x: int) -> int:
            return x

        assert hasattr(compute, "_cache")
        assert hasattr(compute, "_cache_name")
        assert compute._cache_name == "test_attach"
        assert isinstance(compute._cache, TTLCache)

    async def test_caching_none_value(self):
        call_count = 0

        @cached("test_none", ttl=60)
        async def return_none() -> None:
            nonlocal call_count
            call_count += 1
            return None

        r1 = await return_none()
        r2 = await return_none()
        assert r1 is None
        assert r2 is None
        assert call_count == 1  # None was cached


# ---------------------------------------------------------------------------
# invalidate_cache
# ---------------------------------------------------------------------------


class TestInvalidateCache:
    """Tests for the invalidate_cache function."""

    @pytest.fixture(autouse=True)
    def clean_registry(self):
        saved = dict(_caches)
        _caches.clear()
        yield
        _caches.clear()
        _caches.update(saved)

    async def test_invalidate_nonexistent_cache(self):
        result = await invalidate_cache("does_not_exist")
        assert result is False

    async def test_invalidate_specific_key(self):
        cache = get_cache("inv_test", ttl_seconds=60)
        await cache.set("k1", "v1")
        await cache.set("k2", "v2")
        result = await invalidate_cache("inv_test", key="k1")
        assert result is True
        hit, _ = await cache.get("k1")
        assert hit is False
        hit, _ = await cache.get("k2")
        assert hit is True

    async def test_invalidate_entire_cache(self):
        cache = get_cache("inv_all", ttl_seconds=60)
        await cache.set("a", 1)
        await cache.set("b", 2)
        result = await invalidate_cache("inv_all")
        assert result is True
        hit_a, _ = await cache.get("a")
        hit_b, _ = await cache.get("b")
        assert hit_a is False
        assert hit_b is False

    async def test_invalidate_empty_cache_returns_false(self):
        get_cache("inv_empty", ttl_seconds=60)
        result = await invalidate_cache("inv_empty")
        assert result is False
