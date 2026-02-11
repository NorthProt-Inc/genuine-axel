"""Tests for ReActLoopService."""

import pytest
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

from backend.core.services.react_service import (
    EventType,
    ChatEvent,
    ReActConfig,
    ReActResult,
    ReActLoopService,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def mock_generate_stream(chunks):
    """Yield (text, is_thought, function_call) tuples as an async generator."""
    for text, is_thought, function_call in chunks:
        yield text, is_thought, function_call


@dataclass
class FakeModelConfig:
    """Minimal model config with provider and model attributes."""
    provider: str = "anthropic"
    model: str = "claude-test"
    name: str = "Claude Test"
    id: str = "test"
    icon: str = ""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def model_config():
    return FakeModelConfig()


@pytest.fixture
def react_config():
    return ReActConfig(max_loops=3, temperature=0.5, max_tokens=1024)


@pytest.fixture
def tool_service():
    ts = MagicMock()
    ts.execute_tools = AsyncMock()
    return ts


@pytest.fixture
def svc(tool_service):
    return ReActLoopService(tool_service=tool_service)


@pytest.fixture
def svc_bare():
    return ReActLoopService(tool_service=None)


# ---------------------------------------------------------------------------
# EventType enum
# ---------------------------------------------------------------------------


class TestEventTypes:
    """Verify EventType enum values match expected strings."""

    def test_event_types_enum_values(self):
        assert EventType.STATUS == "status"
        assert EventType.TEXT == "text"
        assert EventType.THINKING == "thinking"
        assert EventType.AUDIO == "audio"
        assert EventType.ERROR == "error"
        assert EventType.DONE == "done"
        assert EventType.CONTROL == "control"
        assert EventType.THINKING_START == "thinking start"
        assert EventType.THINKING_END == "thinking end"
        assert EventType.TOOL_START == "tool start"
        assert EventType.TOOL_END == "tool end"


# ---------------------------------------------------------------------------
# _get_fallback_response
# ---------------------------------------------------------------------------


class TestFallbackResponse:
    """Tests for error-type-to-Korean-message mapping."""

    def test_fallback_503_overloaded(self, svc):
        msg = svc._get_fallback_response("503 service unavailable")
        assert "서버" in msg or "바빠" in msg

    def test_fallback_overloaded_keyword(self, svc):
        msg = svc._get_fallback_response("the model is overloaded")
        assert "서버" in msg or "바빠" in msg

    def test_fallback_timeout(self, svc):
        msg = svc._get_fallback_response("request timeout after 30s")
        assert "늦어" in msg or "기다려" in msg

    def test_fallback_circuit_breaker(self, svc):
        msg = svc._get_fallback_response("circuit breaker open")
        assert "쉬어" in msg or "30초" in msg

    def test_fallback_rate_limit(self, svc):
        msg = svc._get_fallback_response("429 too many requests")
        assert "요청" in msg or "많았" in msg

    def test_fallback_rate_keyword(self, svc):
        msg = svc._get_fallback_response("rate limit exceeded")
        assert "요청" in msg or "많았" in msg

    def test_fallback_generic(self, svc):
        msg = svc._get_fallback_response("something weird happened")
        assert "문제" in msg or "다시" in msg


# ---------------------------------------------------------------------------
# run() - streaming
# ---------------------------------------------------------------------------


class TestReActRun:
    """Tests for the main run() async generator."""

    @patch("backend.core.services.react_service.get_llm_client")
    async def test_run_simple_text_response(
        self, mock_get_llm, svc, model_config, react_config
    ):
        """Simple text chunks are collected and yielded as TEXT events."""
        llm = MagicMock()
        llm.generate_stream = lambda **kw: mock_generate_stream([
            ("Hello ", False, None),
            ("world!", False, None),
        ])
        mock_get_llm.return_value = llm

        events = []
        async for event in svc.run(
            prompt="hi",
            system_prompt="sys",
            model_config=model_config,
            available_tools=[],
            config=react_config,
        ):
            events.append(event)

        types = [e.type for e in events]
        # Must start with THINKING_START and end with THINKING_END + CONTROL
        assert types[0] == EventType.THINKING_START
        assert types[-2] == EventType.THINKING_END
        assert types[-1] == EventType.CONTROL

        # TEXT events must contain the response text
        text_content = "".join(e.content for e in events if e.type == EventType.TEXT)
        assert "Hello " in text_content
        assert "world!" in text_content

        # CONTROL event carries ReActResult
        control = events[-1]
        result = control.metadata["react_result"]
        assert isinstance(result, ReActResult)
        assert result.loops_completed == 1
        assert "Hello " in result.full_response

    @patch("backend.core.services.react_service.get_llm_client")
    async def test_run_with_thinking(
        self, mock_get_llm, svc, model_config, react_config
    ):
        """Thought chunks are yielded as THINKING events."""
        react_config.enable_thinking = True

        llm = MagicMock()
        llm.generate_stream = lambda **kw: mock_generate_stream([
            ("I should think...", True, None),
            ("Answer", False, None),
        ])
        mock_get_llm.return_value = llm

        events = []
        async for event in svc.run(
            prompt="question",
            system_prompt="sys",
            model_config=model_config,
            available_tools=[],
            config=react_config,
        ):
            events.append(event)

        thinking_events = [e for e in events if e.type == EventType.THINKING]
        assert len(thinking_events) == 1
        assert "think" in thinking_events[0].content

        text_events = [e for e in events if e.type == EventType.TEXT]
        assert any("Answer" in e.content for e in text_events)

    @patch("backend.core.services.react_service.get_llm_client")
    async def test_run_with_tool_calls(
        self, mock_get_llm, svc, tool_service, model_config, react_config
    ):
        """Tool calls trigger tool execution and a second LLM loop."""
        call_count = 0

        def make_stream(**kw):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First loop: LLM emits a function call
                return mock_generate_stream([
                    (None, False, {"name": "search", "args": {"q": "test"}}),
                ])
            else:
                # Second loop: LLM produces text
                return mock_generate_stream([
                    ("Tool result summary.", False, None),
                ])

        llm = MagicMock()
        llm.generate_stream = make_stream
        mock_get_llm.return_value = llm

        # Mock tool execution result
        tool_result = MagicMock()
        tool_result.results = [
            MagicMock(name="search", success=True, output="found 3 results", error=None)
        ]
        tool_result.deferred_tools = []
        tool_result.observation = "search: found 3 results"
        tool_service.execute_tools = AsyncMock(return_value=tool_result)

        events = []
        async for event in svc.run(
            prompt="search test",
            system_prompt="sys",
            model_config=model_config,
            available_tools=[{"name": "search"}],
            config=react_config,
        ):
            events.append(event)

        types = [e.type for e in events]
        # Tool events should appear
        assert EventType.TOOL_START in types
        assert EventType.TOOL_END in types
        assert EventType.STATUS in types

        # Final result
        control = [e for e in events if e.type == EventType.CONTROL][-1]
        result = control.metadata["react_result"]
        assert result.loops_completed == 2
        assert "Tool result summary." in result.full_response

    @patch("backend.core.services.react_service.get_llm_client")
    async def test_run_llm_error_with_fallback(
        self, mock_get_llm, svc, model_config, react_config
    ):
        """LLM error with no partial response yields a Korean fallback."""
        llm = MagicMock()

        async def exploding_stream(**kw):
            raise ConnectionError("503 overloaded")
            yield  # pragma: no cover -- makes this an async generator

        llm.generate_stream = exploding_stream
        mock_get_llm.return_value = llm

        events = []
        async for event in svc.run(
            prompt="hi",
            system_prompt="sys",
            model_config=model_config,
            available_tools=[],
            config=react_config,
        ):
            events.append(event)

        text_events = [e for e in events if e.type == EventType.TEXT]
        assert len(text_events) >= 1
        # Fallback is a Korean message about server being busy
        assert any("서버" in e.content or "바빠" in e.content for e in text_events)

        control = [e for e in events if e.type == EventType.CONTROL][-1]
        result = control.metadata["react_result"]
        assert result.loops_completed == 1

    @patch("backend.core.services.react_service.get_llm_client")
    async def test_run_llm_error_with_partial_response(
        self, mock_get_llm, svc, model_config, react_config
    ):
        """LLM error with partial text keeps the partial response."""
        call_count = 0

        async def partial_then_error(**kw):
            nonlocal call_count
            call_count += 1
            yield "Partial answer so far", False, None
            raise TimeoutError("stream timeout")

        llm = MagicMock()
        llm.generate_stream = partial_then_error
        mock_get_llm.return_value = llm

        events = []
        async for event in svc.run(
            prompt="hi",
            system_prompt="sys",
            model_config=model_config,
            available_tools=[],
            config=react_config,
        ):
            events.append(event)

        text_events = [e for e in events if e.type == EventType.TEXT]
        combined_text = "".join(e.content for e in text_events)
        assert "Partial answer so far" in combined_text

        # No fallback message since partial response exists
        control = [e for e in events if e.type == EventType.CONTROL][-1]
        result = control.metadata["react_result"]
        assert "Partial answer so far" in result.full_response

    @patch("backend.core.services.react_service.get_llm_client")
    async def test_run_max_loops_reached(
        self, mock_get_llm, svc, tool_service, model_config
    ):
        """When max_loops is reached with pending calls, final response is generated."""
        config = ReActConfig(max_loops=1, temperature=0.5, max_tokens=512)

        # Every loop returns a tool call, so loop never finishes naturally
        llm = MagicMock()
        llm.generate_stream = lambda **kw: mock_generate_stream([
            (None, False, {"name": "tool_a", "args": {}}),
        ])
        mock_get_llm.return_value = llm

        tool_result = MagicMock()
        tool_result.results = [
            MagicMock(name="tool_a", success=True, output="done", error=None)
        ]
        tool_result.deferred_tools = []
        tool_result.observation = "tool_a: done"
        tool_service.execute_tools = AsyncMock(return_value=tool_result)

        events = []
        async for event in svc.run(
            prompt="do stuff",
            system_prompt="sys",
            model_config=model_config,
            available_tools=[{"name": "tool_a"}],
            config=config,
        ):
            events.append(event)

        control = [e for e in events if e.type == EventType.CONTROL][-1]
        result = control.metadata["react_result"]
        # max_loops=1, and there was a tool call, so _generate_final_response is invoked
        assert result.loops_completed >= 1
