"""Tests for backend.memory.memgpt — MemGPT-style memory management.

Tests context_budget_select, smart_eviction, episodic_to_semantic,
and the _extract_semantic_knowledge helper.
"""

import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.utils.timezone import VANCOUVER_TZ
from backend.memory.memgpt import (
    MemGPTManager,
    MemGPTConfig,
    ScoredMemory,
    SemanticKnowledge,
    DEFAULT_CONFIG,
    MAX_CONSOLIDATION_CONCURRENCY,
)


# ── Helpers ──────────────────────────────────────────────────────────────

def _make_memory(
    id: str = "mem-1",
    content: str = "Test memory",
    score: float = 0.8,
    topics: list = None,
    metadata: dict = None,
):
    """Build a candidate memory dict for context_budget_select."""
    meta = metadata or {}
    if topics:
        meta["key_topics"] = topics
    return {
        "id": id,
        "content": content,
        "effective_score": score,
        "metadata": meta,
    }


def _make_config(**overrides) -> MemGPTConfig:
    return MemGPTConfig(**overrides)


@pytest.fixture
def mock_ltm():
    """Mock LongTermMemory with configurable query/get_all results."""
    ltm = MagicMock()
    ltm.query.return_value = []
    ltm.get_all_memories.return_value = {"ids": [], "documents": [], "metadatas": []}
    ltm.delete_memories.return_value = None
    ltm.find_similar_memories.return_value = []
    ltm.add.return_value = None
    return ltm


@pytest.fixture
def mock_client():
    """Mock Gemini client for semantic extraction."""
    client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "knowledge": "User likes Python",
        "confidence": 0.8,
        "key_insight": "Programming preference",
    })
    # Support async client API (client.aio.models.generate_content)
    client.aio = MagicMock()
    client.aio.models = MagicMock()
    client.aio.models.generate_content = AsyncMock(return_value=mock_response)
    # Keep sync API for backward compatibility
    client.models.generate_content.return_value = mock_response
    return client


@pytest.fixture
def manager(mock_ltm, mock_client):
    """MemGPTManager with mocked dependencies."""
    return MemGPTManager(
        long_term_memory=mock_ltm,
        client=mock_client,
        model_name="test-model",
        config=_make_config(long_term_budget=500, max_similar_memories=2),
    )


# ── ScoredMemory / SemanticKnowledge dataclasses ─────────────────────────

class TestDataclasses:

    def test_scored_memory_defaults(self):
        sm = ScoredMemory(id="1", content="test", score=0.5)
        assert sm.metadata == {}
        assert sm.token_estimate == 0

    def test_semantic_knowledge_defaults(self):
        sk = SemanticKnowledge(
            knowledge="fact", confidence=0.9, source_count=3
        )
        assert sk.topics == []


# ── DEFAULT_CONFIG ───────────────────────────────────────────────────────

class TestDefaultConfig:

    def test_default_config_values(self):
        assert DEFAULT_CONFIG.eviction_score_threshold == 0.1
        assert DEFAULT_CONFIG.min_memories_keep == 3
        assert DEFAULT_CONFIG.triage_enabled is True
        assert DEFAULT_CONFIG.triage_batch_size == 5
        assert DEFAULT_CONFIG.max_similar_memories == 2

    def test_max_consolidation_concurrency(self):
        assert MAX_CONSOLIDATION_CONCURRENCY == 3


# ── MemGPTManager.__init__ ──────────────────────────────────────────────

class TestManagerInit:

    def test_init_with_explicit_client(self, mock_ltm, mock_client):
        mgr = MemGPTManager(
            long_term_memory=mock_ltm,
            client=mock_client,
            model_name="my-model",
        )
        assert mgr.client is mock_client
        assert mgr.model_name == "my-model"

    def test_init_backward_compat_model_kwarg(self, mock_ltm):
        """model= kwarg extracts .client attribute."""
        mock_model = MagicMock()
        mock_model.client = MagicMock()
        mgr = MemGPTManager(
            long_term_memory=mock_ltm,
            model=mock_model,
            model_name="test",
        )
        assert mgr.client is mock_model.client

    def test_init_defaults_model_name(self, mock_ltm, mock_client):
        """If model_name is not provided, it fetches from config."""
        with patch("backend.core.utils.gemini_client.get_model_name", return_value="default-model"):
            mgr = MemGPTManager(
                long_term_memory=mock_ltm,
                client=mock_client,
            )
        assert mgr.model_name == "default-model"

    def test_init_default_config(self, mock_ltm, mock_client):
        mgr = MemGPTManager(
            long_term_memory=mock_ltm,
            client=mock_client,
            model_name="test",
        )
        assert mgr.config is DEFAULT_CONFIG


