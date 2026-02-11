"""Tests for backend.core.context_optimizer."""

import pytest
from unittest.mock import patch
from backend.core.context_optimizer import (
    ContextOptimizer,
    SectionBudget,
    TIER_BUDGETS,
    get_dynamic_system_prompt,
)


# ---------------------------------------------------------------------------
# SectionBudget dataclass
# ---------------------------------------------------------------------------


class TestSectionBudget:
    """Tests for the SectionBudget dataclass."""

    def test_effective_max_tokens_from_explicit(self):
        sb = SectionBudget(name="test", max_chars=800, priority=1, max_tokens=200)
        assert sb.effective_max_tokens() == 200

    def test_effective_max_tokens_derived_from_chars(self):
        sb = SectionBudget(name="test", max_chars=800, priority=1, max_tokens=0)
        assert sb.effective_max_tokens() == 200  # 800 // 4

    def test_effective_max_tokens_zero_chars(self):
        sb = SectionBudget(name="test", max_chars=0, priority=1, max_tokens=0)
        assert sb.effective_max_tokens() == 0

    def test_default_overflow_strategy(self):
        sb = SectionBudget(name="test", max_chars=100, priority=1)
        assert sb.overflow_strategy == "truncate"

    def test_default_header_template(self):
        sb = SectionBudget(name="test", max_chars=100, priority=1)
        assert sb.header_template == "## {name}"


# ---------------------------------------------------------------------------
# ContextOptimizer
# ---------------------------------------------------------------------------


