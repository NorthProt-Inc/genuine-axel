"""Tests for Link Pipeline enhancement (Wave 4.3)."""

import pytest

from backend.core.tools.link_pipeline import (
    extract_urls,
    calculate_importance,
    LinkCache,
)


class TestExtractUrls:

    def test_single_url(self):
        urls = extract_urls("Check https://example.com for details")
        assert urls == ["https://example.com"]

    def test_multiple_urls(self):
        text = "Visit https://a.com and http://b.com"
        urls = extract_urls(text)
        assert len(urls) == 2

    def test_no_urls(self):
        urls = extract_urls("No URLs here")
        assert urls == []


class TestCalculateImportance:

    def test_base_importance(self):
        score = calculate_importance("regular text")
        assert score == 0.4

    def test_keyword_boost(self):
        score = calculate_importance("this is important data")
        assert score > 0.4

    def test_max_cap(self):
        score = calculate_importance("important 중요 기억 save 저장 remember")
        assert score <= 1.0


class TestLinkCache:

    def test_set_and_get(self):
        cache = LinkCache(max_size=10)
        cache.set("https://example.com", {"content": "hello"})
        assert cache.get("https://example.com") == {"content": "hello"}

    def test_cache_miss(self):
        cache = LinkCache(max_size=10)
        assert cache.get("https://missing.com") is None

    def test_eviction_on_max_size(self):
        cache = LinkCache(max_size=2)
        cache.set("url1", "a")
        cache.set("url2", "b")
        cache.set("url3", "c")
        assert cache.get("url1") is None
        assert cache.get("url3") == "c"

    def test_has(self):
        cache = LinkCache(max_size=10)
        cache.set("url1", "data")
        assert cache.has("url1") is True
        assert cache.has("url2") is False

    def test_clear(self):
        cache = LinkCache(max_size=10)
        cache.set("url1", "data")
        cache.clear()
        assert cache.get("url1") is None
