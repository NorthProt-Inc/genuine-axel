"""Tests for backend.llm.clients — LLM client implementations.

Covers:
- AdaptiveTimeout calculation logic
- CircuitBreakerState transitions (closed -> open -> half-open -> closed)
- _gemini_schema_to_anthropic schema conversion
- LLMProvider dataclass and provider lookup
- get_all_providers availability check
- get_llm_client factory dispatch
- GeminiClient.generate (non-stream)
- AnthropicClient.generate (non-stream)
- _calculate_dynamic_timeout helper
"""

from __future__ import annotations

import os
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.llm.clients import (
    AdaptiveTimeout,
    AnthropicClient,
    BaseLLMClient,
    CircuitBreakerState,
    DEFAULT_PROVIDER,
    GeminiClient,
    LLMProvider,
    LLM_PROVIDERS,
    _adaptive_timeout,
    _calculate_dynamic_timeout,
    _gemini_schema_to_anthropic,
    get_all_providers,
    get_llm_client,
    get_provider,
)


# ============================================================================
# AdaptiveTimeout
# ============================================================================

class TestAdaptiveTimeout:

    def test_initial_deque_is_empty(self):
        at = AdaptiveTimeout()
        assert len(at._recent_latencies) == 0

    def test_record_latency_appends(self):
        at = AdaptiveTimeout()
        at.record_latency(1.5)
        at.record_latency(2.5)
        assert len(at._recent_latencies) == 2
        assert list(at._recent_latencies) == [1.5, 2.5]

    def test_record_latency_maxlen_10(self):
        at = AdaptiveTimeout()
        for i in range(15):
            at.record_latency(float(i))
        assert len(at._recent_latencies) == 10
        # Only the last 10 remain
        assert list(at._recent_latencies) == [float(i) for i in range(5, 15)]

    def test_calculate_non_first_chunk_returns_stream_chunk_timeout(self):
        at = AdaptiveTimeout()
        result = at.calculate(tool_count=5, model="test", is_first_chunk=False)
        from backend.core.utils.timeouts import TIMEOUTS
        assert result == TIMEOUTS.STREAM_CHUNK

    def test_calculate_first_chunk_no_tools_no_latency(self):
        at = AdaptiveTimeout()
        result = at.calculate(tool_count=0, model="test", is_first_chunk=True)
        from backend.core.utils.timeouts import TIMEOUTS
        # base + 0 tools * 2 = base, latency_factor = 1.0
        expected = TIMEOUTS.FIRST_CHUNK_BASE
        assert result == expected

    def test_calculate_first_chunk_small_tool_count(self):
        at = AdaptiveTimeout()
        result = at.calculate(tool_count=5, model="test", is_first_chunk=True)
        from backend.core.utils.timeouts import TIMEOUTS
        expected = int((TIMEOUTS.FIRST_CHUNK_BASE + 5 * 2) * 1.0)
        assert result == expected

    def test_calculate_first_chunk_medium_tool_count(self):
        at = AdaptiveTimeout()
        result = at.calculate(tool_count=15, model="test", is_first_chunk=True)
        from backend.core.utils.timeouts import TIMEOUTS
        tool_factor = 20 + ((15 - 10) * 3)  # 35
        expected = int((TIMEOUTS.FIRST_CHUNK_BASE + tool_factor) * 1.0)
        assert result == expected

    def test_calculate_first_chunk_large_tool_count(self):
        at = AdaptiveTimeout()
        result = at.calculate(tool_count=25, model="test", is_first_chunk=True)
        from backend.core.utils.timeouts import TIMEOUTS
        tool_factor = 50 + ((25 - 20) * 4)  # 70
        expected = int((TIMEOUTS.FIRST_CHUNK_BASE + tool_factor) * 1.0)
        max_timeout = TIMEOUTS.API_CALL - 10
        assert result == min(expected, max_timeout)

    def test_calculate_with_recent_latency_increases_timeout(self):
        at = AdaptiveTimeout()
        at.record_latency(30.0)  # avg = 30 -> latency_factor = 1 + 30/30 = 2.0
        result = at.calculate(tool_count=0, model="test", is_first_chunk=True)
        from backend.core.utils.timeouts import TIMEOUTS
        expected = int(TIMEOUTS.FIRST_CHUNK_BASE * 2.0)
        max_timeout = TIMEOUTS.API_CALL - 10
        assert result == min(expected, max_timeout)

    def test_calculate_latency_factor_capped_at_2(self):
        at = AdaptiveTimeout()
        at.record_latency(120.0)  # would be 1 + 120/30 = 5, capped at 2
        result = at.calculate(tool_count=0, model="test", is_first_chunk=True)
        from backend.core.utils.timeouts import TIMEOUTS
        expected = int(TIMEOUTS.FIRST_CHUNK_BASE * 2.0)
        max_timeout = TIMEOUTS.API_CALL - 10
        assert result == min(expected, max_timeout)

    def test_calculate_result_capped_at_max_timeout(self):
        at = AdaptiveTimeout()
        at.record_latency(100.0)  # latency_factor = 2.0
        result = at.calculate(tool_count=30, model="test", is_first_chunk=True)
        from backend.core.utils.timeouts import TIMEOUTS
        max_timeout = TIMEOUTS.API_CALL - 10
        assert result <= max_timeout