class TestContextOptimizer:
    """Tests for the ContextOptimizer class."""

    def test_init_default_tier(self):
        opt = ContextOptimizer()
        assert opt.tier == "axel"
        assert opt.budgets is TIER_BUDGETS["axel"]

    def test_init_invalid_tier_falls_back_to_axel(self):
        opt = ContextOptimizer(tier="nonexistent_tier")
        assert opt.tier == "axel"

    def test_init_stats_are_zeroed(self):
        opt = ContextOptimizer()
        stats = opt.get_stats()
        assert stats["sections_added"] == 0
        assert stats["sections_truncated"] == 0
        assert stats["sections_summarized"] == 0
        assert stats["sections_dropped"] == 0
        assert stats["total_chars_raw"] == 0
        assert stats["total_chars_final"] == 0

    # -- add_section ---------------------------------------------------------

    def test_add_section_empty_content_ignored(self):
        opt = ContextOptimizer()
        opt.add_section("system_prompt", "")
        assert opt.sections == {}
        assert opt.get_stats()["sections_added"] == 0

    def test_add_section_whitespace_only_ignored(self):
        opt = ContextOptimizer()
        opt.add_section("system_prompt", "   \n\t  ")
        assert opt.sections == {}

    def test_add_section_none_content_ignored(self):
        opt = ContextOptimizer()
        opt.add_section("system_prompt", None)
        assert opt.sections == {}

    def test_add_section_known_section(self):
        opt = ContextOptimizer()
        opt.add_section("system_prompt", "Hello world")
        assert "system_prompt" in opt.sections
        assert opt.get_stats()["sections_added"] == 1

    def test_add_section_unknown_section_uses_default_budget(self):
        opt = ContextOptimizer()
        opt.add_section("totally_unknown", "Some content")
        assert "totally_unknown" in opt.sections
        assert opt.get_stats()["sections_added"] == 1

    def test_add_section_content_within_budget_unchanged(self):
        opt = ContextOptimizer()
        content = "Short content"
        opt.add_section("system_prompt", content)
        assert opt.sections["system_prompt"] == content

    def test_add_section_content_exceeding_budget_truncated(self):
        opt = ContextOptimizer()
        budget = opt.budgets["system_prompt"]
        content = "x" * (budget.max_chars + 1000)
        opt.add_section("system_prompt", content)
        assert len(opt.sections["system_prompt"]) <= budget.max_chars
        assert opt.get_stats()["sections_truncated"] == 1

    def test_add_section_tracks_raw_chars(self):
        opt = ContextOptimizer()
        content = "abcde"
        opt.add_section("system_prompt", content)
        assert opt.get_stats()["total_chars_raw"] == 5

    def test_add_section_tracks_final_chars(self):
        opt = ContextOptimizer()
        content = "abcde"
        opt.add_section("system_prompt", content)
        assert opt.get_stats()["total_chars_final"] == 5

    # -- _apply_budget -------------------------------------------------------

    def test_apply_budget_zero_max_chars_drops(self):
        opt = ContextOptimizer()
        budget = SectionBudget(name="test", max_chars=0, priority=1)
        result = opt._apply_budget("Hello", budget)
        assert result == ""
        assert opt.get_stats()["sections_dropped"] == 1

    def test_apply_budget_negative_max_chars_drops(self):
        opt = ContextOptimizer()
        budget = SectionBudget(name="test", max_chars=-10, priority=1)
        result = opt._apply_budget("Hello", budget)
        assert result == ""

    def test_apply_budget_truncate_strategy(self):
        opt = ContextOptimizer()
        budget = SectionBudget(name="test", max_chars=20, priority=1, overflow_strategy="truncate")
        result = opt._apply_budget("a" * 100, budget)
        assert len(result) <= 20

    def test_apply_budget_drop_strategy(self):
        opt = ContextOptimizer()
        budget = SectionBudget(name="test", max_chars=5, priority=1, overflow_strategy="drop")
        result = opt._apply_budget("a" * 100, budget)
        assert result == ""
        assert opt.get_stats()["sections_dropped"] == 1

    def test_apply_budget_summarize_strategy_few_turns_truncates(self):
        """When content has <= 3 turns, summarize falls back to truncate."""
        opt = ContextOptimizer()
        budget = SectionBudget(
            name="test", max_chars=50, priority=1, overflow_strategy="summarize"
        )
        content = "Short text that exceeds budget but has no turn markers at all " * 5
        result = opt._apply_budget(content, budget)
        assert len(result) <= 50
        assert opt.get_stats()["sections_summarized"] == 1

    def test_apply_budget_summarize_strategy_many_turns(self):
        """When content has many turns, summarize produces a summary + recent turns."""
        opt = ContextOptimizer()
        budget = SectionBudget(
            name="test", max_chars=800, priority=1, overflow_strategy="summarize"
        )
        turns = [f"[User]: Message number {i} with some extra text padding here." for i in range(20)]
        content = "\n\n".join(turns)
        result = opt._apply_budget(content, budget)
        # Summarize keeps recent turns and adds a summary header for older ones.
        # The result should be significantly shorter than raw input.
        assert len(result) < len(content)
        assert opt.get_stats()["sections_summarized"] == 1
        # Should contain the summary header for older messages
        assert "이전 대화 요약" in result

    def test_apply_budget_token_based_limit(self):
        """Token-based budget (max_tokens * 4) can be stricter than max_chars."""
        opt = ContextOptimizer()
        # max_tokens=10 => 40 chars effective, even though max_chars=200
        budget = SectionBudget(
            name="test", max_chars=200, priority=1, max_tokens=10, overflow_strategy="truncate"
        )
        content = "x" * 100  # exceeds 40 char effective limit
        result = opt._apply_budget(content, budget)
        # Should be truncated to max_chars (200) since truncate uses max_chars
        assert len(result) <= 200

    # -- build ---------------------------------------------------------------

    def test_build_empty_sections_returns_empty(self):
        opt = ContextOptimizer()
        assert opt.build() == ""

    def test_build_single_section_with_header(self):
        opt = ContextOptimizer()
        opt.add_section("temporal", "Some temporal context")
        result = opt.build()
        # temporal has header_template "## {name}" and name "대화 맥락"
        assert "## 대화 맥락" in result
        assert "Some temporal context" in result

    def test_build_system_prompt_no_header(self):
        """system_prompt has empty header_template, so no header line."""
        opt = ContextOptimizer()
        opt.add_section("system_prompt", "You are Axel.")
        result = opt.build()
        assert "You are Axel." in result
        # Should not have a "## " prefix for system prompt
        assert "## " not in result

    def test_build_multiple_sections_joined(self):
        opt = ContextOptimizer()
        opt.add_section("system_prompt", "System content")
        opt.add_section("temporal", "Temporal content")
        result = opt.build()
        assert "System content" in result
        assert "Temporal content" in result

    def test_build_sections_sorted_by_priority(self):
        opt = ContextOptimizer()
        # event_buffer has priority 2, system_prompt has priority 1
        opt.add_section("event_buffer", "Event data")
        opt.add_section("system_prompt", "System data")
        result = opt.build()
        # Priority 1 sections should come before priority 2
        sys_pos = result.index("System data")
        event_pos = result.index("Event data")
        assert sys_pos < event_pos

    # -- format_as_bullets ---------------------------------------------------

    def test_format_as_bullets_empty_list(self):
        opt = ContextOptimizer()
        assert opt.format_as_bullets([]) == ""

    def test_format_as_bullets_single_item(self):
        opt = ContextOptimizer()
        result = opt.format_as_bullets(["Hello"])
        assert result == "- Hello"

    def test_format_as_bullets_multiple_items(self):
        opt = ContextOptimizer()
        result = opt.format_as_bullets(["A", "B", "C"])
        lines = result.split("\n")
        assert len(lines) == 3
        assert lines[0] == "- A"
        assert lines[1] == "- B"
        assert lines[2] == "- C"

    def test_format_as_bullets_max_items(self):
        opt = ContextOptimizer()
        items = [f"Item {i}" for i in range(15)]
        result = opt.format_as_bullets(items, max_items=5)
        lines = result.split("\n")
        assert len(lines) == 6  # 5 items + 1 "... (10 more)"
        assert "10 more" in lines[-1]

    def test_format_as_bullets_long_item_truncated(self):
        opt = ContextOptimizer()
        long_item = "x" * 300
        result = opt.format_as_bullets([long_item])
        assert len(result) < 300
        assert result.endswith("...")

    def test_format_as_bullets_whitespace_stripped(self):
        opt = ContextOptimizer()
        result = opt.format_as_bullets(["  padded  "])
        assert result == "- padded"

    def test_format_as_bullets_empty_items_skipped(self):
        opt = ContextOptimizer()
        result = opt.format_as_bullets(["A", "", "  ", "B"])
        lines = result.split("\n")
        assert len(lines) == 2
        assert lines[0] == "- A"
        assert lines[1] == "- B"

    # -- get_stats -----------------------------------------------------------

    def test_get_stats_returns_copy(self):
        opt = ContextOptimizer()
        stats1 = opt.get_stats()
        stats1["sections_added"] = 999
        stats2 = opt.get_stats()
        assert stats2["sections_added"] == 0

    def test_get_stats_reflects_operations(self):
        opt = ContextOptimizer()
        opt.add_section("system_prompt", "content")
        opt.add_section("temporal", "more content")
        stats = opt.get_stats()
        assert stats["sections_added"] == 2

    # -- _split_turns --------------------------------------------------------

    def test_split_turns_user_assistant(self):
        opt = ContextOptimizer()
        content = "[User]: Hello\n[Assistant]: Hi there"
        turns = opt._split_turns(content)
        assert len(turns) == 2

    def test_split_turns_no_markers(self):
        opt = ContextOptimizer()
        content = "Just some plain text without markers"
        turns = opt._split_turns(content)
        assert len(turns) == 1
        assert turns[0] == content

    def test_split_turns_time_markers(self):
        opt = ContextOptimizer()
        content = "[5분] Something happened\n[User]: Then this"
        turns = opt._split_turns(content)
        assert len(turns) >= 2


