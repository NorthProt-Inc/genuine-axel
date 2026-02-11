"""Tests for backend.core.mcp_tools.memory_tools -- Memory tool handlers.

Each tool function is tested for:
  - Successful invocation with valid arguments
  - Missing/empty required parameters
  - Invalid parameter values
  - External dependency failure (exceptions)
  - Edge cases (empty results, corrupt data, etc.)

External dependencies (memory_server, file I/O) are mocked via conftest
fixtures or local patches.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.mcp_tools.memory_tools import (
    _read_file_safe,
    add_memory,
    get_recent_logs,
    memory_stats,
    query_axel_memory,
    retrieve_context,
    store_memory,
)


# ===========================================================================
# _read_file_safe
# ===========================================================================


class TestReadFileSafe:
    async def test_reads_existing_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world", encoding="utf-8")
        result = await _read_file_safe(f)
        assert result == "hello world"

    async def test_missing_file_returns_error(self, tmp_path):
        result = await _read_file_safe(tmp_path / "nonexistent.txt")
        assert "Error: File not found" in result

    async def test_read_error_returns_error(self, tmp_path):
        f = tmp_path / "noperm.txt"
        f.write_text("content")
        f.chmod(0o000)
        result = await _read_file_safe(f)
        assert "Error reading file" in result
        f.chmod(0o644)


# ===========================================================================
# query_axel_memory
# ===========================================================================


class TestQueryAxelMemory:
    async def test_finds_matching_messages(self, working_memory_file):
        with patch("backend.core.mcp_tools.memory_tools.WORKING_MEMORY_PATH", working_memory_file):
            result = await query_axel_memory({"query": "alice"})
        assert len(result) == 1
        text = result[0].text
        assert "Alice" in text

    async def test_no_matches(self, working_memory_file):
        with patch("backend.core.mcp_tools.memory_tools.WORKING_MEMORY_PATH", working_memory_file):
            result = await query_axel_memory({"query": "nonexistent_term_xyz"})
        text = result[0].text
        assert "No matches found" in text

    async def test_empty_query_returns_error(self):
        result = await query_axel_memory({"query": ""})
        assert "Error" in result[0].text
        assert "query parameter is required" in result[0].text

    async def test_missing_query_returns_error(self):
        result = await query_axel_memory({})
        assert "Error" in result[0].text

    async def test_corrupt_file(self, corrupt_working_memory_file):
        with patch("backend.core.mcp_tools.memory_tools.WORKING_MEMORY_PATH", corrupt_working_memory_file):
            result = await query_axel_memory({"query": "test"})
        assert "corrupt" in result[0].text.lower()

    async def test_file_not_found(self, tmp_path):
        missing = tmp_path / "missing.json"
        with patch("backend.core.mcp_tools.memory_tools.WORKING_MEMORY_PATH", missing):
            result = await query_axel_memory({"query": "test"})
        # _read_file_safe returns error string, which is not valid JSON
        assert "Error" in result[0].text

    async def test_case_insensitive_search(self, working_memory_file):
        with patch("backend.core.mcp_tools.memory_tools.WORKING_MEMORY_PATH", working_memory_file):
            result = await query_axel_memory({"query": "PYTHON"})
        text = result[0].text
        assert "Python" in text

    async def test_multiple_matches(self, tmp_path):
        data = {
            "messages": [
                {"role": "user", "content": "I like cats", "timestamp": "2025-01-01T00:00:00"},
                {"role": "user", "content": "cats are great", "timestamp": "2025-01-01T00:01:00"},
                {"role": "user", "content": "dogs too", "timestamp": "2025-01-01T00:02:00"},
            ]
        }
        f = tmp_path / "wm.json"
        f.write_text(json.dumps(data), encoding="utf-8")
        with patch("backend.core.mcp_tools.memory_tools.WORKING_MEMORY_PATH", f):
            result = await query_axel_memory({"query": "cats"})
        text = result[0].text
        assert text.count("cats") >= 2


# ===========================================================================
# add_memory
# ===========================================================================


class TestAddMemory:
    async def test_adds_to_existing_file(self, working_memory_file):
        with patch("backend.core.mcp_tools.memory_tools.WORKING_MEMORY_PATH", working_memory_file):
            result = await add_memory({"content": "New fact about user", "category": "fact"})
        text = result[0].text
        assert "successfully" in text.lower()

        data = json.loads(working_memory_file.read_text())
        last_msg = data["messages"][-1]
        assert "INJECTED_MEMORY:FACT" in last_msg["content"]
        assert "New fact about user" in last_msg["content"]
        assert last_msg["role"] == "system"

    async def test_creates_file_if_missing(self, tmp_path):
        f = tmp_path / "new_memory.json"
        with patch("backend.core.mcp_tools.memory_tools.WORKING_MEMORY_PATH", f):
            result = await add_memory({"content": "First memory"})
        assert "successfully" in result[0].text.lower()
        assert f.exists()
        data = json.loads(f.read_text())
        assert len(data["messages"]) == 1

    async def test_empty_content_returns_error(self):
        result = await add_memory({"content": ""})
        assert "Error" in result[0].text
        assert "content parameter is required" in result[0].text

    async def test_missing_content_returns_error(self):
        result = await add_memory({})
        assert "Error" in result[0].text

    async def test_invalid_category_returns_error(self):
        result = await add_memory({"content": "test", "category": "invalid_cat"})
        assert "Error" in result[0].text
        assert "invalid category" in result[0].text.lower()

    async def test_default_category_is_observation(self, tmp_path):
        f = tmp_path / "wm.json"
        f.write_text(json.dumps({"messages": []}), encoding="utf-8")
        with patch("backend.core.mcp_tools.memory_tools.WORKING_MEMORY_PATH", f):
            await add_memory({"content": "Some note"})
        data = json.loads(f.read_text())
        assert "OBSERVATION" in data["messages"][-1]["content"]

    async def test_all_valid_categories(self, tmp_path):
        for cat in ["observation", "fact", "code"]:
            f = tmp_path / f"wm_{cat}.json"
            f.write_text(json.dumps({"messages": []}), encoding="utf-8")
            with patch("backend.core.mcp_tools.memory_tools.WORKING_MEMORY_PATH", f):
                result = await add_memory({"content": "test", "category": cat})
            assert "successfully" in result[0].text.lower()

    async def test_truncates_at_100_messages(self, tmp_path):
        data = {
            "messages": [
                {"role": "user", "content": f"msg {i}", "timestamp": f"2025-01-01T{i:02d}:00:00"}
                for i in range(100)
            ]
        }
        f = tmp_path / "wm.json"
        f.write_text(json.dumps(data), encoding="utf-8")
        with patch("backend.core.mcp_tools.memory_tools.WORKING_MEMORY_PATH", f):
            await add_memory({"content": "new msg"})
        data = json.loads(f.read_text())
        assert len(data["messages"]) == 100  # truncated to last 100

    async def test_write_error(self, tmp_path):
        f = tmp_path / "wm.json"
        f.write_text(json.dumps({"messages": []}), encoding="utf-8")
        f.chmod(0o444)  # read-only
        with patch("backend.core.mcp_tools.memory_tools.WORKING_MEMORY_PATH", f):
            result = await add_memory({"content": "test"})
        assert "Error" in result[0].text
        f.chmod(0o644)


# ===========================================================================
# store_memory
# ===========================================================================


class TestStoreMemory:
    async def test_success(self, mock_memory_store):
        result = await store_memory({
            "content": "User's favorite color is blue",
            "category": "preference",
            "importance": 0.7,
        })
        text = result[0].text
        assert "abc12345" in text
        assert "Memory stored" in text or "stored" in text.lower()
        mock_memory_store.assert_awaited_once_with(
            content="User's favorite color is blue",
            category="preference",
            importance=0.7,
        )

    async def test_empty_content_returns_error(self):
        result = await store_memory({"content": ""})
        assert "Error" in result[0].text

    async def test_missing_content_returns_error(self):
        result = await store_memory({})
        assert "Error" in result[0].text

    async def test_invalid_category_returns_error(self):
        result = await store_memory({"content": "test", "category": "invalid"})
        assert "Error" in result[0].text

    async def test_importance_out_of_range_low(self):
        result = await store_memory({"content": "test", "importance": -0.1})
        assert "Error" in result[0].text

    async def test_importance_out_of_range_high(self):
        result = await store_memory({"content": "test", "importance": 1.5})
        assert "Error" in result[0].text

    async def test_importance_non_numeric(self):
        result = await store_memory({"content": "test", "importance": "high"})
        assert "Error" in result[0].text

    async def test_default_category_and_importance(self, mock_memory_store):
        await store_memory({"content": "something"})
        mock_memory_store.assert_awaited_once_with(
            content="something",
            category="conversation",
            importance=0.5,
        )

    async def test_store_failure(self):
        with patch(
            "backend.protocols.mcp.memory_server.store_memory",
            new_callable=AsyncMock,
            return_value={"success": False, "error": "DB connection failed"},
        ):
            result = await store_memory({"content": "test", "category": "fact"})
        assert "failed" in result[0].text.lower() or "Store failed" in result[0].text

    async def test_store_exception(self):
        with patch(
            "backend.protocols.mcp.memory_server.store_memory",
            new_callable=AsyncMock,
            side_effect=RuntimeError("network error"),
        ):
            result = await store_memory({"content": "test", "category": "fact"})
        assert "Error" in result[0].text
        assert "network error" in result[0].text

    async def test_memory_id_na_fallback(self):
        with patch(
            "backend.protocols.mcp.memory_server.store_memory",
            new_callable=AsyncMock,
            return_value={"success": True, "memory_id": None, "category": "fact", "importance": 0.5},
        ):
            result = await store_memory({"content": "test", "category": "fact"})
        assert "N/A" in result[0].text


# ===========================================================================
# retrieve_context
# ===========================================================================


class TestRetrieveContext:
    async def test_success(self, mock_memory_retrieve):
        result = await retrieve_context({"query": "user preferences"})
        text = result[0].text
        assert "Context Retrieved" in text
        assert "Alice" in text
        assert "ChromaDB: 3" in text
        assert "Graph: 2" in text

    async def test_empty_query_returns_error(self):
        result = await retrieve_context({"query": ""})
        assert "Error" in result[0].text

    async def test_missing_query_returns_error(self):
        result = await retrieve_context({})
        assert "Error" in result[0].text

    async def test_invalid_max_results_zero(self):
        result = await retrieve_context({"query": "test", "max_results": 0})
        assert "Error" in result[0].text

    async def test_invalid_max_results_over_25(self):
        result = await retrieve_context({"query": "test", "max_results": 26})
        assert "Error" in result[0].text

    async def test_invalid_max_results_not_int(self):
        result = await retrieve_context({"query": "test", "max_results": "ten"})
        assert "Error" in result[0].text

    async def test_default_max_results(self, mock_memory_retrieve):
        await retrieve_context({"query": "test"})
        mock_memory_retrieve.assert_awaited_once_with(query="test", max_results=10)

    async def test_retrieve_failure(self):
        with patch(
            "backend.protocols.mcp.memory_server.retrieve_context",
            new_callable=AsyncMock,
            return_value={"success": False, "error": "ChromaDB unavailable"},
        ):
            result = await retrieve_context({"query": "test"})
        assert "failed" in result[0].text.lower() or "Retrieve failed" in result[0].text

    async def test_retrieve_exception(self):
        with patch(
            "backend.protocols.mcp.memory_server.retrieve_context",
            new_callable=AsyncMock,
            side_effect=ConnectionError("timeout"),
        ):
            result = await retrieve_context({"query": "test"})
        assert "Error" in result[0].text
        assert "timeout" in result[0].text


# ===========================================================================
# get_recent_logs
# ===========================================================================


class TestGetRecentLogs:
    async def test_success(self, mock_memory_get_logs):
        result = await get_recent_logs({"limit": 20})
        text = result[0].text
        assert "Recent Logs" in text
        assert "42 total interactions" in text
        assert "Python" in text

    async def test_default_limit(self, mock_memory_get_logs):
        await get_recent_logs({})
        mock_memory_get_logs.assert_awaited_once_with(limit=50)

    async def test_invalid_limit_zero(self):
        result = await get_recent_logs({"limit": 0})
        assert "Error" in result[0].text

    async def test_invalid_limit_over_100(self):
        result = await get_recent_logs({"limit": 101})
        assert "Error" in result[0].text

    async def test_invalid_limit_not_int(self):
        result = await get_recent_logs({"limit": "fifty"})
        assert "Error" in result[0].text

    async def test_logs_failure(self):
        with patch(
            "backend.protocols.mcp.memory_server.get_recent_logs",
            new_callable=AsyncMock,
            return_value={"success": False, "error": "DB locked"},
        ):
            result = await get_recent_logs({})
        assert "failed" in result[0].text.lower() or "Logs failed" in result[0].text

    async def test_logs_exception(self):
        with patch(
            "backend.protocols.mcp.memory_server.get_recent_logs",
            new_callable=AsyncMock,
            side_effect=RuntimeError("crash"),
        ):
            result = await get_recent_logs({})
        assert "Error" in result[0].text


# ===========================================================================
# memory_stats
# ===========================================================================


class TestMemoryStats:
    async def test_working_memory_present(self, working_memory_file):
        with patch("backend.core.mcp_tools.memory_tools.WORKING_MEMORY_PATH", working_memory_file):
            # Patch the LTM / GraphRAG / cache imports to avoid real dependencies
            with patch("backend.memory.permanent.LongTermMemory") as mock_ltm, \
                 patch("backend.memory.graph_rag.GraphRAG") as mock_graph, \
                 patch("backend.core.utils.get_all_cache_stats", return_value={}):
                mock_ltm.return_value.get_stats.return_value = {
                    "total_documents": 50,
                    "categories": {"fact": 20, "preference": 30},
                    "embedding_cache_size": 10,
                }
                mock_graph.return_value.get_stats.return_value = {
                    "entity_count": 25,
                    "relationship_count": 15,
                }
                result = await memory_stats({})

        text = result[0].text
        assert "Memory System Statistics" in text
        assert "Messages: 3" in text

    async def test_working_memory_missing(self, tmp_path):
        missing = tmp_path / "nonexistent.json"
        with patch("backend.core.mcp_tools.memory_tools.WORKING_MEMORY_PATH", missing):
            with patch("backend.memory.permanent.LongTermMemory", side_effect=Exception("no db")), \
                 patch("backend.memory.graph_rag.GraphRAG", side_effect=Exception("no graph")), \
                 patch("backend.core.utils.get_all_cache_stats", side_effect=Exception("no cache")):
                result = await memory_stats({})
        text = result[0].text
        assert "Not initialized" in text

    async def test_ltm_error_handled(self, working_memory_file):
        with patch("backend.core.mcp_tools.memory_tools.WORKING_MEMORY_PATH", working_memory_file):
            with patch("backend.memory.permanent.LongTermMemory", side_effect=ImportError("missing")), \
                 patch("backend.memory.graph_rag.GraphRAG", side_effect=Exception("err")), \
                 patch("backend.core.utils.get_all_cache_stats", return_value={}):
                result = await memory_stats({})
        text = result[0].text
        assert "Long-term Memory: Error" in text

    async def test_graphrag_error_handled(self, working_memory_file):
        with patch("backend.core.mcp_tools.memory_tools.WORKING_MEMORY_PATH", working_memory_file):
            with patch("backend.memory.permanent.LongTermMemory") as mock_ltm, \
                 patch("backend.memory.graph_rag.GraphRAG", side_effect=Exception("graph failed")), \
                 patch("backend.core.utils.get_all_cache_stats", return_value={}):
                mock_ltm.return_value.get_stats.return_value = {}
                result = await memory_stats({})
        text = result[0].text
        assert "Knowledge Graph: Error" in text

    async def test_cache_stats_shown(self, working_memory_file):
        cache_stats = {
            "embedding": {"size": 50, "maxsize": 100, "hit_rate": "85.0%"},
        }
        with patch("backend.core.mcp_tools.memory_tools.WORKING_MEMORY_PATH", working_memory_file):
            with patch("backend.memory.permanent.LongTermMemory") as mock_ltm, \
                 patch("backend.memory.graph_rag.GraphRAG") as mock_graph, \
                 patch("backend.core.utils.get_all_cache_stats", return_value=cache_stats):
                mock_ltm.return_value.get_stats.return_value = {}
                mock_graph.return_value.get_stats.return_value = {}
                result = await memory_stats({})
        text = result[0].text
        assert "embedding" in text
        assert "50/100" in text

    async def test_no_caches_configured(self, working_memory_file):
        with patch("backend.core.mcp_tools.memory_tools.WORKING_MEMORY_PATH", working_memory_file):
            with patch("backend.memory.permanent.LongTermMemory") as mock_ltm, \
                 patch("backend.memory.graph_rag.GraphRAG") as mock_graph, \
                 patch("backend.core.utils.get_all_cache_stats", return_value={}):
                mock_ltm.return_value.get_stats.return_value = {}
                mock_graph.return_value.get_stats.return_value = {}
                result = await memory_stats({})
        text = result[0].text
        assert "None configured" in text

    async def test_corrupt_working_memory_handled(self, corrupt_working_memory_file):
        with patch("backend.core.mcp_tools.memory_tools.WORKING_MEMORY_PATH", corrupt_working_memory_file):
            with patch("backend.memory.permanent.LongTermMemory", side_effect=Exception("err")), \
                 patch("backend.memory.graph_rag.GraphRAG", side_effect=Exception("err")), \
                 patch("backend.core.utils.get_all_cache_stats", return_value={}):
                result = await memory_stats({})
        text = result[0].text
        assert "Working Memory: Error" in text

    async def test_top_level_exception(self):
        """Edge case: total crash in memory_stats."""
        with patch(
            "backend.core.mcp_tools.memory_tools.WORKING_MEMORY_PATH",
            new_callable=lambda: property(lambda self: (_ for _ in ()).throw(RuntimeError("boom"))),
        ):
            # Simulating an unlikely crash at the top level
            with patch("backend.core.mcp_tools.memory_tools.json.loads", side_effect=RuntimeError("total crash")):
                with patch("backend.core.mcp_tools.memory_tools.WORKING_MEMORY_PATH") as mock_path:
                    mock_path.exists.side_effect = RuntimeError("total crash")
                    with patch("backend.memory.permanent.LongTermMemory", side_effect=Exception), \
                         patch("backend.memory.graph_rag.GraphRAG", side_effect=Exception), \
                         patch("backend.core.utils.get_all_cache_stats", side_effect=Exception):
                        result = await memory_stats({})
        text = result[0].text
        # Should still return something (error sections) rather than crash
        assert "Memory System Statistics" in text or "Stats Error" in text
