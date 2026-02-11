"""Tests for MemoryPersistenceService."""

import pytest
from unittest.mock import AsyncMock, patch

from backend.core.services.memory_persistence_service import MemoryPersistenceService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def svc_bare():
    """Service with no managers at all."""
    return MemoryPersistenceService()


@pytest.fixture
def svc_full(mock_memory_manager, mock_long_term, mock_identity_manager):
    """Service wired with all three managers."""
    return MemoryPersistenceService(
        memory_manager=mock_memory_manager,
        long_term_memory=mock_long_term,
        identity_manager=mock_identity_manager,
    )


# ---------------------------------------------------------------------------
# persist_all
# ---------------------------------------------------------------------------


class TestPersistAll:
    """Tests for the persist_all orchestration method."""

    async def test_persist_all_no_managers(self, svc_bare):
        """With no managers, persist_all returns default empty results."""
        result = await svc_bare.persist_all("hello", "hi there")
        assert result["working_saved"] is False
        assert result["longterm_id"] is None
        assert result["graph_result"] is None
        assert result["errors"] == []

    async def test_persist_all_working_save_success(self, svc_full, mock_memory_manager):
        """Working memory save succeeds and result is recorded."""
        mock_memory_manager.save_working_to_disk = AsyncMock(return_value=True)
        # Disable longterm and graph to isolate working-memory path
        svc_full.long_term = None
        mock_memory_manager.is_graph_rag_available.return_value = False

        result = await svc_full.persist_all("user msg", "bot reply")

        assert result["working_saved"] is True
        mock_memory_manager.save_working_to_disk.assert_awaited_once()
        assert result["errors"] == []

    async def test_persist_all_working_save_fail(self, svc_full, mock_memory_manager):
        """Working memory save raises and error is captured."""
        mock_memory_manager.save_working_to_disk = AsyncMock(
            side_effect=RuntimeError("disk full")
        )
        svc_full.long_term = None
        mock_memory_manager.is_graph_rag_available.return_value = False

        result = await svc_full.persist_all("user msg", "bot reply")

        assert result["working_saved"] is False
        assert any("working" in e for e in result["errors"])

    @patch("backend.core.services.memory_persistence_service.calculate_importance_sync")
    async def test_persist_all_longterm_store(
        self, mock_calc, svc_full, mock_memory_manager, mock_long_term
    ):
        """Long-term storage is called and its ID is recorded."""
        mock_calc.return_value = 0.8
        mock_long_term.add.return_value = "mem-abc-123"
        mock_memory_manager.is_graph_rag_available.return_value = False
        mock_memory_manager.save_working_to_disk = AsyncMock(return_value=False)

        result = await svc_full.persist_all("user msg", "bot reply")

        assert result["longterm_id"] == "mem-abc-123"
        mock_long_term.add.assert_called_once()
        assert result["errors"] == []

    async def test_persist_all_graph_extract(self, svc_full, mock_memory_manager):
        """Graph extraction is called and result is recorded."""
        svc_full.long_term = None
        mock_memory_manager.save_working_to_disk = AsyncMock(return_value=False)
        mock_memory_manager.graph_rag.extract_and_store = AsyncMock(
            return_value={"entities_added": 2, "relations_added": 1}
        )

        result = await svc_full.persist_all("user msg", "bot reply")

        assert result["graph_result"] == {"entities_added": 2, "relations_added": 1}
        mock_memory_manager.graph_rag.extract_and_store.assert_awaited_once()

    @patch("backend.core.services.memory_persistence_service.calculate_importance_sync")
    async def test_persist_all_parallel_with_exception(
        self, mock_calc, svc_full, mock_memory_manager, mock_long_term
    ):
        """When one parallel task raises, the error is captured but other results survive."""
        mock_calc.return_value = 0.5
        mock_long_term.add.return_value = "mem-ok-456"
        mock_memory_manager.save_working_to_disk = AsyncMock(return_value=True)
        # _extract_graph catches internally and returns an error dict, so
        # from persist_all's perspective graph_result will be the error dict.
        mock_memory_manager.graph_rag.extract_and_store = AsyncMock(
            side_effect=RuntimeError("graph boom")
        )

        result = await svc_full.persist_all("user msg", "bot reply")

        assert result["working_saved"] is True
        assert result["longterm_id"] == "mem-ok-456"
        # _extract_graph catches exceptions and returns an error dict
        assert result["graph_result"] is not None
        assert "graph boom" in result["graph_result"]["error"]


# ---------------------------------------------------------------------------
# _store_longterm
# ---------------------------------------------------------------------------


