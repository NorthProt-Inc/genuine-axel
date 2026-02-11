"""Tests for ReAct error recovery with exponential backoff (Wave 2.1)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.core.services.react_service import (
    ReActLoopService,
    ReActConfig,
    ChatEvent,
    EventType,
)
from backend.core.errors import ProviderError, TransientError, PermanentError


class TestReActRetryOnProviderError:
    """ReAct should retry on transient/provider errors with backoff."""

    @pytest.mark.asyncio
    async def test_retry_on_provider_error(self):
        """Should retry when LLM raises ProviderError (transient)."""
        call_count = 0

        class MockLLM:
            def generate_stream(self, **kwargs):
                nonlocal call_count
                call_count += 1
                return self._gen(call_count)

            async def _gen(self, n):
                if n == 1:
                    raise ProviderError("overloaded", provider="gemini")
                yield ("hello", False, None)

        service = ReActLoopService()
        config = ReActConfig(max_loops=3)

        events = []
        with patch("backend.core.services.react_service.get_llm_client", return_value=MockLLM()):
            async for event in service.run(
                prompt="test",
                system_prompt="system",
                model_config=MagicMock(provider="gemini", model="flash"),
                available_tools=[],
                config=config,
            ):
                events.append(event)

        text_events = [e for e in events if e.type == EventType.TEXT]
        assert len(text_events) > 0
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_no_retry_on_permanent_error(self):
        """Should NOT retry on PermanentError."""
        call_count = 0

        class MockLLM:
            def generate_stream(self, **kwargs):
                nonlocal call_count
                call_count += 1
                return self._gen()

            async def _gen(self):
                raise PermanentError("invalid model")
                yield  # make it an async generator  # noqa: E501

        service = ReActLoopService()
        config = ReActConfig(max_loops=3)

        events = []
        with patch("backend.core.services.react_service.get_llm_client", return_value=MockLLM()):
            async for event in service.run(
                prompt="test",
                system_prompt="system",
                model_config=MagicMock(provider="gemini", model="flash"),
                available_tools=[],
                config=config,
            ):
                events.append(event)

        assert call_count == 1
        text_events = [e for e in events if e.type == EventType.TEXT]
        assert len(text_events) > 0

    @pytest.mark.asyncio
    async def test_max_retries_exceeded(self):
        """Should give up after max retries."""
        call_count = 0

        class MockLLM:
            def generate_stream(self, **kwargs):
                nonlocal call_count
                call_count += 1
                return self._gen()

            async def _gen(self):
                raise ProviderError("always failing", provider="gemini")
                yield  # noqa: E501

        service = ReActLoopService()
        config = ReActConfig(max_loops=3)

        events = []
        with patch("backend.core.services.react_service.get_llm_client", return_value=MockLLM()):
            async for event in service.run(
                prompt="test",
                system_prompt="system",
                model_config=MagicMock(provider="gemini", model="flash"),
                available_tools=[],
                config=config,
            ):
                events.append(event)

        assert call_count <= 4
        text_events = [e for e in events if e.type == EventType.TEXT]
        assert len(text_events) > 0

    @pytest.mark.asyncio
    async def test_retry_on_transient_error(self):
        """Should retry on any TransientError subclass."""
        call_count = 0

        class MockLLM:
            def generate_stream(self, **kwargs):
                nonlocal call_count
                call_count += 1
                return self._gen(call_count)

            async def _gen(self, n):
                if n == 1:
                    raise TransientError("temporary issue")
                yield ("recovered", False, None)

        service = ReActLoopService()
        config = ReActConfig(max_loops=3)

        events = []
        with patch("backend.core.services.react_service.get_llm_client", return_value=MockLLM()):
            async for event in service.run(
                prompt="test",
                system_prompt="system",
                model_config=MagicMock(provider="gemini", model="flash"),
                available_tools=[],
                config=config,
            ):
                events.append(event)

        assert call_count == 2
