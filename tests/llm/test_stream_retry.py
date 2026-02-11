"""Tests for GeminiClient and AnthropicClient stream retry integration."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.llm.clients import (
    AnthropicClient,
    CircuitBreakerState,
    GeminiClient,
    _adaptive_timeout,
)


# ============================================================================
# Helpers
# ============================================================================

def _make_chunk(text: str, is_thought: bool = False, func_call: Any = None) -> SimpleNamespace:
    """Create a fake SDK-style Gemini chunk with candidates structure."""
    part = SimpleNamespace(text=text, thought=is_thought, function_call=func_call)
    content = SimpleNamespace(parts=[part])
    candidate = SimpleNamespace(content=content)
    return SimpleNamespace(candidates=[candidate], text=text)


class _FakeAsyncStream:
    """Async iterable that yields SDK-like chunks for native async streaming."""

    def __init__(self, chunks: list[SimpleNamespace]) -> None:
        self._chunks = chunks

    async def __aiter__(self):
        for c in self._chunks:
            yield c


def _build_gemini_client() -> GeminiClient:
    """Build a GeminiClient without calling __init__ (avoids google SDK import)."""
    c = object.__new__(GeminiClient)
    c.model_name = "gemini-test"
    c._client = MagicMock()

    types_mock = MagicMock()
    types_mock.Part.from_text.return_value = MagicMock()
    types_mock.Content.return_value = MagicMock()
    c._types = types_mock
    return c


# ============================================================================
# GeminiClient stream retry tests
# ============================================================================

class TestGeminiStreamRetry:

    @pytest.fixture(autouse=True)
    def reset_circuit_breaker(self) -> None:
        GeminiClient._circuit_breaker = CircuitBreakerState()

    @pytest.fixture
    def client(self) -> GeminiClient:
        return _build_gemini_client()

    def _setup_stream(self, client: GeminiClient, chunks: list) -> None:
        """Configure the client mock to return async stream of chunks."""
        client._client.aio.models.generate_content_stream = MagicMock(
            return_value=_FakeAsyncStream(chunks)
        )

    def _setup_stream_error(self, client: GeminiClient, error: Exception) -> None:
        """Configure the client mock to raise on streaming."""
        client._client.aio.models.generate_content_stream = MagicMock(
            side_effect=error
        )

    def _setup_stream_sequence(self, client: GeminiClient, sequence: list) -> None:
        """Configure sequential responses (errors then success)."""
        client._client.aio.models.generate_content_stream = MagicMock(
            side_effect=sequence
        )

    # ---- success ----

    async def test_stream_yields_all_chunks_on_success(self, client: GeminiClient) -> None:
        chunks = [_make_chunk("hello "), _make_chunk("world")]
        self._setup_stream(client, chunks)

        items = []
        async for item in client.generate_stream("test prompt"):
            items.append(item[0])
        assert "".join(items) == "hello world"

    # ---- retryable errors ----

    async def test_stream_retries_on_503(self, client: GeminiClient) -> None:
        self._setup_stream_sequence(client, [
            Exception("503 Service Unavailable"),
            _FakeAsyncStream([_make_chunk("recovered")]),
        ])

        items = []
        async for item in client.generate_stream("test"):
            items.append(item[0])
        assert "recovered" in items

    async def test_stream_retries_on_timeout(self, client: GeminiClient) -> None:
        self._setup_stream_sequence(client, [
            Exception("timeout - server not responding"),
            _FakeAsyncStream([_make_chunk("ok after timeout")]),
        ])

        items = []
        async for item in client.generate_stream("test"):
            items.append(item[0])
        assert len(items) >= 1

    async def test_stream_retries_on_429(self, client: GeminiClient) -> None:
        self._setup_stream_sequence(client, [
            Exception("429 resource_exhausted"),
            _FakeAsyncStream([_make_chunk("ok")]),
        ])

        items = []
        async for item in client.generate_stream("test"):
            items.append(item[0])
        assert len(items) >= 1

    # ---- non-retryable ----

    async def test_stream_no_retry_on_non_retryable(self, client: GeminiClient) -> None:
        self._setup_stream_error(client, ValueError("bad prompt format"))
        with pytest.raises(ValueError, match="bad prompt"):
            async for _ in client.generate_stream("test"):
                pass

    # ---- circuit breaker ----

    async def test_circuit_breaker_records_failure_on_retryable(self, client: GeminiClient) -> None:
        self._setup_stream_error(client, Exception("503 Service Unavailable"))

        with pytest.raises(Exception, match="503"):
            async for _ in client.generate_stream("test"):
                pass

        assert GeminiClient._circuit_breaker._failure_count > 0

    async def test_circuit_breaker_records_success_on_completion(self, client: GeminiClient) -> None:
        GeminiClient._circuit_breaker.record_failure("server_error")
        assert GeminiClient._circuit_breaker._failure_count == 1

        self._setup_stream(client, [_make_chunk("ok")])

        async for _ in client.generate_stream("test"):
            pass
        assert GeminiClient._circuit_breaker._failure_count == 0

    async def test_circuit_breaker_open_prevents_call(self, client: GeminiClient) -> None:
        for _ in range(5):
            GeminiClient._circuit_breaker.record_failure("rate_limit")

        with pytest.raises(Exception, match="Circuit breaker open"):
            async for _ in client.generate_stream("test"):
                pass

    # ---- error_monitor ----

    async def test_error_monitor_records_on_failure(self, client: GeminiClient) -> None:
        self._setup_stream_error(client, Exception("503 broken"))

        with patch("backend.llm.gemini_client.error_monitor") as mock_monitor:
            with pytest.raises(Exception, match="503"):
                async for _ in client.generate_stream("test"):
                    pass
            assert mock_monitor.record.called

    # ---- adaptive timeout ----

    async def test_adaptive_timeout_records_latency_on_success(self, client: GeminiClient) -> None:
        self._setup_stream(client, [_make_chunk("done")])
        initial_len = len(_adaptive_timeout._recent_latencies)

        async for _ in client.generate_stream("test"):
            pass

        assert len(_adaptive_timeout._recent_latencies) > initial_len


# ============================================================================
# AnthropicClient stream retry tests
# ============================================================================

def _build_anthropic_client() -> AnthropicClient:
    """Build an AnthropicClient without calling __init__ (avoids SDK import)."""
    import anthropic

    c = object.__new__(AnthropicClient)
    c.model_name = "claude-test"
    c._client = AsyncMock()
    c._anthropic = anthropic
    return c


class TestAnthropicStreamRetry:

    @pytest.fixture(autouse=True)
    def reset_circuit_breaker(self) -> None:
        AnthropicClient._circuit_breaker = CircuitBreakerState()

    @pytest.fixture
    def client(self) -> AnthropicClient:
        return _build_anthropic_client()

    @staticmethod
    def _make_stream_events(text_chunks: list[str]) -> list:
        """Build a sequence of Anthropic stream events for text output."""
        events = []
        for chunk in text_chunks:
            events.append(SimpleNamespace(
                type="content_block_delta",
                delta=SimpleNamespace(type="text_delta", text=chunk),
            ))
        events.append(SimpleNamespace(type="content_block_stop"))
        return events

    def _setup_stream(
        self,
        client: AnthropicClient,
        events_list: list[list],
        errors: list[Exception | None] | None = None,
    ) -> None:
        """Configure client._client.messages.stream for sequential attempts."""
        if errors is None:
            errors = [None] * len(events_list)

        call_idx = 0

        class _FakeStream:
            def __init__(self, events, error):
                self._events = events
                self._error = error

            async def __aenter__(self):
                if self._error:
                    raise self._error
                return self

            async def __aexit__(self, *args):
                pass

            async def __aiter__(self):
                for ev in self._events:
                    yield ev

        def _stream_factory(**kwargs):
            nonlocal call_idx
            idx = min(call_idx, len(events_list) - 1)
            err = errors[idx] if idx < len(errors) else None
            evts = events_list[idx] if idx < len(events_list) else []
            call_idx += 1
            return _FakeStream(evts, err)

        client._client.messages.stream = MagicMock(side_effect=_stream_factory)

    # ---- success ----

    async def test_stream_yields_all_chunks_on_success(self, client: AnthropicClient) -> None:
        events = self._make_stream_events(["hello ", "world"])
        self._setup_stream(client, [events])

        items = []
        async for text, is_thought, func_call in client.generate_stream("test"):
            items.append(text)
        assert "".join(items) == "hello world"

    # ---- retryable Anthropic errors ----

    async def test_stream_retries_on_rate_limit(self, client: AnthropicClient) -> None:
        import anthropic as anth_mod
        rate_err = anth_mod.RateLimitError(
            "rate limited",
            response=MagicMock(status_code=429, headers={}),
            body=None,
        )
        ok_events = self._make_stream_events(["ok"])
        self._setup_stream(client, [[], ok_events], errors=[rate_err, None])

        items = []
        async for text, _, _ in client.generate_stream("test"):
            items.append(text)
        assert "ok" in "".join(items)

    async def test_stream_retries_on_529_overloaded(self, client: AnthropicClient) -> None:
        import anthropic as anth_mod
        err_529 = anth_mod.APIStatusError(
            "overloaded",
            response=MagicMock(status_code=529, headers={}),
            body=None,
        )
        err_529.status_code = 529
        ok_events = self._make_stream_events(["recovered"])
        self._setup_stream(client, [[], ok_events], errors=[err_529, None])

        items = []
        async for text, _, _ in client.generate_stream("test"):
            items.append(text)
        assert len(items) > 0

    async def test_stream_retries_on_timeout(self, client: AnthropicClient) -> None:
        import anthropic as anth_mod
        timeout_err = anth_mod.APITimeoutError(MagicMock())
        ok_events = self._make_stream_events(["ok"])
        self._setup_stream(client, [[], ok_events], errors=[timeout_err, None])

        items = []
        async for text, _, _ in client.generate_stream("test"):
            items.append(text)
        assert len(items) > 0

    async def test_stream_retries_on_connection_error(self, client: AnthropicClient) -> None:
        import anthropic as anth_mod
        conn_err = anth_mod.APIConnectionError(request=MagicMock())
        ok_events = self._make_stream_events(["ok"])
        self._setup_stream(client, [[], ok_events], errors=[conn_err, None])

        items = []
        async for text, _, _ in client.generate_stream("test"):
            items.append(text)
        assert len(items) > 0

    # ---- non-retryable ----

    async def test_stream_no_retry_on_other_api_status_error(self, client: AnthropicClient) -> None:
        import anthropic as anth_mod
        err_400 = anth_mod.APIStatusError(
            "bad request",
            response=MagicMock(status_code=400, headers={}),
            body=None,
        )
        err_400.status_code = 400
        self._setup_stream(client, [[]], errors=[err_400])

        with pytest.raises(anth_mod.APIStatusError):
            async for _ in client.generate_stream("test"):
                pass

    async def test_stream_no_retry_on_generic_exception(self, client: AnthropicClient) -> None:
        self._setup_stream(client, [[]], errors=[RuntimeError("unexpected")])

        with pytest.raises(RuntimeError, match="unexpected"):
            async for _ in client.generate_stream("test"):
                pass

    # ---- circuit breaker ----

    async def test_circuit_breaker_records_failure(self, client: AnthropicClient) -> None:
        import anthropic as anth_mod
        rate_err = anth_mod.RateLimitError(
            "limit",
            response=MagicMock(status_code=429, headers={}),
            body=None,
        )
        self._setup_stream(
            client,
            [[] for _ in range(5)],
            errors=[rate_err] * 5,
        )

        with pytest.raises(anth_mod.RateLimitError):
            async for _ in client.generate_stream("test"):
                pass
        assert AnthropicClient._circuit_breaker._failure_count > 0

    async def test_circuit_breaker_records_success(self, client: AnthropicClient) -> None:
        AnthropicClient._circuit_breaker.record_failure("rate_limit")
        assert AnthropicClient._circuit_breaker._failure_count == 1

        ok_events = self._make_stream_events(["ok"])
        self._setup_stream(client, [ok_events])

        async for _ in client.generate_stream("test"):
            pass
        assert AnthropicClient._circuit_breaker._failure_count == 0