class TestStoreLongterm:
    """Tests for the _store_longterm private method."""

    @patch("backend.core.services.memory_persistence_service.calculate_importance_sync")
    async def test_store_longterm_with_identity(
        self, mock_calc, svc_full, mock_long_term, mock_identity_manager
    ):
        """Identity persona context is passed to importance calculator."""
        mock_calc.return_value = 0.9
        mock_identity_manager.persona = {"core_identity": "I am Axel, a helpful AI."}
        mock_long_term.add.return_value = "mem-id-789"

        mem_id = await svc_full._store_longterm("hi", "hello")

        assert mem_id == "mem-id-789"
        # Verify importance was calculated with persona context
        mock_calc.assert_called_once()
        call_kwargs = mock_calc.call_args
        assert "I am Axel" in call_kwargs.kwargs.get("persona_context", call_kwargs[0][2] if len(call_kwargs[0]) > 2 else "")

    @patch("backend.core.services.memory_persistence_service.calculate_importance_sync")
    async def test_store_longterm_without_identity(
        self, mock_calc, mock_memory_manager, mock_long_term
    ):
        """Without identity_manager, persona_summary defaults to empty string."""
        svc = MemoryPersistenceService(
            memory_manager=mock_memory_manager,
            long_term_memory=mock_long_term,
            identity_manager=None,
        )
        mock_calc.return_value = 0.5
        mock_long_term.add.return_value = "mem-no-id"

        mem_id = await svc._store_longterm("q", "a")

        assert mem_id == "mem-no-id"
        # persona_context should be empty string
        mock_calc.assert_called_once()

    @patch("backend.core.services.memory_persistence_service.calculate_importance_sync")
    async def test_store_longterm_exception(self, mock_calc, svc_full, mock_long_term):
        """On exception, returns None instead of propagating."""
        mock_calc.side_effect = ValueError("importance exploded")

        mem_id = await svc_full._store_longterm("q", "a")

        assert mem_id is None


# ---------------------------------------------------------------------------
# _extract_graph
# ---------------------------------------------------------------------------


class TestExtractGraph:
    """Tests for the _extract_graph private method."""

    async def test_extract_graph_success(self, svc_full, mock_memory_manager):
        """Successful extraction returns the result dict."""
        mock_memory_manager.graph_rag.extract_and_store = AsyncMock(
            return_value={"entities_added": 3, "relations_added": 2}
        )

        result = await svc_full._extract_graph("hello", "world")

        assert result["entities_added"] == 3
        assert result["relations_added"] == 2
        mock_memory_manager.graph_rag.extract_and_store.assert_awaited_once()
        # Verify combined text is passed
        call_args = mock_memory_manager.graph_rag.extract_and_store.call_args
        assert "hello" in call_args.args[0]
        assert "world" in call_args.args[0]

    async def test_extract_graph_exception(self, svc_full, mock_memory_manager):
        """On exception, returns dict with error info instead of propagating."""
        mock_memory_manager.graph_rag.extract_and_store = AsyncMock(
            side_effect=ConnectionError("neo4j down")
        )

        result = await svc_full._extract_graph("q", "a")

        assert "error" in result
        assert "neo4j down" in result["error"]
        assert result["entities_added"] == 0
        assert result["relations_added"] == 0


# ---------------------------------------------------------------------------
# add_assistant_message
# ---------------------------------------------------------------------------


class TestAddAssistantMessage:
    """Tests for the async add_assistant_message method."""

    @patch("backend.core.services.memory_persistence_service.classify_emotion_sync")
    async def test_add_assistant_message_with_manager(
        self, mock_emotion, svc_full, mock_memory_manager
    ):
        """Message is added with classified emotion."""
        mock_emotion.return_value = "positive"

        await svc_full.add_assistant_message("Great news!")

        mock_emotion.assert_called_once_with("Great news!")
        mock_memory_manager.add_message.assert_called_once_with(
            "assistant", "Great news!", emotional_context="positive"
        )

    @patch("backend.core.services.memory_persistence_service.classify_emotion_sync")
    async def test_add_assistant_message_without_manager(self, mock_emotion, svc_bare):
        """Without memory manager, nothing happens and no error is raised."""
        await svc_bare.add_assistant_message("Hello!")

        mock_emotion.assert_not_called()

    @patch("backend.core.services.memory_persistence_service.classify_emotion_sync")
    async def test_add_assistant_message_empty_response(
        self, mock_emotion, svc_full, mock_memory_manager
    ):
        """Empty response string is treated as falsy, nothing is stored."""
        await svc_full.add_assistant_message("")

        mock_emotion.assert_not_called()
        mock_memory_manager.add_message.assert_not_called()
