"""Tests for backend.memory.permanent.importance — importance scoring.

Mocks Gemini client calls to test importance calculation logic.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.memory.permanent.importance import (
    _build_importance_prompt,
    _parse_importance,
    calculate_importance_async,
    calculate_importance_sync,
    IMPORTANCE_TIMEOUT_SECONDS,
)


# ── _build_importance_prompt ─────────────────────────────────────────────

class TestBuildImportancePrompt:

    def test_basic_prompt_structure(self):
        prompt = _build_importance_prompt("hi", "hello", "")
        assert "User: hi" in prompt
        assert "AI: hello" in prompt
        assert "중요도 기준" in prompt

    def test_truncates_long_user_msg(self):
        long_msg = "a" * 1000
        prompt = _build_importance_prompt(long_msg, "ok", "")
        # User message should be truncated to 500 chars
        assert "a" * 500 in prompt
        assert "a" * 501 not in prompt

    def test_truncates_long_ai_msg(self):
        long_msg = "b" * 1000
        prompt = _build_importance_prompt("hi", long_msg, "")
        assert "b" * 500 in prompt
        assert "b" * 501 not in prompt

    def test_truncates_long_persona_context(self):
        long_persona = "c" * 500
        prompt = _build_importance_prompt("hi", "ok", long_persona)
        assert "c" * 200 in prompt
        assert "c" * 201 not in prompt

    def test_no_persona_context(self):
        prompt = _build_importance_prompt("hi", "ok", "")
        assert "없음" in prompt

    def test_with_persona_context(self):
        prompt = _build_importance_prompt("hi", "ok", "friendly assistant")
        assert "friendly assistant" in prompt


# ── _parse_importance ────────────────────────────────────────────────────

class TestParseImportance:

    def test_parses_decimal(self):
        assert _parse_importance("0.75") == 0.75

    def test_parses_with_surrounding_text(self):
        assert _parse_importance("The importance is 0.85.") == 0.85

    def test_parses_one_point_zero(self):
        assert _parse_importance("1.0") == 1.0

    def test_parses_integer_one(self):
        assert _parse_importance("1") == 1.0

    def test_parses_low_score(self):
        assert _parse_importance("0.15") == 0.15

    def test_empty_string_returns_default(self):
        assert _parse_importance("") == 0.7

    def test_no_match_returns_default(self):
        assert _parse_importance("no number here") == 0.7

    def test_whitespace_handling(self):
        assert _parse_importance("  0.65  ") == 0.65

    def test_multiline_response(self):
        text = "Based on the analysis:\n0.80\nThis is important."
        assert _parse_importance(text) == 0.80

    def test_json_like_response(self):
        text = '{"importance": 0.90}'
        assert _parse_importance(text) == 0.90

    def test_zero_score(self):
        assert _parse_importance("0.0") == 0.0

    def test_first_match_wins(self):
        """When multiple numbers are present, the first one is returned."""
        assert _parse_importance("0.3 and 0.9") == 0.3


# ── calculate_importance_async ───────────────────────────────────────────

class TestCalculateImportanceAsync:

    async def test_successful_calculation(self):
        mock_response = MagicMock()
        mock_response.text = "0.85"

        with patch(
            "backend.memory.permanent.importance.gemini_generate",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            score = await calculate_importance_async("What's your name?", "I'm Axel")

        assert score == 0.85

    async def test_timeout_returns_default(self):
        with patch(
            "backend.memory.permanent.importance.gemini_generate",
            new_callable=AsyncMock,
            side_effect=TimeoutError("timed out"),
        ):
            score = await calculate_importance_async("test", "test")

        assert score == 0.7

    async def test_general_error_returns_default(self):
        with patch(
            "backend.memory.permanent.importance.gemini_generate",
            new_callable=AsyncMock,
            side_effect=RuntimeError("API error"),
        ):
            score = await calculate_importance_async("test", "test")

        assert score == 0.7

    async def test_empty_response_returns_default(self):
        mock_response = MagicMock()
        mock_response.text = None

        with patch(
            "backend.memory.permanent.importance.gemini_generate",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            score = await calculate_importance_async("test", "test")

        assert score == 0.7

    async def test_persona_context_passed(self):
        mock_response = MagicMock()
        mock_response.text = "0.9"

        with patch(
            "backend.memory.permanent.importance.gemini_generate",
            new_callable=AsyncMock,
            return_value=mock_response,
        ) as mock_gen:
            score = await calculate_importance_async(
                "My name is Alice", "Nice to meet you!", persona_context="friendly bot"
            )

        assert score == 0.9
        # Verify the prompt includes persona context
        call_args = mock_gen.call_args
        assert "friendly bot" in call_args[1]["contents"]

    async def test_timeout_seconds_is_passed(self):
        mock_response = MagicMock()
        mock_response.text = "0.5"

        with patch(
            "backend.memory.permanent.importance.gemini_generate",
            new_callable=AsyncMock,
            return_value=mock_response,
        ) as mock_gen:
            await calculate_importance_async("test", "test")

        mock_gen.assert_called_once()
        assert mock_gen.call_args[1]["timeout_seconds"] == IMPORTANCE_TIMEOUT_SECONDS


# ── calculate_importance_sync ────────────────────────────────────────────

class TestCalculateImportanceSync:

    def test_successful_calculation(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "0.65"
        mock_client.models.generate_content.return_value = mock_response

        with patch(
            "backend.memory.permanent.importance.get_gemini_client",
            return_value=mock_client,
        ), patch(
            "backend.memory.permanent.importance.get_model_name",
            return_value="test-model",
        ):
            score = calculate_importance_sync("How's work?", "It's going well")

        assert score == 0.65

    def test_timeout_returns_default(self):
        with patch(
            "backend.memory.permanent.importance.get_gemini_client",
            side_effect=TimeoutError("timeout"),
        ):
            score = calculate_importance_sync("test", "test")

        assert score == 0.7

    def test_general_error_returns_default(self):
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = RuntimeError("API error")

        with patch(
            "backend.memory.permanent.importance.get_gemini_client",
            return_value=mock_client,
        ), patch(
            "backend.memory.permanent.importance.get_model_name",
            return_value="test-model",
        ):
            score = calculate_importance_sync("test", "test")

        assert score == 0.7

    def test_empty_response_returns_default(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = ""
        mock_client.models.generate_content.return_value = mock_response

        with patch(
            "backend.memory.permanent.importance.get_gemini_client",
            return_value=mock_client,
        ), patch(
            "backend.memory.permanent.importance.get_model_name",
            return_value="test-model",
        ):
            score = calculate_importance_sync("test", "test")

        assert score == 0.7

    def test_with_persona_context(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "0.9"
        mock_client.models.generate_content.return_value = mock_response

        with patch(
            "backend.memory.permanent.importance.get_gemini_client",
            return_value=mock_client,
        ), patch(
            "backend.memory.permanent.importance.get_model_name",
            return_value="test-model",
        ):
            score = calculate_importance_sync(
                "My name is Bob", "Hi Bob!", persona_context="caring assistant"
            )

        assert score == 0.9


# ── Constants ────────────────────────────────────────────────────────────

class TestConstants:

    def test_importance_timeout_is_positive(self):
        assert IMPORTANCE_TIMEOUT_SECONDS > 0
        assert isinstance(IMPORTANCE_TIMEOUT_SECONDS, (int, float))
