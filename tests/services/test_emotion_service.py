"""Tests for backend.core.services.emotion_service."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── Synchronous: classify_emotion_sync ───────────────────────────────────


class TestClassifyEmotionSync:
    def test_empty_text_returns_neutral(self):
        from backend.core.services.emotion_service import classify_emotion_sync

        assert classify_emotion_sync("") == "neutral"

    def test_none_text_returns_neutral(self):
        from backend.core.services.emotion_service import classify_emotion_sync

        assert classify_emotion_sync(None) == "neutral"

    def test_short_text_returns_neutral(self):
        """Single character text (< 2 chars stripped) -> neutral."""
        from backend.core.services.emotion_service import classify_emotion_sync

        assert classify_emotion_sync("x") == "neutral"
        assert classify_emotion_sync(" ") == "neutral"

    @pytest.mark.parametrize("label", ["positive", "negative", "neutral", "mixed"])
    def test_valid_label(self, label):
        mock_response = MagicMock()
        mock_response.text = f"  {label.upper()}  "  # test strip+lower

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response

        with (
            patch(
                "backend.core.services.emotion_service.get_gemini_client",
                return_value=mock_client,
            ),
            patch(
                "backend.core.services.emotion_service.get_model_name",
                return_value="gemini-flash",
            ),
        ):
            from backend.core.services.emotion_service import classify_emotion_sync

            result = classify_emotion_sync("I am so happy today!")
            assert result == label

    def test_invalid_label_returns_neutral(self):
        mock_response = MagicMock()
        mock_response.text = "joyful"  # not in valid set

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response

        with (
            patch(
                "backend.core.services.emotion_service.get_gemini_client",
                return_value=mock_client,
            ),
            patch(
                "backend.core.services.emotion_service.get_model_name",
                return_value="gemini-flash",
            ),
        ):
            from backend.core.services.emotion_service import classify_emotion_sync

            assert classify_emotion_sync("I feel joyful") == "neutral"

    def test_empty_response_returns_neutral(self):
        mock_response = MagicMock()
        mock_response.text = ""

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response

        with (
            patch(
                "backend.core.services.emotion_service.get_gemini_client",
                return_value=mock_client,
            ),
            patch(
                "backend.core.services.emotion_service.get_model_name",
                return_value="gemini-flash",
            ),
        ):
            from backend.core.services.emotion_service import classify_emotion_sync

            assert classify_emotion_sync("hello there") == "neutral"

    def test_none_response_text_returns_neutral(self):
        mock_response = MagicMock()
        mock_response.text = None

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response

        with (
            patch(
                "backend.core.services.emotion_service.get_gemini_client",
                return_value=mock_client,
            ),
            patch(
                "backend.core.services.emotion_service.get_model_name",
                return_value="gemini-flash",
            ),
        ):
            from backend.core.services.emotion_service import classify_emotion_sync

            assert classify_emotion_sync("hello there") == "neutral"

    def test_exception_returns_neutral(self):
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = RuntimeError("API down")

        with (
            patch(
                "backend.core.services.emotion_service.get_gemini_client",
                return_value=mock_client,
            ),
            patch(
                "backend.core.services.emotion_service.get_model_name",
                return_value="gemini-flash",
            ),
        ):
            from backend.core.services.emotion_service import classify_emotion_sync

            assert classify_emotion_sync("something went wrong") == "neutral"

    def test_get_gemini_client_raises_returns_neutral(self):
        """If get_gemini_client itself raises, still return neutral."""
        with patch(
            "backend.core.services.emotion_service.get_gemini_client",
            side_effect=RuntimeError("no API key"),
        ):
            from backend.core.services.emotion_service import classify_emotion_sync

            assert classify_emotion_sync("test text") == "neutral"


# ── Asynchronous: classify_emotion ───────────────────────────────────────


class TestClassifyEmotion:
    async def test_empty_text_returns_neutral(self):
        from backend.core.services.emotion_service import classify_emotion

        assert await classify_emotion("") == "neutral"

    async def test_none_text_returns_neutral(self):
        from backend.core.services.emotion_service import classify_emotion

        assert await classify_emotion(None) == "neutral"

    async def test_short_text_returns_neutral(self):
        from backend.core.services.emotion_service import classify_emotion

        assert await classify_emotion("a") == "neutral"
        assert await classify_emotion("  ") == "neutral"

    @pytest.mark.parametrize("label", ["positive", "negative", "neutral", "mixed"])
    async def test_valid_label(self, label):
        mock_response = MagicMock()
        mock_response.text = label

        with patch(
            "backend.core.services.emotion_service.gemini_generate",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            from backend.core.services.emotion_service import classify_emotion

            result = await classify_emotion("I love this conversation!")
            assert result == label

    async def test_valid_label_with_whitespace(self):
        mock_response = MagicMock()
        mock_response.text = "  Positive \n"

        with patch(
            "backend.core.services.emotion_service.gemini_generate",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            from backend.core.services.emotion_service import classify_emotion

            result = await classify_emotion("great day!")
            assert result == "positive"

    async def test_invalid_label_returns_neutral(self):
        mock_response = MagicMock()
        mock_response.text = "happy"

        with patch(
            "backend.core.services.emotion_service.gemini_generate",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            from backend.core.services.emotion_service import classify_emotion

            assert await classify_emotion("I'm happy") == "neutral"

    async def test_empty_response_returns_neutral(self):
        mock_response = MagicMock()
        mock_response.text = ""

        with patch(
            "backend.core.services.emotion_service.gemini_generate",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            from backend.core.services.emotion_service import classify_emotion

            assert await classify_emotion("hello world") == "neutral"

    async def test_none_response_text_returns_neutral(self):
        mock_response = MagicMock()
        mock_response.text = None

        with patch(
            "backend.core.services.emotion_service.gemini_generate",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            from backend.core.services.emotion_service import classify_emotion

            assert await classify_emotion("hello world") == "neutral"

    async def test_exception_returns_neutral(self):
        with patch(
            "backend.core.services.emotion_service.gemini_generate",
            new_callable=AsyncMock,
            side_effect=RuntimeError("timeout"),
        ):
            from backend.core.services.emotion_service import classify_emotion

            assert await classify_emotion("this should fail gracefully") == "neutral"

    async def test_text_truncated_to_500(self):
        """Verify that very long input is clipped before sending to model."""
        mock_response = MagicMock()
        mock_response.text = "positive"

        mock_generate = AsyncMock(return_value=mock_response)
        with patch(
            "backend.core.services.emotion_service.gemini_generate",
            mock_generate,
        ):
            from backend.core.services.emotion_service import classify_emotion

            # Build text where the tail portion cannot appear in the head
            head = "A" * 500
            tail = "Z" * 500
            long_text = head + tail
            assert len(long_text) == 1000

            await classify_emotion(long_text)

            call_kwargs = mock_generate.call_args
            contents_arg = call_kwargs.kwargs.get("contents") or call_kwargs[0][0]
            # The prompt should contain exactly the first 500 chars
            assert head in contents_arg
            # The tail portion (all Z's) should NOT appear because text[:500] is all A's
            assert "ZZZZ" not in contents_arg
