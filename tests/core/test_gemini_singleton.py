"""Tests for gemini_client singleton via Lazy[T]."""

from unittest.mock import patch, MagicMock

from backend.core.utils.gemini_client import get_gemini_client


class TestGeminiSingleton:
    """get_gemini_client() should use Lazy[T] pattern."""

    @patch("backend.core.utils.gemini_client.genai")
    @patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"})
    def test_returns_same_instance(self, mock_genai: MagicMock) -> None:
        first = get_gemini_client()
        second = get_gemini_client()
        assert first is second

    @patch("backend.core.utils.gemini_client.genai")
    @patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"})
    def test_reset_creates_new_instance(self, mock_genai: MagicMock) -> None:
        from backend.core.utils.lazy import Lazy

        # Make genai.Client return distinct objects each call
        mock_genai.Client.side_effect = [MagicMock(name="client_1"), MagicMock(name="client_2")]

        first = get_gemini_client()
        Lazy.reset_all()
        second = get_gemini_client()
        assert first is not second