# ============================================================================
# _calculate_dynamic_timeout wrapper
# ============================================================================

class TestCalculateDynamicTimeout:

    def test_delegates_to_adaptive_timeout(self):
        result = _calculate_dynamic_timeout(tool_count=0, is_first_chunk=True, model="test")
        assert isinstance(result, int)
        assert result > 0

    def test_model_default_to_empty_string(self):
        result = _calculate_dynamic_timeout(tool_count=0, is_first_chunk=True, model=None)
        assert isinstance(result, int)


# ============================================================================
# CircuitBreakerState
# ============================================================================

class TestCircuitBreakerState:

    def test_initial_state_is_closed(self):
        cb = CircuitBreakerState()
        assert cb._state == "closed"
        assert cb._failure_count == 0
        assert cb.can_proceed() is True

    def test_record_failure_increments_count(self):
        cb = CircuitBreakerState()
        cb.record_failure("server_error")
        assert cb._failure_count == 1
        assert cb._state == "closed"  # not yet open

    def test_record_failure_opens_after_5(self):
        cb = CircuitBreakerState()
        for _ in range(5):
            cb.record_failure("server_error")
        assert cb._state == "open"
        assert cb.can_proceed() is False

    def test_record_failure_rate_limit_sets_300s_cooldown(self):
        cb = CircuitBreakerState()
        for _ in range(5):
            cb.record_failure("rate_limit")
        assert cb._cooldown_seconds == 300

    def test_record_failure_server_error_sets_60s_cooldown(self):
        cb = CircuitBreakerState()
        for _ in range(5):
            cb.record_failure("server_error")
        assert cb._cooldown_seconds == 60

    def test_record_failure_timeout_sets_30s_cooldown(self):
        cb = CircuitBreakerState()
        for _ in range(5):
            cb.record_failure("timeout")
        assert cb._cooldown_seconds == 30

    def test_record_failure_unknown_uses_default_cooldown(self):
        cb = CircuitBreakerState()
        for _ in range(5):
            cb.record_failure("unknown")
        from backend.core.utils.timeouts import TIMEOUTS
        assert cb._cooldown_seconds == TIMEOUTS.CIRCUIT_BREAKER_DEFAULT

    def test_record_success_resets_failure_count(self):
        cb = CircuitBreakerState()
        cb.record_failure("timeout")
        cb.record_failure("timeout")
        cb.record_success()
        assert cb._failure_count == 0

    def test_record_success_closes_half_open(self):
        cb = CircuitBreakerState()
        cb._state = "half-open"
        cb.record_success()
        assert cb._state == "closed"

    def test_record_success_no_change_when_closed(self):
        cb = CircuitBreakerState()
        cb.record_success()
        assert cb._state == "closed"

    def test_can_proceed_transitions_open_to_half_open_after_cooldown(self):
        cb = CircuitBreakerState()
        for _ in range(5):
            cb.record_failure("timeout")
        assert cb._state == "open"
        # Set open_until in the past
        cb._open_until = time.time() - 1
        assert cb.can_proceed() is True
        assert cb._state == "half-open"

    def test_can_proceed_false_when_open_and_not_expired(self):
        cb = CircuitBreakerState()
        for _ in range(5):
            cb.record_failure("timeout")
        cb._open_until = time.time() + 1000
        assert cb.can_proceed() is False

    def test_get_remaining_cooldown_zero_when_closed(self):
        cb = CircuitBreakerState()
        assert cb.get_remaining_cooldown() == 0

    def test_get_remaining_cooldown_positive_when_open(self):
        cb = CircuitBreakerState()
        for _ in range(5):
            cb.record_failure("rate_limit")
        remaining = cb.get_remaining_cooldown()
        assert remaining > 0

    def test_get_remaining_cooldown_zero_when_expired(self):
        cb = CircuitBreakerState()
        cb._state = "open"
        cb._open_until = time.time() - 10
        assert cb.get_remaining_cooldown() == 0