# ── context_budget_select ────────────────────────────────────────────────

class TestContextBudgetSelect:

    def test_empty_candidates_returns_empty(self, manager):
        selected, tokens = manager.context_budget_select("hello", candidate_memories=[])
        assert selected == []
        assert tokens == 0

    def test_none_candidates_queries_ltm(self, manager, mock_ltm):
        mock_ltm.query.return_value = [
            _make_memory("m1", "short text", 0.9),
        ]
        selected, tokens = manager.context_budget_select("hello")
        mock_ltm.query.assert_called_once()
        assert len(selected) == 1

    def test_selects_within_budget(self, manager):
        # Each memory content is ~40 chars => ~10 tokens
        candidates = [
            _make_memory("m1", "a" * 40, 0.9),
            _make_memory("m2", "b" * 40, 0.8),
            _make_memory("m3", "c" * 40, 0.7),
        ]
        selected, tokens = manager.context_budget_select(
            "test", token_budget=25, candidate_memories=candidates
        )
        # Each is ~10 tokens, budget=25 => 2 fit
        assert len(selected) == 2
        assert tokens <= 25

    def test_sorts_by_score_descending(self, manager):
        candidates = [
            _make_memory("low", "content low", 0.3),
            _make_memory("high", "content high", 0.9),
            _make_memory("mid", "content mid", 0.6),
        ]
        selected, _ = manager.context_budget_select(
            "test", token_budget=10000, candidate_memories=candidates
        )
        assert selected[0].id == "high"
        assert selected[1].id == "mid"
        assert selected[2].id == "low"

    def test_topic_diversity_cap(self, manager):
        """Memories with same topic are capped at max_similar_memories."""
        candidates = [
            _make_memory("m1", "a" * 20, 0.9, topics=["python"]),
            _make_memory("m2", "b" * 20, 0.8, topics=["python"]),
            _make_memory("m3", "c" * 20, 0.7, topics=["python"]),
            _make_memory("m4", "d" * 20, 0.6, topics=["rust"]),
        ]
        selected, _ = manager.context_budget_select(
            "test", token_budget=10000, candidate_memories=candidates
        )
        python_ids = [s.id for s in selected if "python" in s.metadata.get("key_topics", [])]
        assert len(python_ids) <= 2  # max_similar_memories=2

    def test_skips_none_candidates(self, manager):
        candidates = [None, _make_memory("m1", "valid", 0.5), None]
        selected, _ = manager.context_budget_select(
            "test", token_budget=10000, candidate_memories=candidates
        )
        assert len(selected) == 1

    def test_uses_relevance_fallback_score(self, manager):
        """If effective_score is missing, falls back to relevance."""
        mem = {"id": "m1", "content": "test", "relevance": 0.6, "metadata": {}}
        selected, _ = manager.context_budget_select(
            "test", token_budget=10000, candidate_memories=[mem]
        )
        assert selected[0].score == 0.6

    def test_default_score_when_both_missing(self, manager):
        """If both effective_score and relevance are missing, defaults to 0.5."""
        mem = {"id": "m1", "content": "test", "metadata": {}}
        selected, _ = manager.context_budget_select(
            "test", token_budget=10000, candidate_memories=[mem]
        )
        assert selected[0].score == 0.5

    def test_token_estimate_from_content_length(self, manager):
        mem = _make_memory("m1", "x" * 100, 0.9)  # 100 chars => 25 tokens
        selected, tokens = manager.context_budget_select(
            "test", token_budget=10000, candidate_memories=[mem]
        )
        assert selected[0].token_estimate == 25
        assert tokens == 25

    def test_budget_skip_large_memory(self, manager):
        """A single large memory that exceeds budget is skipped."""
        candidates = [
            _make_memory("big", "x" * 4000, 0.9),  # 1000 tokens
            _make_memory("small", "y" * 40, 0.5),   # 10 tokens
        ]
        selected, tokens = manager.context_budget_select(
            "test", token_budget=50, candidate_memories=candidates
        )
        assert len(selected) == 1
        assert selected[0].id == "small"

    def test_temporal_filter_passed_to_query(self, manager, mock_ltm):
        tf = {"type": "exact", "date": "2025-01-01"}
        manager.context_budget_select("test", temporal_filter=tf)
        mock_ltm.query.assert_called_once_with(
            "test", n_results=20, temporal_filter=tf
        )


