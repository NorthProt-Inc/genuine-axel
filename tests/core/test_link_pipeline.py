"""Tests for link content pipeline."""

import asyncio
import pytest
from backend.core.tools.link_pipeline import (
    extract_urls,
    calculate_importance,
    IMPORTANCE_BASE,
)


class TestLinkPipeline:

    def test_extract_urls(self):
        text = "Check out https://example.com and http://test.org/page"
        urls = extract_urls(text)
        assert len(urls) == 2
        assert "https://example.com" in urls

    def test_extract_no_urls(self):
        urls = extract_urls("no urls here")
        assert urls == []

    def test_importance_boost_keywords(self):
        importance = calculate_importance("\uc774\uac74 \uc911\uc694\ud55c \ub0b4\uc6a9\uc774\uc57c")
        assert importance > IMPORTANCE_BASE

    def test_importance_base_without_keywords(self):
        importance = calculate_importance("just some text")
        assert importance == IMPORTANCE_BASE

    def test_importance_capped_at_1(self):
        importance = calculate_importance("important \uc911\uc694 remember")
        assert importance <= 1.0

    def test_empty_url_returns_none(self):
        """Empty URL should return None."""
        # Test the sync check only
        from backend.core.tools.link_pipeline import ingest_url
        result = asyncio.get_event_loop().run_until_complete(ingest_url(""))
        assert result is None

    def test_invalid_url_returns_none(self):
        from backend.core.tools.link_pipeline import ingest_url
        result = asyncio.get_event_loop().run_until_complete(ingest_url("not-a-url"))
        assert result is None