# ============================================================================
# _gemini_schema_to_anthropic
# ============================================================================

class TestGeminiSchemaToAnthropic:

    def test_non_dict_passthrough(self):
        assert _gemini_schema_to_anthropic("hello") == "hello"
        assert _gemini_schema_to_anthropic(42) == 42
        assert _gemini_schema_to_anthropic(None) is None

    def test_lowercases_type_field(self):
        result = _gemini_schema_to_anthropic({"type": "STRING"})
        assert result == {"type": "string"}

    def test_preserves_non_type_fields(self):
        result = _gemini_schema_to_anthropic({"name": "test", "description": "desc"})
        assert result == {"name": "test", "description": "desc"}

    def test_recursive_dict(self):
        result = _gemini_schema_to_anthropic({
            "type": "OBJECT",
            "properties": {"name": {"type": "STRING"}},
        })
        assert result == {
            "type": "object",
            "properties": {"name": {"type": "string"}},
        }

    def test_recursive_list(self):
        result = _gemini_schema_to_anthropic({
            "items": [{"type": "INTEGER"}, {"type": "BOOLEAN"}],
        })
        assert result == {
            "items": [{"type": "integer"}, {"type": "boolean"}],
        }

    def test_list_with_non_dict_items(self):
        result = _gemini_schema_to_anthropic({
            "enum": ["one", "two"],
        })
        assert result == {"enum": ["one", "two"]}

    def test_empty_dict(self):
        assert _gemini_schema_to_anthropic({}) == {}


# ============================================================================
# LLMProvider / get_provider / get_all_providers
# ============================================================================

class TestLLMProviders:

    def test_llm_providers_has_google_and_anthropic(self):
        assert "google" in LLM_PROVIDERS
        assert "anthropic" in LLM_PROVIDERS

    def test_provider_dataclass_fields(self):
        p = LLM_PROVIDERS["anthropic"]
        assert isinstance(p, LLMProvider)
        assert p.provider == "anthropic"
        assert p.supports_vision is True
        assert p.supports_streaming is True

    def test_default_provider_is_anthropic(self):
        assert DEFAULT_PROVIDER == "anthropic"

    def test_get_provider_known(self):
        p = get_provider("google")
        assert p.provider == "google"

    def test_get_provider_unknown_returns_default(self):
        p = get_provider("nonexistent")
        assert p is LLM_PROVIDERS[DEFAULT_PROVIDER]

    def test_get_all_providers_returns_list(self):
        result = get_all_providers()
        assert isinstance(result, list)
        assert len(result) == len(LLM_PROVIDERS)
        for item in result:
            assert "id" in item
            assert "name" in item
            assert "available" in item

    def test_get_all_providers_availability_reflects_env(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}):
            result = get_all_providers()
            google_entry = next(e for e in result if e["id"] == "google")
            assert google_entry["available"] is True

    def test_get_all_providers_unavailable_without_key(self):
        with patch.dict(os.environ, {}, clear=True):
            # Remove the key if present
            os.environ.pop("GEMINI_API_KEY", None)
            os.environ.pop("ANTHROPIC_API_KEY", None)
            result = get_all_providers()
            for entry in result:
                assert entry["available"] is False