# ── smart_eviction ──────────────────────────────────────────────────────

class TestSmartEviction:

    def test_dry_run_no_deletion(self, manager, mock_ltm):
        now = datetime.now(VANCOUVER_TZ)
        old_time = (now - timedelta(days=30)).isoformat()
        mock_ltm.get_all_memories.return_value = {
            "ids": ["m1"],
            "documents": ["old memory"],
            "metadatas": [{
                "importance": 0.05,
                "created_at": old_time,
                "repetitions": 1,
                "access_count": 0,
            }],
        }

        with patch("backend.memory.permanent.get_connection_count", return_value=0), \
             patch("backend.memory.permanent.apply_adaptive_decay", return_value=0.01), \
             patch("backend.memory.permanent.get_memory_age_hours", return_value=24 * 30):
            result = manager.smart_eviction(dry_run=True)

        assert result["candidates"] >= 1
        assert result["evicted"] == 0
        assert result["dry_run"] is True
        mock_ltm.delete_memories.assert_not_called()

    def test_actual_eviction(self, manager, mock_ltm):
        now = datetime.now(VANCOUVER_TZ)
        old_time = (now - timedelta(days=30)).isoformat()
        mock_ltm.get_all_memories.return_value = {
            "ids": ["m1", "m2", "m3", "m4", "m5"],
            "documents": ["d1", "d2", "d3", "d4", "d5"],
            "metadatas": [
                {"importance": 0.01, "created_at": old_time, "repetitions": 1, "access_count": 0},
                {"importance": 0.01, "created_at": old_time, "repetitions": 1, "access_count": 0},
                {"importance": 0.01, "created_at": old_time, "repetitions": 1, "access_count": 0},
                {"importance": 0.9, "created_at": old_time, "repetitions": 5, "access_count": 10},
                {"importance": 0.9, "created_at": old_time, "repetitions": 5, "access_count": 10},
            ],
        }

        def mock_decay(imp, created, access_count=0, connection_count=0):
            return imp * 0.5

        with patch("backend.memory.permanent.get_connection_count", return_value=0), \
             patch("backend.memory.permanent.apply_adaptive_decay", side_effect=mock_decay), \
             patch("backend.memory.permanent.get_memory_age_hours", return_value=24 * 30):
            result = manager.smart_eviction(dry_run=False)

        assert result["evicted"] >= 1

    def test_eviction_respects_min_memories_keep(self, manager, mock_ltm):
        """Should not evict below min_memories_keep."""
        now = datetime.now(VANCOUVER_TZ)
        old_time = (now - timedelta(days=30)).isoformat()
        # Only 4 memories, min_memories_keep=3 => can evict at most 1
        mock_ltm.get_all_memories.return_value = {
            "ids": ["m1", "m2", "m3", "m4"],
            "documents": ["d1", "d2", "d3", "d4"],
            "metadatas": [
                {"importance": 0.01, "created_at": old_time, "repetitions": 1, "access_count": 0},
                {"importance": 0.01, "created_at": old_time, "repetitions": 1, "access_count": 0},
                {"importance": 0.01, "created_at": old_time, "repetitions": 1, "access_count": 0},
                {"importance": 0.01, "created_at": old_time, "repetitions": 1, "access_count": 0},
            ],
        }

        with patch("backend.memory.permanent.get_connection_count", return_value=0), \
             patch("backend.memory.permanent.apply_adaptive_decay", return_value=0.01), \
             patch("backend.memory.permanent.get_memory_age_hours", return_value=24 * 30):
            result = manager.smart_eviction(dry_run=False)

        assert result["evicted"] <= 1

    def test_eviction_empty_memories(self, manager, mock_ltm):
        mock_ltm.get_all_memories.return_value = {"ids": [], "documents": [], "metadatas": []}
        result = manager.smart_eviction(dry_run=True)
        assert result["candidates"] == []
        assert result["total"] == 0

    def test_eviction_no_ids(self, manager, mock_ltm):
        mock_ltm.get_all_memories.return_value = None
        result = manager.smart_eviction(dry_run=True)
        assert result["candidates"] == []

    def test_eviction_error_returns_error_dict(self, manager, mock_ltm):
        mock_ltm.get_all_memories.side_effect = RuntimeError("DB error")
        result = manager.smart_eviction(dry_run=True)
        assert "error" in result

    def test_eviction_delete_failure_logged(self, manager, mock_ltm):
        now = datetime.now(VANCOUVER_TZ)
        old_time = (now - timedelta(days=30)).isoformat()
        mock_ltm.get_all_memories.return_value = {
            "ids": ["m1", "m2", "m3", "m4", "m5"],
            "documents": ["d"] * 5,
            "metadatas": [
                {"importance": 0.01, "created_at": old_time, "repetitions": 1, "access_count": 0}
            ] * 5,
        }
        mock_ltm.delete_memories.side_effect = RuntimeError("delete failed")

        with patch("backend.memory.permanent.get_connection_count", return_value=0), \
             patch("backend.memory.permanent.apply_adaptive_decay", return_value=0.01), \
             patch("backend.memory.permanent.get_memory_age_hours", return_value=24 * 30):
            result = manager.smart_eviction(dry_run=False)

        assert result["evicted"] == 0


