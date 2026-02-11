"""Tests for ChatHandler."""

from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

from backend.core.chat_handler import ChatHandler, ChatRequest
from backend.core.services.react_service import (
    ChatEvent,
    EventType,
    ReActResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _collect_events(async_gen):
    """Drain an async generator into a list."""
    events = []
    async for event in async_gen:
        events.append(event)
    return events


def _make_state(
    memory_manager=None,
    long_term_memory=None,
    identity_manager=None,
    background_tasks=None,
):
    """Build a minimal ChatStateProtocol-compatible mock."""
    state = MagicMock()
    type(state).memory_manager = PropertyMock(return_value=memory_manager)
    type(state).long_term_memory = PropertyMock(return_value=long_term_memory)
    type(state).identity_manager = PropertyMock(return_value=identity_manager)
    type(state).background_tasks = PropertyMock(
        return_value=background_tasks if background_tasks is not None else []
    )
    return state


# ---------------------------------------------------------------------------
# Lazy service creation
# ---------------------------------------------------------------------------


class TestLazyServiceCreation:
    """Verify that services are lazily instantiated on first property access."""

    def test_lazy_service_creation(self, mock_chat_state):
        """Services start as None and are created on first access."""
        handler = ChatHandler(state=mock_chat_state)

        # Internal slots are None before access
        assert handler._context_service is None
        assert handler._search_service is None
        assert handler._tool_service is None
        assert handler._react_service is None
        assert handler._persistence_service is None

        # Accessing properties triggers creation
        ctx = handler.context_service
        assert ctx is not None
        assert handler._context_service is ctx

        search = handler.search_service
        assert search is not None
        assert handler._search_service is search

        tool = handler.tool_service
        assert tool is not None
        assert handler._tool_service is tool

        react = handler.react_service
        assert react is not None
        assert handler._react_service is react

        persist = handler.persistence_service
        assert persist is not None
        assert handler._persistence_service is persist

    def test_lazy_service_reuses_instance(self, mock_chat_state):
        """Second access returns the same instance (no re-creation)."""
        handler = ChatHandler(state=mock_chat_state)
        first = handler.context_service
        second = handler.context_service
        assert first is second


# ---------------------------------------------------------------------------
# _build_final_prompt
# ---------------------------------------------------------------------------


class TestBuildFinalPrompt:
    """Tests for prompt construction."""

    def test_build_final_prompt_no_search(self, mock_chat_state):
        """Without search context, prompt is just user input."""
        handler = ChatHandler(state=mock_chat_state)
        prompt = handler._build_final_prompt(
            user_input="tell me a joke",
            search_context="",
            search_failed=False,
        )
        assert "[User]: tell me a joke" in prompt
        assert "검색 결과" not in prompt
        assert "검색 실패" not in prompt

    def test_build_final_prompt_with_search(self, mock_chat_state):
        """Search context is included above user input."""
        handler = ChatHandler(state=mock_chat_state)
        prompt = handler._build_final_prompt(
            user_input="what is the weather",
            search_context="It will rain tomorrow.",
            search_failed=False,
        )
        assert "## 검색 결과" in prompt
        assert "It will rain tomorrow." in prompt
        assert "[User]: what is the weather" in prompt
        # Search context should come before user input
        idx_search = prompt.index("검색 결과")
        idx_user = prompt.index("[User]")
        assert idx_search < idx_user

    def test_build_final_prompt_search_failed(self, mock_chat_state):
        """When search failed, a failure marker is inserted."""
        handler = ChatHandler(state=mock_chat_state)
        prompt = handler._build_final_prompt(
            user_input="news today",
            search_context="",
            search_failed=True,
        )
        assert "검색 실패" in prompt
        assert "[User]: news today" in prompt


# ---------------------------------------------------------------------------
# _get_session_id / _get_turn_count / _get_longterm_count
# ---------------------------------------------------------------------------


class TestStateAccessors:
    """Tests for safe state accessor methods."""

    def test_get_session_id_with_manager(self, mock_chat_state, mock_memory_manager):
        """Session ID is fetched from memory manager."""
        mock_memory_manager.get_session_id.return_value = "sess-abcdefgh"
        handler = ChatHandler(state=mock_chat_state)
        assert handler._get_session_id() == "sess-abcdefgh"

    def test_get_session_id_without_manager(self):
        """Without memory manager, returns 'unknown'."""
        state = _make_state(memory_manager=None)
        handler = ChatHandler(state=state)
        assert handler._get_session_id() == "unknown"

    def test_get_turn_count_with_manager(self, mock_chat_state, mock_memory_manager):
        """Turn count is fetched from memory manager."""
        mock_memory_manager.get_turn_count.return_value = 42
        handler = ChatHandler(state=mock_chat_state)
        assert handler._get_turn_count() == 42

    def test_get_turn_count_without_manager(self):
        """Without memory manager, returns 0."""
        state = _make_state(memory_manager=None)
        handler = ChatHandler(state=state)
        assert handler._get_turn_count() == 0

    def test_get_longterm_count_with_manager(self):
        """Long-term count is derived from long_term_memory.get_stats()."""
        lt = MagicMock()
        lt.get_stats.return_value = {"total_memories": 150}
        state = _make_state(long_term_memory=lt)
        handler = ChatHandler(state=state)
        assert handler._get_longterm_count() == 150

    def test_get_longterm_count_without_manager(self):
        """Without long-term memory, returns 0."""
        state = _make_state(long_term_memory=None)
        handler = ChatHandler(state=state)
        assert handler._get_longterm_count() == 0


# ---------------------------------------------------------------------------
# process() - end-to-end with mocked services
# ---------------------------------------------------------------------------


class TestProcess:
    """Integration-style test for the process orchestration."""

    @patch("backend.core.chat_handler.classify_emotion", new_callable=AsyncMock)
    @patch("backend.core.chat_handler.strip_xml_tags", side_effect=lambda x: x)
    async def test_process_basic_flow(
        self,
        mock_strip,
        mock_emotion,
        mock_chat_state,
        mock_memory_manager,
    ):
        """process() yields STATUS, TEXT, STATUS(Idle), DONE events."""
        mock_emotion.return_value = "positive"

        # Build mock services
        context_service = AsyncMock()
        from backend.core.services.context_service import ContextResult
        context_service.build = AsyncMock(
            return_value=ContextResult(
                system_prompt="You are Axel.", stats={}, turn_count=3, elapsed_ms=10.0,
            )
        )

        search_service = AsyncMock()
        from backend.core.services.search_service import SearchResult
        search_service.search_if_needed = AsyncMock(
            return_value=SearchResult(context="", success=False)
        )

        tool_service = MagicMock()
        tool_service.mcp_client = None

        persistence_service = MagicMock()
        persistence_service.add_assistant_message = AsyncMock()
        persistence_service.persist_all = AsyncMock()

        # ReAct service yields a simple text response
        react_result = ReActResult(
            full_response="Hi there!",
            loops_completed=1,
            llm_elapsed_ms=200.0,
        )

        async def mock_react_run(**kwargs):
            yield ChatEvent(EventType.THINKING_START, "")
            yield ChatEvent(EventType.TEXT, "Hi there!")
            yield ChatEvent(EventType.THINKING_END, "")
            yield ChatEvent(EventType.CONTROL, "", metadata={"react_result": react_result})

        react_service = MagicMock()
        react_service.run = mock_react_run

        handler = ChatHandler(
            state=mock_chat_state,
            context_service=context_service,
            search_service=search_service,
            tool_service=tool_service,
            react_service=react_service,
            persistence_service=persistence_service,
        )

        # Patch _fetch_tools to avoid real MCP
        handler._fetch_tools = AsyncMock(return_value=(None, []))

        request = ChatRequest(user_input="Hello Axel!")

        events = await _collect_events(handler.process(request))

        # Verify event stream structure
        types = [e.type for e in events]

        # Must contain at least one STATUS and a DONE at the end
        assert EventType.STATUS in types
        assert types[-1] == EventType.DONE

        # TEXT events from react
        text_events = [e for e in events if e.type == EventType.TEXT]
        assert len(text_events) >= 1
        assert any("Hi there!" in e.content for e in text_events)

        # DONE metadata
        done_event = events[-1]
        assert "full_response" in done_event.metadata
        assert done_event.metadata["full_response"] == "Hi there!"

        # Persistence was called
        persistence_service.add_assistant_message.assert_called_once_with("Hi there!")

        # Memory manager had user message added
        mock_memory_manager.add_message.assert_called_once_with(
            "user", "Hello Axel!", emotional_context="neutral"
        )
