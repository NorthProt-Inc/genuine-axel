"""Shared fixtures for service-layer tests."""

import pytest
from unittest.mock import AsyncMock, MagicMock, PropertyMock


# ---------------------------------------------------------------------------
# MCP Client
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_mcp_client():
    """AsyncMock MCP client with call_tool and get_anthropic_tools."""
    client = AsyncMock()
    client.call_tool = AsyncMock(return_value={"success": True, "result": "ok"})
    client.get_anthropic_tools = AsyncMock(return_value=[])
    return client


# ---------------------------------------------------------------------------
# MemoryManager
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_memory_manager():
    """MagicMock implementing the MemoryManager interface."""
    mm = MagicMock()
    mm.is_working_available.return_value = True
    mm.is_graph_rag_available.return_value = True
    mm.is_session_archive_available.return_value = True
    mm.get_turn_count.return_value = 5
    mm.get_session_id.return_value = "session-test-001"
    mm.add_message = MagicMock()
    mm.save_working_to_disk = AsyncMock()
    mm.get_progressive_context = MagicMock(return_value="progressive context")
    mm.get_time_elapsed_context = MagicMock(return_value="time context")

    # Sub-components
    mm.graph_rag = MagicMock()
    mm.session_archive = MagicMock()
    mm.memgpt = MagicMock()
    mm.working = MagicMock()

    return mm


# ---------------------------------------------------------------------------
# LongTermMemory
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_long_term():
    """MagicMock for LongTermMemory."""
    lt = MagicMock()
    lt.add = MagicMock()
    lt.get_formatted_context = MagicMock(return_value="long-term context")
    lt.get_stats = MagicMock(return_value={"count": 10, "avg_importance": 0.7})
    lt.search = MagicMock(return_value=[])
    return lt


# ---------------------------------------------------------------------------
# IdentityManager
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_identity_manager():
    """MagicMock for IdentityManager."""
    im = MagicMock()
    im.get_system_prompt = MagicMock(return_value="You are Axel.")
    im.persona = {"name": "Axel", "traits": ["helpful"]}
    return im


# ---------------------------------------------------------------------------
# ChatStateProtocol
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_chat_state(mock_memory_manager, mock_long_term, mock_identity_manager):
    """MagicMock implementing ChatStateProtocol."""
    state = MagicMock()
    type(state).memory_manager = PropertyMock(return_value=mock_memory_manager)
    type(state).long_term_memory = PropertyMock(return_value=mock_long_term)
    type(state).identity_manager = PropertyMock(return_value=mock_identity_manager)
    type(state).background_tasks = PropertyMock(return_value=[])
    return state