# ── episodic_to_semantic ─────────────────────────────────────────────────

class TestEpisodicToSemantic:

    async def test_no_client_returns_error(self, mock_ltm):
        mgr = MemGPTManager(
            long_term_memory=mock_ltm,
            client=None,
            model_name="test",
        )
        result = await mgr.episodic_to_semantic()
        assert "error" in result

    async def test_empty_memories(self, manager, mock_ltm):
        mock_ltm.get_all_memories.return_value = {"ids": [], "documents": [], "metadatas": []}
        result = await manager.episodic_to_semantic()
        assert result["candidates"] == 0
        assert result["transformed"] == 0

    async def test_skips_semantic_type(self, manager, mock_ltm, mock_client):
        now = datetime.now(VANCOUVER_TZ)
        old_time = (now - timedelta(days=10)).isoformat()
        mock_ltm.get_all_memories.return_value = {
            "ids": ["m1", "m2"],
            "documents": ["semantic knowledge", "another semantic"],
            "metadatas": [
                {"type": "semantic", "created_at": old_time, "repetitions": 3, "key_topics": ["python"]},
                {"type": "semantic", "created_at": old_time, "repetitions": 3, "key_topics": ["python"]},
            ],
        }
        with patch("backend.memory.permanent.get_memory_age_hours", return_value=24 * 10):
            result = await manager.episodic_to_semantic()
        assert result["total_groups"] == 0

    async def test_skips_young_memories(self, manager, mock_ltm, mock_client):
        now = datetime.now(VANCOUVER_TZ)
        recent = now.isoformat()
        mock_ltm.get_all_memories.return_value = {
            "ids": ["m1", "m2"],
            "documents": ["young1", "young2"],
            "metadatas": [
                {"type": "conversation", "created_at": recent, "repetitions": 3, "key_topics": ["python"]},
                {"type": "conversation", "created_at": recent, "repetitions": 3, "key_topics": ["python"]},
            ],
        }
        with patch("backend.memory.permanent.get_memory_age_hours", return_value=1):
            result = await manager.episodic_to_semantic()
        assert result["total_groups"] == 0

    async def test_single_memory_group_not_transformed(self, manager, mock_ltm):
        """Groups with < 2 memories are not transformed."""
        now = datetime.now(VANCOUVER_TZ)
        old_time = (now - timedelta(days=10)).isoformat()
        mock_ltm.get_all_memories.return_value = {
            "ids": ["m1"],
            "documents": ["only one"],
            "metadatas": [
                {"type": "conversation", "created_at": old_time, "repetitions": 3,
                 "key_topics": ["unique_topic"]},
            ],
        }
        with patch("backend.memory.permanent.get_memory_age_hours", return_value=24 * 10):
            result = await manager.episodic_to_semantic()
        assert result["transformations"] == 0

    async def test_successful_transformation_dry_run(self, manager, mock_ltm, mock_client):
        now = datetime.now(VANCOUVER_TZ)
        old_time = (now - timedelta(days=10)).isoformat()
        mock_ltm.get_all_memories.return_value = {
            "ids": ["m1", "m2"],
            "documents": ["Python is great", "I love Python"],
            "metadatas": [
                {"type": "conversation", "created_at": old_time, "repetitions": 2,
                 "key_topics": ["python"]},
                {"type": "conversation", "created_at": old_time, "repetitions": 2,
                 "key_topics": ["python"]},
            ],
        }
        with patch("backend.memory.permanent.get_memory_age_hours", return_value=24 * 10):
            result = await manager.episodic_to_semantic(dry_run=True)

        assert result["transformations"] >= 1
        assert result["dry_run"] is True
        mock_ltm.add.assert_not_called()

    async def test_transformation_stores_when_not_dry_run(self, manager, mock_ltm, mock_client):
        now = datetime.now(VANCOUVER_TZ)
        old_time = (now - timedelta(days=10)).isoformat()
        mock_ltm.get_all_memories.return_value = {
            "ids": ["m1", "m2"],
            "documents": ["Python is great", "I love Python"],
            "metadatas": [
                {"type": "conversation", "created_at": old_time, "repetitions": 2,
                 "key_topics": ["python"]},
                {"type": "conversation", "created_at": old_time, "repetitions": 2,
                 "key_topics": ["python"]},
            ],
        }
        mock_ltm.find_similar_memories.return_value = []

        with patch("backend.memory.permanent.get_memory_age_hours", return_value=24 * 10):
            result = await manager.episodic_to_semantic(dry_run=False)

        assert result["transformations"] >= 1
        mock_ltm.add.assert_called_once()
        call_kwargs = mock_ltm.add.call_args
        assert call_kwargs[1]["memory_type"] == "semantic"
        assert call_kwargs[1]["force"] is True

    async def test_transformation_dedup_merges_existing(self, manager, mock_ltm, mock_client):
        """When similar semantic memory already exists, merge instead of creating new."""
        now = datetime.now(VANCOUVER_TZ)
        old_time = (now - timedelta(days=10)).isoformat()
        mock_ltm.get_all_memories.return_value = {
            "ids": ["m1", "m2"],
            "documents": ["Python is great", "I love Python"],
            "metadatas": [
                {"type": "conversation", "created_at": old_time, "repetitions": 2,
                 "key_topics": ["python"]},
                {"type": "conversation", "created_at": old_time, "repetitions": 2,
                 "key_topics": ["python"]},
            ],
        }
        # Simulate existing similar memory
        mock_ltm.find_similar_memories.return_value = [
            {"id": "existing-1", "metadata": {"repetitions": 2}, "similarity": 0.95}
        ]
        mock_ltm._repository = MagicMock()

        with patch("backend.memory.permanent.get_memory_age_hours", return_value=24 * 10):
            result = await manager.episodic_to_semantic(dry_run=False)

        mock_ltm.add.assert_not_called()  # Should merge, not add
        mock_ltm._repository.update_metadata.assert_called_once()

    async def test_low_confidence_not_transformed(self, manager, mock_ltm, mock_client):
        """Semantic knowledge with confidence <= 0.5 is not transformed."""
        now = datetime.now(VANCOUVER_TZ)
        old_time = (now - timedelta(days=10)).isoformat()
        mock_ltm.get_all_memories.return_value = {
            "ids": ["m1", "m2"],
            "documents": ["random chat 1", "random chat 2"],
            "metadatas": [
                {"type": "conversation", "created_at": old_time, "repetitions": 2,
                 "key_topics": ["chat"]},
                {"type": "conversation", "created_at": old_time, "repetitions": 2,
                 "key_topics": ["chat"]},
            ],
        }
        # Return low confidence
        low_conf_response = MagicMock()
        low_conf_response.text = json.dumps({
            "knowledge": "unclear", "confidence": 0.3, "key_insight": "none"
        })
        mock_client.aio.models.generate_content = AsyncMock(return_value=low_conf_response)

        with patch("backend.memory.permanent.get_memory_age_hours", return_value=24 * 10):
            result = await manager.episodic_to_semantic(dry_run=True)

        assert result["transformations"] == 0

    async def test_episodic_to_semantic_error_returns_error(self, manager, mock_ltm):
        mock_ltm.get_all_memories.side_effect = RuntimeError("boom")
        result = await manager.episodic_to_semantic()
        assert "error" in result