# ============================================================================
# get_llm_client factory
# ============================================================================

class TestGetLlmClient:

    @patch("backend.llm.clients.GeminiClient.__init__", return_value=None)
    def test_returns_gemini_client_for_google(self, mock_init):
        client = get_llm_client("google")
        assert isinstance(client, GeminiClient)

    @patch("backend.llm.clients.AnthropicClient.__init__", return_value=None)
    def test_returns_anthropic_client_for_anthropic(self, mock_init):
        client = get_llm_client("anthropic")
        assert isinstance(client, AnthropicClient)

    @patch("backend.llm.clients.AnthropicClient.__init__", return_value=None)
    def test_unknown_provider_falls_back_to_default(self, mock_init):
        # get_provider returns default (anthropic) for unknown
        client = get_llm_client("unknown_provider")
        assert isinstance(client, AnthropicClient)

    @patch("backend.llm.clients.GeminiClient.__init__", return_value=None)
    def test_model_override_passed_through(self, mock_init):
        get_llm_client("google", model="custom-model")
        mock_init.assert_called_once_with(model="custom-model")


# ============================================================================
# GeminiClient.generate (non-stream)
# ============================================================================

def _build_gemini_client() -> GeminiClient:
    """Build a GeminiClient without calling __init__."""
    c = object.__new__(GeminiClient)
    c.model_name = "gemini-test"
    c._client = MagicMock()
    types_mock = MagicMock()
    types_mock.Part.from_text.return_value = MagicMock()
    types_mock.Part.from_bytes.return_value = MagicMock()
    types_mock.Content.return_value = MagicMock()
    types_mock.GenerateContentConfig.return_value = MagicMock()
    c._types = types_mock
    return c


class TestGeminiClientGenerate:

    @pytest.fixture
    def client(self) -> GeminiClient:
        return _build_gemini_client()

    async def test_generate_returns_text(self, client: GeminiClient):
        mock_response = MagicMock()
        mock_response.text = "Hello from Gemini"
        client._client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        result = await client.generate("test prompt")
        assert result == "Hello from Gemini"

    async def test_generate_returns_empty_when_no_text(self, client: GeminiClient):
        mock_response = MagicMock()
        mock_response.text = None
        client._client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        result = await client.generate("test prompt")
        assert result == ""

    async def test_generate_with_system_prompt(self, client: GeminiClient):
        mock_response = MagicMock()
        mock_response.text = "ok"
        client._client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        await client.generate("prompt", system_prompt="sys prompt")
        # Verify text content includes system instructions
        call_args = client._types.Part.from_text.call_args
        text_arg = call_args[1]["text"]
        assert "[System Instructions]" in text_arg
        assert "sys prompt" in text_arg

    async def test_generate_with_image_dict(self, client: GeminiClient):
        import base64
        b64_data = base64.b64encode(b"fake_image").decode()
        images = [{"mime_type": "image/png", "data": b64_data}]

        mock_response = MagicMock()
        mock_response.text = "saw image"
        client._client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        result = await client.generate("what is this?", images=images)
        assert result == "saw image"
        client._types.Part.from_bytes.assert_called_once()

    async def test_generate_with_image_bytes(self, client: GeminiClient):
        images = [b"raw_bytes"]
        mock_response = MagicMock()
        mock_response.text = "ok"
        client._client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        await client.generate("describe", images=images)
        client._types.Part.from_bytes.assert_called_once()

    async def test_generate_with_image_string(self, client: GeminiClient):
        import base64
        b64_str = base64.b64encode(b"test").decode()
        images = [b64_str]
        mock_response = MagicMock()
        mock_response.text = "ok"
        client._client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        await client.generate("describe", images=images)
        client._types.Part.from_bytes.assert_called_once()

    async def test_generate_image_error_is_swallowed(self, client: GeminiClient):
        """Bad image data should not crash generate."""
        images = [{"mime_type": "image/png", "data": "not-valid-base64!!!"}]
        mock_response = MagicMock()
        mock_response.text = "ok despite bad image"
        client._client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        result = await client.generate("test", images=images)
        assert result == "ok despite bad image"


