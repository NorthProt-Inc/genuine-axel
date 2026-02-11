"""Tests for backend.protocols.mcp.memory_server functions.

Covers:
- store_memory: category validation, importance clamping, GraphRAG extraction
- retrieve_context: ChromaDB query, temporal formatting, GraphRAG context
- get_recent_logs: session archive summaries and interaction logs
- _parse_timestamp: various timestamp formats
- _format_temporal_label: LATEST/OLD classification
- _format_memory_age: relative time strings
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _patch_components(mm=None, ltm=None, sa=None, gr=None):
    """Return a patch context manager for _get_memory_components."""
    return patch(
        "backend.protocols.mcp.memory_server._get_memory_components",
        return_value=(mm, ltm, sa, gr),
    )


# ---------------------------------------------------------------------------
# store_memory
# ---------------------------------------------------------------------------


class TestStoreMemory:

    async def test_store_success(self) -> None:
        from backend.protocols.mcp.memory_server import store_memory

        ltm = MagicMock()
        ltm.add.return_value = "abc-123-def"

        with _patch_components(ltm=ltm):
            result = await store_memory("hello world", category="fact", importance=0.8)

        assert result["success"] is True
        assert result["memory_id"] == "abc-123-def"
        assert result["category"] == "fact"
        assert result["importance"] == 0.8
        ltm.add.assert_called_once_with(
            content="hello world",
            memory_type="fact",
            importance=0.8,
            source_session=None,
        )

    async def test_store_invalid_category_defaults(self) -> None:
        from backend.protocols.mcp.memory_server import store_memory

        ltm = MagicMock()
        ltm.add.return_value = "id-1"

        with _patch_components(ltm=ltm):
            result = await store_memory("data", category="invalid_cat")

        assert result["success"] is True
        assert result["category"] == "conversation"

    async def test_store_importance_clamped_high(self) -> None:
        from backend.protocols.mcp.memory_server import store_memory

        ltm = MagicMock()
        ltm.add.return_value = "id-2"

        with _patch_components(ltm=ltm):
            result = await store_memory("data", importance=5.0)

        assert result["importance"] == 1.0

    async def test_store_importance_clamped_low(self) -> None:
        from backend.protocols.mcp.memory_server import store_memory

        ltm = MagicMock()
        ltm.add.return_value = "id-3"

        with _patch_components(ltm=ltm):
            result = await store_memory("data", importance=-2.0)

        assert result["importance"] == 0.0

    async def test_store_no_long_term(self) -> None:
        from backend.protocols.mcp.memory_server import store_memory

        with _patch_components(ltm=None):
            result = await store_memory("data")

        assert result["success"] is False
        assert "not available" in result["error"]

    async def test_store_with_graph_rag(self) -> None:
        from backend.protocols.mcp.memory_server import store_memory

        ltm = MagicMock()
        ltm.add.return_value = "id-4"
        gr = AsyncMock()

        with _patch_components(ltm=ltm, gr=gr):
            result = await store_memory("data")

        assert result["success"] is True
        gr.extract_and_store.assert_awaited_once_with("data", source="mcp_memory")

    async def test_store_graph_rag_error_ignored(self) -> None:
        from backend.protocols.mcp.memory_server import store_memory

        ltm = MagicMock()
        ltm.add.return_value = "id-5"
        gr = AsyncMock()
        gr.extract_and_store.side_effect = RuntimeError("graph fail")

        with _patch_components(ltm=ltm, gr=gr):
            result = await store_memory("data")

        assert result["success"] is True

    async def test_store_ltm_exception(self) -> None:
        from backend.protocols.mcp.memory_server import store_memory

        ltm = MagicMock()
        ltm.add.side_effect = RuntimeError("db error")

        with _patch_components(ltm=ltm):
            result = await store_memory("data")

        assert result["success"] is False
        assert "db error" in result["error"]

    async def test_store_valid_categories(self) -> None:
        from backend.protocols.mcp.memory_server import store_memory

        ltm = MagicMock()
        ltm.add.return_value = "id-x"

        for cat in ("fact", "preference", "conversation", "insight"):
            with _patch_components(ltm=ltm):
                result = await store_memory("data", category=cat)
            assert result["category"] == cat


# ---------------------------------------------------------------------------
# retrieve_context
# ---------------------------------------------------------------------------


class TestRetrieveContext:

    async def test_retrieve_no_backends(self) -> None:
        from backend.protocols.mcp.memory_server import retrieve_context

        with _patch_components():
            result = await retrieve_context("anything")

        assert result["success"] is True
        assert "No relevant memories" in result["context"]
        assert result["metadata"]["chromadb_results"] == 0

    async def test_retrieve_chromadb_results(self) -> None:
        from backend.protocols.mcp.memory_server import retrieve_context

        ltm = MagicMock()
        ltm.query.return_value = [
            {
                "content": "User likes Python",
                "metadata": {"created_at": "2025-01-01T12:00:00+00:00"},
            },
        ]

        with _patch_components(ltm=ltm):
            result = await retrieve_context("preferences", max_results=5)

        assert result["success"] is True
        assert "MEMORY CONTEXT" in result["context"]
        assert result["metadata"]["chromadb_results"] == 1

    async def test_retrieve_chromadb_exception_handled(self) -> None:
        from backend.protocols.mcp.memory_server import retrieve_context

        ltm = MagicMock()
        ltm.query.side_effect = RuntimeError("chroma down")

        with _patch_components(ltm=ltm):
            result = await retrieve_context("query")

        assert result["success"] is True
        assert "No relevant memories" in result["context"]

    async def test_retrieve_with_graph_rag(self) -> None:
        from backend.protocols.mcp.memory_server import retrieve_context

        graph_result = MagicMock()
        graph_result.context = "entity relationships here"
        graph_result.entities = ["A", "B"]
        graph_result.relations = ["A->B"]

        gr = MagicMock()
        gr.query_sync.return_value = graph_result

        with _patch_components(gr=gr):
            result = await retrieve_context("relationships")

        assert result["success"] is True
        assert "Relationship Context" in result["context"]
        assert result["metadata"]["graph_entities"] == 2
        assert result["metadata"]["graph_relations"] == 1

    async def test_retrieve_graph_rag_exception_handled(self) -> None:
        from backend.protocols.mcp.memory_server import retrieve_context

        gr = MagicMock()
        gr.query_sync.side_effect = RuntimeError("graph fail")

        with _patch_components(gr=gr):
            result = await retrieve_context("query")

        assert result["success"] is True

    async def test_retrieve_content_truncated_at_250(self) -> None:
        from backend.protocols.mcp.memory_server import retrieve_context

        long_content = "x" * 300
        ltm = MagicMock()
        ltm.query.return_value = [
            {
                "content": long_content,
                "metadata": {"created_at": "2025-01-01T00:00:00+00:00"},
            },
        ]

        with _patch_components(ltm=ltm):
            result = await retrieve_context("long")

        assert "..." in result["context"]

    async def test_retrieve_empty_query_results(self) -> None:
        from backend.protocols.mcp.memory_server import retrieve_context

        ltm = MagicMock()
        ltm.query.return_value = []

        with _patch_components(ltm=ltm):
            result = await retrieve_context("nothing")

        assert result["success"] is True
        assert "No relevant memories" in result["context"]


# ---------------------------------------------------------------------------
# get_recent_logs
# ---------------------------------------------------------------------------


class TestGetRecentLogs:

    async def test_logs_no_session_archive(self) -> None:
        from backend.protocols.mcp.memory_server import get_recent_logs

        with _patch_components(sa=None):
            result = await get_recent_logs()

        assert result["success"] is False
        assert "not available" in result["error"]

    async def test_logs_with_summaries(self) -> None:
        from backend.protocols.mcp.memory_server import get_recent_logs

        sa = MagicMock()
        sa.get_recent_summaries.return_value = "Session 1: Discussed Python"
        sa.get_stats.return_value = {"total_interactions": 42}
        sa.get_recent_interactions.return_value = [{"msg": "hello"}]

        with _patch_components(sa=sa):
            result = await get_recent_logs(limit=10)

        assert result["success"] is True
        assert "Python" in result["session_summaries"]
        assert result["interaction_count"] == 42
        assert len(result["recent_interactions"]) == 1

    async def test_logs_limit_capped(self) -> None:
        from backend.protocols.mcp.memory_server import get_recent_logs

        sa = MagicMock()
        sa.get_recent_summaries.return_value = "summaries"
        sa.get_stats.return_value = {"total_interactions": 0}

        with _patch_components(sa=sa):
            await get_recent_logs(limit=100)

        # limit should be capped to 20
        sa.get_recent_summaries.assert_called_once_with(limit=20, max_tokens=5000)

    async def test_logs_no_recent_interactions_attr(self) -> None:
        from backend.protocols.mcp.memory_server import get_recent_logs

        sa = MagicMock(spec=["get_recent_summaries", "get_stats"])
        sa.get_recent_summaries.return_value = "data"
        sa.get_stats.return_value = {"total_interactions": 5}

        with _patch_components(sa=sa):
            result = await get_recent_logs()

        assert result["success"] is True
        assert result["recent_interactions"] == []

    async def test_logs_archive_exception(self) -> None:
        from backend.protocols.mcp.memory_server import get_recent_logs

        sa = MagicMock()
        sa.get_recent_summaries.side_effect = RuntimeError("archive broken")

        with _patch_components(sa=sa):
            result = await get_recent_logs()

        assert result["success"] is False
        assert "archive broken" in result["error"]

    async def test_logs_empty_summaries(self) -> None:
        from backend.protocols.mcp.memory_server import get_recent_logs

        sa = MagicMock()
        sa.get_recent_summaries.return_value = ""
        sa.get_stats.return_value = {"total_interactions": 0}

        with _patch_components(sa=sa):
            result = await get_recent_logs()

        assert result["session_summaries"] == "No recent sessions."


# ---------------------------------------------------------------------------
# _parse_timestamp
# ---------------------------------------------------------------------------


class TestParseTimestamp:

    def test_iso_with_tz(self) -> None:
        from backend.protocols.mcp.memory_server import _parse_timestamp

        result = _parse_timestamp("2025-06-15T10:30:00+00:00")
        assert result is not None
        assert result.year == 2025
        assert result.month == 6
        assert result.tzinfo is not None

    def test_iso_with_z(self) -> None:
        from backend.protocols.mcp.memory_server import _parse_timestamp

        result = _parse_timestamp("2025-06-15T10:30:00Z")
        assert result is not None
        assert result.tzinfo is not None

    def test_iso_with_milliseconds(self) -> None:
        from backend.protocols.mcp.memory_server import _parse_timestamp

        result = _parse_timestamp("2025-06-15T10:30:00.123456+00:00")
        assert result is not None

    def test_date_only(self) -> None:
        from backend.protocols.mcp.memory_server import _parse_timestamp

        result = _parse_timestamp("2025-06-15")
        assert result is not None
        assert result.year == 2025

    def test_datetime_no_tz(self) -> None:
        from backend.protocols.mcp.memory_server import _parse_timestamp

        result = _parse_timestamp("2025-06-15 10:30:00")
        assert result is not None
        assert result.tzinfo == timezone.utc

    def test_empty_string(self) -> None:
        from backend.protocols.mcp.memory_server import _parse_timestamp

        assert _parse_timestamp("") is None

    def test_none_equivalent(self) -> None:
        from backend.protocols.mcp.memory_server import _parse_timestamp

        assert _parse_timestamp("") is None

    def test_garbage_string(self) -> None:
        from backend.protocols.mcp.memory_server import _parse_timestamp

        assert _parse_timestamp("not-a-date") is None


# ---------------------------------------------------------------------------
# _format_temporal_label
# ---------------------------------------------------------------------------


class TestFormatTemporalLabel:

    def test_empty_timestamp(self) -> None:
        from backend.protocols.mcp.memory_server import _format_temporal_label

        formatted, label = _format_temporal_label("")
        assert formatted == "unknown"
        assert label == "OLD"

    def test_recent_timestamp_is_latest(self) -> None:
        from backend.protocols.mcp.memory_server import _format_temporal_label

        now = datetime.now(timezone.utc)
        recent = (now - timedelta(hours=2)).isoformat()
        formatted, label = _format_temporal_label(recent)

        assert label == "LATEST"
        assert formatted != "unknown"

    def test_old_timestamp_is_old(self) -> None:
        from backend.protocols.mcp.memory_server import _format_temporal_label

        old = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        formatted, label = _format_temporal_label(old)

        assert label == "OLD"
        assert formatted != "unknown"

    def test_unparseable_timestamp(self) -> None:
        from backend.protocols.mcp.memory_server import _format_temporal_label

        formatted, label = _format_temporal_label("garbage")
        assert formatted == "unknown"
        assert label == "OLD"


# ---------------------------------------------------------------------------
# _format_memory_age
# ---------------------------------------------------------------------------


class TestFormatMemoryAge:

    def test_just_now(self) -> None:
        from backend.protocols.mcp.memory_server import _format_memory_age

        now = datetime.now(timezone.utc)
        ts = (now - timedelta(minutes=10)).isoformat()
        assert _format_memory_age(ts) == "just now"

    def test_hours_ago(self) -> None:
        from backend.protocols.mcp.memory_server import _format_memory_age

        ts = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
        assert "h ago" in _format_memory_age(ts)

    def test_yesterday(self) -> None:
        from backend.protocols.mcp.memory_server import _format_memory_age

        ts = (datetime.now(timezone.utc) - timedelta(days=1, hours=2)).isoformat()
        assert _format_memory_age(ts) == "yesterday"

    def test_days_ago(self) -> None:
        from backend.protocols.mcp.memory_server import _format_memory_age

        ts = (datetime.now(timezone.utc) - timedelta(days=4)).isoformat()
        result = _format_memory_age(ts)
        assert "d ago" in result

    def test_weeks_ago(self) -> None:
        from backend.protocols.mcp.memory_server import _format_memory_age

        ts = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
        result = _format_memory_age(ts)
        assert "w ago" in result

    def test_months_ago(self) -> None:
        from backend.protocols.mcp.memory_server import _format_memory_age

        ts = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        result = _format_memory_age(ts)
        assert "mo ago" in result

    def test_years_ago(self) -> None:
        from backend.protocols.mcp.memory_server import _format_memory_age

        ts = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
        result = _format_memory_age(ts)
        # Should return date string like "2024-01-01"
        assert "-" in result

    def test_empty_string(self) -> None:
        from backend.protocols.mcp.memory_server import _format_memory_age

        assert _format_memory_age("") == ""

    def test_unparseable(self) -> None:
        from backend.protocols.mcp.memory_server import _format_memory_age

        assert _format_memory_age("nope") == ""
