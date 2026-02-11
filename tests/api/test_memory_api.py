"""Tests for backend.api.memory -- Memory API endpoints."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timedelta

from backend.api.deps import AppState


# ---------------------------------------------------------------------------
# POST /memory/consolidate
# ---------------------------------------------------------------------------


class TestConsolidateMemory:

    def test_success(self, no_auth_client, mock_state):
        mock_state.long_term_memory.consolidate_memories.return_value = {
            "merged": 2, "decayed": 1,
        }

        with patch("backend.api.memory._evolve_persona_from_memories", new_callable=AsyncMock) as mock_evolve:
            mock_evolve.return_value = (1, ["insight1"])
            resp = no_auth_client.post("/memory/consolidate")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"
        assert body["report"]["merged"] == 2
        assert body["report"]["insights_added"] == 1

    def test_memory_not_initialized(self, no_auth_client, mock_state):
        mock_state.long_term_memory = None
        resp = no_auth_client.post("/memory/consolidate")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "error"
        assert "not initialized" in body["message"].lower()


# ---------------------------------------------------------------------------
# GET /memory/stats
# ---------------------------------------------------------------------------


class TestGetMemoryStats:

    def test_with_memory_manager(self, no_auth_client, mock_state):
        mock_state.memory_manager.get_stats.return_value = {
            "working": {"turns": 5},
            "permanent": {"total": 42},
        }
        resp = no_auth_client.get("/memory/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert "working" in body
        assert "permanent" in body

    def test_fallback_to_long_term(self, no_auth_client, mock_state):
        mock_state.memory_manager = None
        mock_state.long_term_memory.get_stats.return_value = {"total_memories": 10}
        resp = no_auth_client.get("/memory/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert "permanent" in body

    def test_memory_not_initialized(self, no_auth_client, mock_state):
        mock_state.memory_manager = None
        mock_state.long_term_memory = None
        resp = no_auth_client.get("/memory/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert "error" in body


# ---------------------------------------------------------------------------
# POST /session/end
# ---------------------------------------------------------------------------


class TestEndSession:

    def test_success(self, no_auth_client, mock_state):
        mock_state.memory_manager.end_session = AsyncMock(
            return_value={"status": "ok", "summary": "done"}
        )
        resp = no_auth_client.post("/session/end")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"

    def test_no_memory_manager(self, no_auth_client, mock_state):
        mock_state.memory_manager = None
        resp = no_auth_client.post("/session/end")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "error"

    def test_end_session_exception(self, no_auth_client, mock_state):
        mock_state.memory_manager.end_session = AsyncMock(
            side_effect=RuntimeError("db error")
        )
        resp = no_auth_client.post("/session/end")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "error"
        assert "db error" in body["message"]


# ---------------------------------------------------------------------------
# GET /memory/sessions
# ---------------------------------------------------------------------------


class TestGetSessions:

    def test_returns_sessions(self, no_auth_client, mock_state):
        mock_state.memory_manager.session_archive.get_recent_summaries.return_value = [
            {"session_id": "s1", "summary": "Chat about dogs"},
        ]
        resp = no_auth_client.get("/memory/sessions")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["sessions"]) == 1

    def test_no_archive(self, no_auth_client, mock_state):
        mock_state.memory_manager.session_archive = None
        resp = no_auth_client.get("/memory/sessions")
        assert resp.status_code == 200
        assert resp.json()["sessions"] == []

    def test_no_memory_manager(self, no_auth_client, mock_state):
        mock_state.memory_manager = None
        resp = no_auth_client.get("/memory/sessions")
        assert resp.status_code == 200
        assert resp.json()["sessions"] == []

    def test_exception_returns_empty(self, no_auth_client, mock_state):
        mock_state.memory_manager.session_archive.get_recent_summaries.side_effect = (
            RuntimeError("oops")
        )
        resp = no_auth_client.get("/memory/sessions")
        assert resp.status_code == 200
        body = resp.json()
        assert body["sessions"] == []
        assert "error" in body


# ---------------------------------------------------------------------------
# GET /memory/search
# ---------------------------------------------------------------------------


class TestSearchMemory:

    def test_search_chroma_results(self, no_auth_client, mock_state):
        mock_state.long_term_memory.query.return_value = [
            {"content": "User likes cats", "metadata": {"uuid": "u1", "memory_type": "fact", "timestamp": "2024-01-01"}, "similarity": 0.95},
        ]
        resp = no_auth_client.get("/memory/search", params={"query": "cats"})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["results"]) == 1
        assert body["results"][0]["score"] == 0.95

    def test_search_session_archive(self, no_auth_client, mock_state):
        mock_state.long_term_memory.query.return_value = []
        mock_state.memory_manager.session_archive.get_sessions_by_date.return_value = [
            {"session_id": "s1", "summary": "We discussed cats today", "ended_at": "2024-01-01"},
        ]
        resp = no_auth_client.get("/memory/search", params={"query": "cats"})
        assert resp.status_code == 200
        body = resp.json()
        assert any(r["type"] == "session" for r in body["results"])

    def test_search_no_memory(self, no_auth_client, mock_state):
        mock_state.long_term_memory = None
        mock_state.memory_manager.session_archive = None
        resp = no_auth_client.get("/memory/search", params={"query": "xyz"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["results"] == []

    def test_search_chroma_exception_handled(self, no_auth_client, mock_state):
        mock_state.long_term_memory.search.side_effect = RuntimeError("chroma down")
        mock_state.memory_manager.session_archive = None
        resp = no_auth_client.get("/memory/search", params={"query": "test"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["results"] == []

    def test_search_respects_limit(self, no_auth_client, mock_state):
        mock_state.long_term_memory.search.return_value = [
            (f"doc{i}", {"uuid": f"u{i}", "memory_type": "fact", "timestamp": ""}, 0.5)
            for i in range(30)
        ]
        resp = no_auth_client.get("/memory/search", params={"query": "test", "limit": 5})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["results"]) <= 5


# ---------------------------------------------------------------------------
# GET /memory/session/{session_id}
# ---------------------------------------------------------------------------


class TestGetSessionDetail:

    def test_with_detail(self, no_auth_client, mock_state):
        mock_state.memory_manager.session_archive.get_session_detail.return_value = {
            "session": {
                "summary": "We talked about AI",
                "key_topics": ["AI"],
                "emotional_tone": "curious",
            },
            "messages": [
                {"role": "user", "content": "Hello"},
            ],
        }
        resp = no_auth_client.get("/memory/session/sess-123")
        assert resp.status_code == 200
        body = resp.json()
        assert body["session_id"] == "sess-123"
        assert body["summary"] == "We talked about AI"

    def test_fallback_to_messages_only(self, no_auth_client, mock_state):
        mock_state.memory_manager.session_archive.get_session_detail.return_value = None
        mock_state.memory_manager.session_archive.get_session_messages.return_value = [
            {"role": "user", "content": "Hello"},
        ]
        resp = no_auth_client.get("/memory/session/sess-456")
        assert resp.status_code == 200
        body = resp.json()
        assert body["session_id"] == "sess-456"
        assert len(body["messages"]) == 1

    def test_no_archive(self, no_auth_client, mock_state):
        mock_state.memory_manager = None
        resp = no_auth_client.get("/memory/session/sess-789")
        assert resp.status_code == 200
        body = resp.json()
        assert "error" in body

    def test_exception(self, no_auth_client, mock_state):
        mock_state.memory_manager.session_archive.get_session_detail.side_effect = (
            RuntimeError("db error")
        )
        resp = no_auth_client.get("/memory/session/sess-err")
        assert resp.status_code == 200
        body = resp.json()
        assert "error" in body


# ---------------------------------------------------------------------------
# GET /memory/interaction-logs
# ---------------------------------------------------------------------------


class TestInteractionLogs:

    def test_returns_logs(self, no_auth_client, mock_state):
        mock_state.memory_manager.session_archive.get_recent_interaction_logs.return_value = [
            {"model": "gemini", "latency_ms": 120},
        ]
        resp = no_auth_client.get("/memory/interaction-logs")
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert len(body["logs"]) == 1

    def test_no_archive(self, no_auth_client, mock_state):
        mock_state.memory_manager = None
        resp = no_auth_client.get("/memory/interaction-logs")
        assert resp.status_code == 200
        body = resp.json()
        assert body["logs"] == []

    def test_exception(self, no_auth_client, mock_state):
        mock_state.memory_manager.session_archive.get_recent_interaction_logs.side_effect = (
            RuntimeError("fail")
        )
        resp = no_auth_client.get("/memory/interaction-logs")
        assert resp.status_code == 200
        body = resp.json()
        assert body["logs"] == []
        assert "error" in body


# ---------------------------------------------------------------------------
# GET /memory/interaction-stats
# ---------------------------------------------------------------------------


class TestInteractionStats:

    def test_returns_stats(self, no_auth_client, mock_state):
        mock_state.memory_manager.session_archive.get_interaction_stats.return_value = {
            "total_calls": 100,
            "avg_latency": 150,
        }
        resp = no_auth_client.get("/memory/interaction-stats")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_calls"] == 100

    def test_no_archive(self, no_auth_client, mock_state):
        mock_state.memory_manager = None
        resp = no_auth_client.get("/memory/interaction-stats")
        assert resp.status_code == 200
        body = resp.json()
        assert "error" in body

    def test_exception(self, no_auth_client, mock_state):
        mock_state.memory_manager.session_archive.get_interaction_stats.side_effect = (
            RuntimeError("fail")
        )
        resp = no_auth_client.get("/memory/interaction-stats")
        assert resp.status_code == 200
        body = resp.json()
        assert "error" in body


# ---------------------------------------------------------------------------
# _evolve_persona_from_memories (internal async function)
# ---------------------------------------------------------------------------


class TestEvolvePersonaFromMemories:
    """Direct tests for the _evolve_persona_from_memories helper.

    This function is async and calls get_state() + LLM internally,
    so we patch both.
    """

    @pytest.fixture()
    def _mock_evolve_state(self, mock_state):
        """Return mock_state with memory data set up for evolve tests."""
        mock_state.long_term_memory.get_all_memories.return_value = {
            "documents": [
                "User asked about Python decorators",
                "User prefers dark mode in all apps",
            ],
            "metadatas": [
                {"user_query": "What are decorators?"},
                {"user_query": "How to enable dark mode?"},
            ],
        }
        return mock_state

    @patch("backend.api.memory.get_llm_client")
    @patch("backend.api.memory.get_state")
    async def test_returns_insights_on_success(self, mock_gs, mock_llm_factory, _mock_evolve_state):
        from backend.api.memory import _evolve_persona_from_memories

        mock_gs.return_value = _mock_evolve_state
        _mock_evolve_state.identity_manager.evolve = AsyncMock(return_value=2)

        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(return_value="1. Likes Python patterns\n2. Prefers dark mode UIs")
        mock_llm_factory.return_value = mock_llm

        added, insights = await _evolve_persona_from_memories()
        assert added == 2
        assert len(insights) == 2

    @patch("backend.api.memory.get_state")
    async def test_no_long_term_memory(self, mock_gs, mock_state):
        from backend.api.memory import _evolve_persona_from_memories

        mock_state.long_term_memory = None
        mock_gs.return_value = mock_state

        added, insights = await _evolve_persona_from_memories()
        assert added == 0
        assert insights == []

    @patch("backend.api.memory.get_state")
    async def test_no_documents(self, mock_gs, mock_state):
        from backend.api.memory import _evolve_persona_from_memories

        mock_gs.return_value = mock_state
        mock_state.long_term_memory.get_all_memories.return_value = {"documents": []}

        added, insights = await _evolve_persona_from_memories()
        assert added == 0
        assert insights == []

    @patch("backend.api.memory.get_state")
    async def test_none_all_data(self, mock_gs, mock_state):
        from backend.api.memory import _evolve_persona_from_memories

        mock_gs.return_value = mock_state
        mock_state.long_term_memory.get_all_memories.return_value = None

        added, insights = await _evolve_persona_from_memories()
        assert added == 0
        assert insights == []

    @patch("backend.api.memory.get_llm_client")
    @patch("backend.api.memory.get_state")
    async def test_llm_returns_empty(self, mock_gs, mock_llm_factory, _mock_evolve_state):
        from backend.api.memory import _evolve_persona_from_memories

        mock_gs.return_value = _mock_evolve_state

        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(return_value="")
        mock_llm_factory.return_value = mock_llm

        added, insights = await _evolve_persona_from_memories()
        assert added == 0
        assert insights == []

    @patch("backend.api.memory.get_llm_client")
    @patch("backend.api.memory.get_state")
    async def test_no_identity_manager(self, mock_gs, mock_llm_factory, _mock_evolve_state):
        from backend.api.memory import _evolve_persona_from_memories

        _mock_evolve_state.identity_manager = None
        mock_gs.return_value = _mock_evolve_state

        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(return_value="1. Likes Python patterns")
        mock_llm_factory.return_value = mock_llm

        added, insights = await _evolve_persona_from_memories()
        assert added == 0
        assert insights == []

    @patch("backend.api.memory.get_llm_client")
    @patch("backend.api.memory.get_state")
    async def test_exception_handled(self, mock_gs, mock_llm_factory, _mock_evolve_state):
        from backend.api.memory import _evolve_persona_from_memories

        mock_gs.return_value = _mock_evolve_state
        _mock_evolve_state.long_term_memory.get_all_memories.side_effect = RuntimeError("boom")

        added, insights = await _evolve_persona_from_memories()
        assert added == 0
        assert insights == []

    @patch("backend.api.memory.get_llm_client")
    @patch("backend.api.memory.get_state")
    async def test_insight_filtering(self, mock_gs, mock_llm_factory, _mock_evolve_state):
        """Short insights (<=10 chars) should be filtered out."""
        from backend.api.memory import _evolve_persona_from_memories

        mock_gs.return_value = _mock_evolve_state
        _mock_evolve_state.identity_manager.evolve = AsyncMock(return_value=1)

        mock_llm = MagicMock()
        # Line "2. Short" has < 10 chars after stripping prefix, should be filtered
        mock_llm.generate = AsyncMock(
            return_value="1. This is a long enough insight\n2. Short\n- Another valid long insight here"
        )
        mock_llm_factory.return_value = mock_llm

        added, insights = await _evolve_persona_from_memories()
        # Only the two long insights should be kept
        assert len(insights) == 2
        assert all(len(i) > 10 for i in insights)

    @patch("backend.api.memory.get_llm_client")
    @patch("backend.api.memory.get_state")
    async def test_documents_with_content_only(self, mock_gs, mock_llm_factory, mock_state):
        """Documents without user_query should still produce memory lines."""
        from backend.api.memory import _evolve_persona_from_memories

        mock_gs.return_value = mock_state
        mock_state.long_term_memory.get_all_memories.return_value = {
            "documents": ["User is a backend developer"],
            "metadatas": [{}],  # no user_query
        }
        mock_state.identity_manager.evolve = AsyncMock(return_value=1)

        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(return_value="1. Focuses on backend development work")
        mock_llm_factory.return_value = mock_llm

        added, insights = await _evolve_persona_from_memories()
        assert added == 1