# ============================================================================
# AnthropicClient.generate (non-stream)
# ============================================================================

def _build_anthropic_client() -> AnthropicClient:
    """Build an AnthropicClient without calling __init__."""
    import anthropic

    c = object.__new__(AnthropicClient)
    c.model_name = "claude-test"
    c._client = AsyncMock()
    c._anthropic = anthropic
    return c


class TestAnthropicClientGenerate:

    @pytest.fixture
    def client(self) -> AnthropicClient:
        return _build_anthropic_client()

    async def test_generate_returns_text(self, client: AnthropicClient):
        block = SimpleNamespace(type="text", text="Hello from Claude")
        mock_response = MagicMock()
        mock_response.content = [block]
        client._client.messages.create = AsyncMock(return_value=mock_response)

        result = await client.generate("test prompt")
        assert result == "Hello from Claude"

    async def test_generate_filters_non_text_blocks(self, client: AnthropicClient):
        blocks = [
            SimpleNamespace(type="thinking", text="hmm"),
            SimpleNamespace(type="text", text="answer"),
        ]
        mock_response = MagicMock()
        mock_response.content = blocks
        client._client.messages.create = AsyncMock(return_value=mock_response)

        result = await client.generate("test")
        assert result == "answer"

    async def test_generate_with_system_prompt(self, client: AnthropicClient):
        block = SimpleNamespace(type="text", text="ok")
        mock_response = MagicMock()
        mock_response.content = [block]
        client._client.messages.create = AsyncMock(return_value=mock_response)

        await client.generate("prompt", system_prompt="you are helpful")
        kwargs = client._client.messages.create.call_args[1]
        assert kwargs["system"] == "you are helpful"

    async def test_generate_with_image(self, client: AnthropicClient):
        import base64
        b64_data = base64.b64encode(b"fake_img").decode()
        images = [{"mime_type": "image/jpeg", "data": b64_data}]

        block = SimpleNamespace(type="text", text="saw it")
        mock_response = MagicMock()
        mock_response.content = [block]
        client._client.messages.create = AsyncMock(return_value=mock_response)

        result = await client.generate("describe", images=images)
        assert result == "saw it"

        kwargs = client._client.messages.create.call_args[1]
        user_content = kwargs["messages"][0]["content"]
        # Should have image block + text block
        assert len(user_content) == 2
        assert user_content[0]["type"] == "image"
        assert user_content[1]["type"] == "text"

    async def test_generate_concatenates_multiple_text_blocks(self, client: AnthropicClient):
        blocks = [
            SimpleNamespace(type="text", text="part1"),
            SimpleNamespace(type="text", text="part2"),
        ]
        mock_response = MagicMock()
        mock_response.content = blocks
        client._client.messages.create = AsyncMock(return_value=mock_response)

        result = await client.generate("test")
        assert result == "part1part2"


# ============================================================================
# GeminiClient.is_circuit_open / AnthropicClient.is_circuit_open
# ============================================================================

class TestClientCircuitBreakers:

    @pytest.fixture(autouse=True)
    def reset_breakers(self):
        GeminiClient._circuit_breaker = CircuitBreakerState()
        AnthropicClient._circuit_breaker = CircuitBreakerState()

    def test_gemini_circuit_initially_not_open(self):
        assert GeminiClient.is_circuit_open() is False

    def test_anthropic_circuit_initially_not_open(self):
        assert AnthropicClient.is_circuit_open() is False

    def test_gemini_circuit_opens_after_failures(self):
        for _ in range(5):
            GeminiClient._circuit_breaker.record_failure("rate_limit")
        assert GeminiClient.is_circuit_open() is True

    def test_anthropic_circuit_opens_after_failures(self):
        for _ in range(5):
            AnthropicClient._circuit_breaker.record_failure("rate_limit")
        assert AnthropicClient.is_circuit_open() is True


# ============================================================================
# BaseLLMClient abstract interface
# ============================================================================

class TestBaseLLMClient:

    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            BaseLLMClient()
