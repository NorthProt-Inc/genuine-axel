"""Tests for truncate_text utility."""

import pytest

from backend.core.utils.text import truncate_text


SUFFIX = "\n... (truncated)"


class TestTruncateText:
    """Unit tests for truncate_text()."""

    def test_returns_empty_for_none(self) -> None:
        assert truncate_text(None, 100) == ""

    def test_returns_empty_for_empty_string(self) -> None:
        assert truncate_text("", 100) == ""

    def test_returns_original_when_under_limit(self) -> None:
        text = "short"
        assert truncate_text(text, 100) == text

    def test_returns_original_when_exactly_at_limit(self) -> None:
        text = "x" * 50
        assert truncate_text(text, 50) == text

    def test_truncates_with_suffix_when_over_limit(self) -> None:
        text = "a" * 100
        result = truncate_text(text, 50)
        assert result.endswith(SUFFIX)
        assert len(result) <= 50

    def test_returns_empty_for_zero_max_chars(self) -> None:
        assert truncate_text("hello", 0) == ""

    def test_returns_empty_for_negative_max_chars(self) -> None:
        assert truncate_text("hello", -5) == ""

    def test_strips_trailing_whitespace_before_suffix(self) -> None:
        # Build text where the cut point lands on trailing whitespace
        text = "word   " + "x" * 100
        result = truncate_text(text, 25)
        # Should not have whitespace immediately before the suffix
        before_suffix = result[: result.index(SUFFIX)]
        assert not before_suffix.endswith(" ")

    def test_handles_very_small_limit(self) -> None:
        # When max_chars is smaller than the suffix length, fallback to hard cut
        text = "abcdefghij"
        result = truncate_text(text, 5)
        assert result == "abcde"
        assert len(result) == 5

    def test_consistent_output(self) -> None:
        text = "a" * 100
        result1 = truncate_text(text, 50)
        result2 = truncate_text(text, 50)
        assert result1 == result2

    @pytest.mark.parametrize(
        "max_chars",
        [len(SUFFIX), len(SUFFIX) + 1, len(SUFFIX) + 5],
    )
    def test_boundary_around_suffix_length(self, max_chars: int) -> None:
        text = "x" * 200
        result = truncate_text(text, max_chars)
        assert len(result) <= max_chars
