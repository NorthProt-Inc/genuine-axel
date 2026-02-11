"""Tests for T-09: Token-based Context Budget."""

import pytest

from backend.core.context_optimizer import (
    ContextOptimizer,
    SectionBudget,
    TIER_BUDGETS,
)


class TestTokenBudgetAllocation:

    def test_max_tokens_property(self):
        """SectionBudget.effective_max_tokens() returns correct value."""
        # Explicit max_tokens
        b1 = SectionBudget(name="test", max_chars=2000, priority=1, max_tokens=500)
        assert b1.effective_max_tokens() == 500

        # Derived from max_chars
        b2 = SectionBudget(name="test", max_chars=2000, priority=1, max_tokens=0)
        assert b2.effective_max_tokens() == 500  # 2000 // 4

    def test_new_sections_exist(self):
        """event_buffer and meta_memory sections are in TIER_BUDGETS."""
        axel_budgets = TIER_BUDGETS["axel"]
        assert "event_buffer" in axel_budgets
        assert "meta_memory" in axel_budgets

        eb = axel_budgets["event_buffer"]
        assert eb.max_tokens == 200
        assert eb.name == "이벤트 버퍼"

        mm = axel_budgets["meta_memory"]
        assert mm.max_tokens == 150
        assert mm.name == "메타 메모리"

    def test_eight_slot_sections(self):
        """All 8 section slots are present."""
        expected = {
            "system_prompt", "temporal", "working_memory",
            "long_term", "graphrag", "session_archive",
            "event_buffer", "meta_memory",
        }
        actual = set(TIER_BUDGETS["axel"].keys())
        assert expected == actual


class TestPriorityOrdering:

    def test_priority_ordering(self):
        """Sections are ordered by priority in build output."""
        opt = ContextOptimizer(tier="axel")

        # Add sections with different priorities
        opt.add_section("meta_memory", "hot memories: mem-1, mem-2")  # priority=2
        opt.add_section("temporal", "현재 시각: 2024-01-01")  # priority=1

        result = opt.build()

        # Priority 1 should come before priority 2
        temporal_pos = result.find("대화 맥락")
        meta_pos = result.find("메타 메모리")
        assert temporal_pos < meta_pos


class TestOverflowTruncation:

    def test_token_based_truncation(self):
        """Content exceeding token budget gets truncated."""
        opt = ContextOptimizer(tier="axel")

        # event_buffer has max_tokens=200, so max_chars = min(800, 200*4=800) = 800
        long_content = "x" * 1000  # Exceeds both limits
        opt.add_section("event_buffer", long_content)

        result = opt.build()
        # Content should be truncated
        # Find the event_buffer section content (after header)
        assert len(result) < 1000 + 100  # Some header overhead

    def test_content_within_token_budget_not_truncated(self):
        """Content within token budget passes through unchanged."""
        opt = ContextOptimizer(tier="axel")

        short_content = "hot memory: mem-1 (3 accesses)"
        opt.add_section("meta_memory", short_content)

        result = opt.build()
        assert short_content in result

    def test_token_limit_tighter_than_char_limit(self):
        """Token limit (max_tokens*4) overrides max_chars when tighter."""
        budget = SectionBudget(
            name="test",
            max_chars=4000,  # 4000 chars
            priority=1,
            max_tokens=100,  # 100 tokens ≈ 400 chars (tighter)
        )

        # Content of 500 chars exceeds 400 char token limit
        opt = ContextOptimizer(tier="axel")
        # Override the budget for testing
        opt.budgets["test_section"] = budget
        content = "a" * 500
        opt.add_section("test_section", content)

        # The content should be truncated to token limit
        stats = opt.get_stats()
        assert stats["sections_truncated"] >= 1
