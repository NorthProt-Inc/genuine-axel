"""W4-2: Verify GraphRAG → M3 connection_count feedback."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.services.memory_persistence_service import MemoryPersistenceService


class TestGraphM3Feedback:

    async def test_connection_count_updated_on_entity_extraction(self):
        mm = MagicMock()
        mm.is_working_available.return_value = False
        mm.is_graph_rag_available.return_value = True
        mm.graph_rag.extract_and_store = AsyncMock(
            return_value={"entities_added": 3, "relations_added": 1}
        )

        lt = MagicMock()
        lt.query.return_value = [
            {"id": "mem-1", "content": "test", "metadata": {"connection_count": 2}},
        ]
        lt._repository = MagicMock()

        svc = MemoryPersistenceService(
            memory_manager=mm, long_term_memory=lt
        )

        await svc._extract_graph("user input", "ai response")

        # Verify connection_count was incremented
        lt._repository.update_metadata.assert_called_once_with(
            "mem-1", {"connection_count": 5}  # 2 + 3 new entities
        )

    async def test_no_update_when_no_entities_added(self):
        mm = MagicMock()
        mm.graph_rag.extract_and_store = AsyncMock(
            return_value={"entities_added": 0, "relations_added": 0}
        )

        lt = MagicMock()
        svc = MemoryPersistenceService(memory_manager=mm, long_term_memory=lt)

        await svc._extract_graph("hi", "hello")

        lt.query.assert_not_called()

    async def test_no_crash_when_no_longterm(self):
        mm = MagicMock()
        mm.graph_rag.extract_and_store = AsyncMock(
            return_value={"entities_added": 2, "relations_added": 0}
        )

        svc = MemoryPersistenceService(memory_manager=mm, long_term_memory=None)

        # Should not crash
        result = await svc._extract_graph("test", "response")
        assert result["entities_added"] == 2

    async def test_connection_count_starts_from_zero(self):
        mm = MagicMock()
        mm.is_graph_rag_available.return_value = True
        mm.graph_rag.extract_and_store = AsyncMock(
            return_value={"entities_added": 1, "relations_added": 0}
        )

        lt = MagicMock()
        lt.query.return_value = [
            {"id": "mem-new", "content": "new memory", "metadata": {}},
        ]
        lt._repository = MagicMock()

        svc = MemoryPersistenceService(memory_manager=mm, long_term_memory=lt)

        await svc._extract_graph("query", "response")

        lt._repository.update_metadata.assert_called_once_with(
            "mem-new", {"connection_count": 1}  # 0 + 1
        )
