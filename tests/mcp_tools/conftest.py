"""Shared fixtures for MCP tool tests.

Provides mock objects for state, memory managers, and external services
so that tool handler tests run in full isolation with no I/O.
"""

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Registry isolation
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_registry():
    """Snapshot and restore the global tool registry around every test.

    Without this, registering tools in one test would leak into others
    (the module-level dicts are mutable singletons).
    """
    from backend.core.mcp_tools import (
        _tool_handlers,
        _tool_metadata,
        _tool_metrics,
    )

    handlers_snapshot = dict(_tool_handlers)
    metadata_snapshot = dict(_tool_metadata)
    metrics_snapshot = dict(_tool_metrics)

    yield

    _tool_handlers.clear()
    _tool_handlers.update(handlers_snapshot)

    _tool_metadata.clear()
    _tool_metadata.update(metadata_snapshot)

    _tool_metrics.clear()
    _tool_metrics.update(metrics_snapshot)


# ---------------------------------------------------------------------------
# Working-memory file helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def working_memory_file(tmp_path: Path) -> Path:
    """Create a temporary working-memory JSON file with sample messages."""
    data = {
        "messages": [
            {
                "role": "user",
                "content": "Hello Axel, my name is Alice",
                "timestamp": "2025-01-15T10:00:00",
                "emotional_context": "neutral",
            },
            {
                "role": "assistant",
                "content": "Hello Alice! Nice to meet you.",
                "timestamp": "2025-01-15T10:00:05",
                "emotional_context": "happy",
            },
            {
                "role": "user",
                "content": "I like Python programming",
                "timestamp": "2025-01-15T10:01:00",
                "emotional_context": "neutral",
            },
        ]
    }
    p = tmp_path / "working_memory.json"
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return p


@pytest.fixture
def empty_working_memory_file(tmp_path: Path) -> Path:
    """Create an empty working-memory JSON file."""
    p = tmp_path / "working_memory.json"
    p.write_text(json.dumps({"messages": []}, indent=2), encoding="utf-8")
    return p


@pytest.fixture
def corrupt_working_memory_file(tmp_path: Path) -> Path:
    """Create a corrupt (non-JSON) working-memory file."""
    p = tmp_path / "working_memory.json"
    p.write_text("NOT VALID JSON {{{", encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Patch targets for memory_tools external dependencies
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_memory_store():
    """Mock ``backend.protocols.mcp.memory_server.store_memory``."""
    with patch(
        "backend.protocols.mcp.memory_server.store_memory",
        new_callable=AsyncMock,
    ) as m:
        m.return_value = {
            "success": True,
            "memory_id": "abc12345-6789-0000-0000-000000000000",
            "category": "fact",
            "importance": 0.8,
        }
        yield m


@pytest.fixture
def mock_memory_retrieve():
    """Mock ``backend.protocols.mcp.memory_server.retrieve_context``."""
    with patch(
        "backend.protocols.mcp.memory_server.retrieve_context",
        new_callable=AsyncMock,
    ) as m:
        m.return_value = {
            "success": True,
            "context": "User's name is Alice. She likes Python.",
            "metadata": {
                "chromadb_results": 3,
                "graph_entities": 2,
            },
        }
        yield m


@pytest.fixture
def mock_memory_get_logs():
    """Mock ``backend.protocols.mcp.memory_server.get_recent_logs``."""
    with patch(
        "backend.protocols.mcp.memory_server.get_recent_logs",
        new_callable=AsyncMock,
    ) as m:
        m.return_value = {
            "success": True,
            "session_summaries": "Session 1: Discussed Python.\nSession 2: Discussed AI.",
            "interaction_count": 42,
        }
        yield m


# ---------------------------------------------------------------------------
# Patch targets for research_tools external dependencies
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_web_search_engine():
    """Mock ``backend.protocols.mcp.research.search_engines.web_search``."""
    with patch(
        "backend.protocols.mcp.research.search_engines.web_search",
        new_callable=AsyncMock,
    ) as m:
        m.return_value = "1. Example Result - https://example.com\nSnippet text"
        yield m


@pytest.fixture
def mock_visit_page():
    """Mock ``backend.protocols.mcp.research.page_visitor.visit_page``."""
    with patch(
        "backend.protocols.mcp.research.page_visitor.visit_page",
        new_callable=AsyncMock,
    ) as m:
        m.return_value = "# Page Title\n\nPage content in markdown."
        yield m


@pytest.fixture
def mock_deep_dive():
    """Mock ``backend.protocols.mcp.research.page_visitor.deep_dive``."""
    with patch(
        "backend.protocols.mcp.research.page_visitor.deep_dive",
        new_callable=AsyncMock,
    ) as m:
        m.return_value = "## Research Report\n\nFindings from 3 pages..."
        yield m


@pytest.fixture
def mock_tavily_search_engine():
    """Mock ``backend.protocols.mcp.research.search_engines.tavily_search``."""
    with patch(
        "backend.protocols.mcp.research.search_engines.tavily_search",
        new_callable=AsyncMock,
    ) as m:
        m.return_value = "Tavily AI summary: Result 1, Result 2"
        yield m


@pytest.fixture
def mock_read_artifact():
    """Mock ``backend.core.research_artifacts.read_artifact``."""
    with patch("backend.core.research_artifacts.read_artifact") as m:
        m.return_value = "Full artifact content here."
        yield m


@pytest.fixture
def mock_list_artifacts():
    """Mock ``backend.core.research_artifacts.list_artifacts``."""
    with patch("backend.core.research_artifacts.list_artifacts") as m:
        m.return_value = [
            {
                "path": "/artifacts/example.md",
                "url": "https://example.com",
                "saved_at": "2025-01-15T12:00:00",
                "size": 4096,
            }
        ]
        yield m


# ---------------------------------------------------------------------------
# Patch targets for file_tools external dependencies
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_validate_path():
    """Mock ``backend.core.utils.path_validator.validate_path``."""
    with patch("backend.core.mcp_tools.file_tools.validate_path") as m:
        m.return_value = (True, None)
        yield m


@pytest.fixture
def mock_sanitize_path():
    """Mock ``backend.core.mcp_tools.file_tools.sanitize_path``."""
    with patch("backend.core.mcp_tools.file_tools.sanitize_path") as m:
        m.side_effect = lambda p: p  # passthrough
        yield m