# ── episodic_to_semantic_limited ─────────────────────────────────────────

class TestEpisodicToSemanticLimited:

    async def test_limited_delegates(self, manager, mock_ltm):
        mock_ltm.get_all_memories.return_value = {"ids": [], "documents": [], "metadatas": []}
        result = await manager.episodic_to_semantic_limited()
        assert result["candidates"] == 0


# ── _extract_semantic_knowledge ──────────────────────────────────────────

class TestExtractSemanticKnowledge:

    async def test_successful_extraction(self, manager, mock_client):
        memories = [
            {"content": "Python is my favorite language"},
            {"content": "I use Python for data science"},
        ]
        result = await manager._extract_semantic_knowledge("python", memories)
        assert result is not None
        assert isinstance(result, SemanticKnowledge)
        assert result.knowledge == "User likes Python"
        assert result.confidence == 0.8
        assert result.source_count == 2
        assert result.topics == ["python"]

    async def test_extraction_with_code_fences(self, manager, mock_client):
        """Response wrapped in ```json should still parse."""
        mock_response = MagicMock()
        mock_response.text = '```json\n{"knowledge": "Test", "confidence": 0.9}\n```'
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        result = await manager._extract_semantic_knowledge("test", [{"content": "a"}])
        assert result is not None
        assert result.knowledge == "Test"

    async def test_extraction_failure_returns_none(self, manager, mock_client):
        mock_client.aio.models.generate_content = AsyncMock(side_effect=RuntimeError("API error"))
        result = await manager._extract_semantic_knowledge("test", [{"content": "a"}])
        assert result is None

    async def test_extraction_invalid_json_returns_none(self, manager, mock_client):
        mock_response = MagicMock()
        mock_response.text = "not json at all"
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        result = await manager._extract_semantic_knowledge("test", [{"content": "a"}])
        assert result is None

    async def test_extraction_empty_response_returns_none(self, manager, mock_client):
        mock_response = MagicMock()
        mock_response.text = None
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        result = await manager._extract_semantic_knowledge("test", [{"content": "a"}])
        # "{}" is valid JSON => returns SemanticKnowledge with defaults
        assert result is not None
        assert result.knowledge == ""

    async def test_extraction_truncates_long_content(self, manager, mock_client):
        """Content longer than 200 chars is truncated in prompt."""
        memories = [{"content": "x" * 300}]
        await manager._extract_semantic_knowledge("test", memories)
        call_args = mock_client.aio.models.generate_content.call_args
        prompt = call_args[1]["contents"]
        # The memory text in the prompt should be truncated
        assert len(prompt) < 300 + 500  # prompt template + truncated content

    async def test_extraction_caps_at_five_memories(self, manager, mock_client):
        """Only first 5 memories are included in the prompt."""
        memories = [{"content": f"memory {i}"} for i in range(10)]
        await manager._extract_semantic_knowledge("test", memories)
        call_args = mock_client.aio.models.generate_content.call_args
        prompt = call_args[1]["contents"]
        assert "memory 4" in prompt
        assert "memory 5" not in prompt