# ---------------------------------------------------------------------------
# get_dynamic_system_prompt
# ---------------------------------------------------------------------------


class TestGetDynamicSystemPrompt:
    """Tests for the get_dynamic_system_prompt function."""

    def test_short_prompt_returned_as_is(self):
        prompt = "Short prompt"
        result = get_dynamic_system_prompt("axel", prompt)
        assert result == prompt

    def test_long_prompt_truncated(self):
        budget = TIER_BUDGETS["axel"]["system_prompt"]
        prompt = "x" * (budget.max_chars + 500)
        result = get_dynamic_system_prompt("axel", prompt)
        assert len(result) <= budget.max_chars
        assert result.endswith("... (truncated)")

    def test_unknown_tier_falls_back_to_axel(self):
        prompt = "Hello"
        result = get_dynamic_system_prompt("nonexistent", prompt)
        assert result == prompt

    def test_exact_budget_length_not_truncated(self):
        budget = TIER_BUDGETS["axel"]["system_prompt"]
        prompt = "x" * budget.max_chars
        result = get_dynamic_system_prompt("axel", prompt)
        assert result == prompt


# ---------------------------------------------------------------------------
# TIER_BUDGETS structure validation
# ---------------------------------------------------------------------------


class TestTierBudgets:
    """Validate the TIER_BUDGETS configuration dict."""

    def test_axel_tier_exists(self):
        assert "axel" in TIER_BUDGETS

    def test_axel_has_required_sections(self):
        required = {"system_prompt", "temporal", "working_memory", "long_term", "graphrag", "session_archive"}
        assert required.issubset(TIER_BUDGETS["axel"].keys())

    def test_all_budgets_are_section_budget(self):
        for section_name, budget in TIER_BUDGETS["axel"].items():
            assert isinstance(budget, SectionBudget), f"{section_name} is not SectionBudget"

    def test_system_prompt_has_empty_header_template(self):
        assert TIER_BUDGETS["axel"]["system_prompt"].header_template == ""

    def test_event_buffer_has_token_budget(self):
        eb = TIER_BUDGETS["axel"]["event_buffer"]
        assert eb.max_tokens == 200
        assert eb.effective_max_tokens() == 200

    def test_meta_memory_has_token_budget(self):
        mm = TIER_BUDGETS["axel"]["meta_memory"]
        assert mm.max_tokens == 150
        assert mm.effective_max_tokens() == 150
