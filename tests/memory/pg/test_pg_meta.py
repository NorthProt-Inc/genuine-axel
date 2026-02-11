"""Tests for backend.memory.pg.meta_repository — PgMetaMemoryRepository.

Covers:
- persist_pattern() success and error handling
- get_hot_memories() with materialized view and fallback
- prune_old_patterns() success and failure
"""

from unittest.mock import MagicMock

import pytest

from backend.memory.pg.meta_repository import PgMetaMemoryRepository


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def repo(conn_mgr_with_mocks):
    return PgMetaMemoryRepository(conn_mgr_with_mocks)


# ============================================================================
# persist_pattern()
# ============================================================================

class TestPersistPattern:

    def test_success(self, repo):
        pattern = {
            "query_text": "test query",
            "matched_memory_ids": ["m1", "m2"],
            "relevance_scores": [0.9, 0.8],
            "channel_id": "web",
            "created_at": "2025-01-01T00:00:00",
        }
        repo.persist_pattern(pattern)
        repo._conn.execute.assert_called_once()

    def test_params_serialized_correctly(self, repo):
        pattern = {
            "query_text": "test query",
            "matched_memory_ids": ["m1"],
            "relevance_scores": [0.95],
            "channel_id": "api",
            "created_at": "2025-01-01T00:00:00",
        }
        repo.persist_pattern(pattern)
        call_params = repo._conn.execute.call_args[0][1]
        assert call_params[0] == "test query"
        assert '"m1"' in call_params[1]
        assert "0.95" in call_params[2]
        assert call_params[3] == "api"

    def test_error_swallowed(self, repo):
        """persist_pattern should not raise on DB errors."""
        repo._conn.execute.side_effect = Exception("db error")
        pattern = {
            "query_text": "q",
            "matched_memory_ids": [],
            "relevance_scores": [],
            "channel_id": "c",
            "created_at": "ts",
        }
        # Should not raise
        repo.persist_pattern(pattern)


# ============================================================================
# get_hot_memories()
# ============================================================================

class TestGetHotMemories:

    def test_uses_materialized_view(self, repo):
        repo._conn.execute_dict.return_value = [
            {"memory_id": "m1", "access_count": 10, "channel_diversity": 3}
        ]
        result = repo.get_hot_memories(limit=5)
        assert len(result) == 1
        assert result[0]["memory_id"] == "m1"

    def test_fallback_on_view_not_exists(self, repo):
        """When materialized view fails, should fall back to aggregation query."""
        fallback_result = [
            {"memory_id": "m2", "access_count": 5, "channel_diversity": 2}
        ]
        repo._conn.execute_dict.side_effect = [
            Exception("relation hot_memories does not exist"),
            fallback_result,
        ]
        result = repo.get_hot_memories(limit=5)
        assert len(result) == 1
        assert result[0]["memory_id"] == "m2"

    def test_both_queries_fail_returns_empty(self, repo):
        repo._conn.execute_dict.side_effect = [
            Exception("view missing"),
            Exception("aggregation failed"),
        ]
        result = repo.get_hot_memories()
        assert result == []

    def test_default_limit(self, repo):
        repo._conn.execute_dict.return_value = []
        repo.get_hot_memories()
        call_params = repo._conn.execute_dict.call_args[0][1]
        assert call_params == (10,)

    def test_custom_limit(self, repo):
        repo._conn.execute_dict.return_value = []
        repo.get_hot_memories(limit=3)
        call_params = repo._conn.execute_dict.call_args[0][1]
        assert call_params == (3,)


# ============================================================================
# prune_old_patterns()
# ============================================================================

class TestPruneOldPatterns:

    def test_returns_deleted_count(self, repo):
        repo._conn.execute.return_value = [(1,), (2,), (3,)]
        result = repo.prune_old_patterns(older_than_days=30)
        assert result == 3

    def test_nothing_to_prune(self, repo):
        repo._conn.execute.return_value = []
        result = repo.prune_old_patterns()
        assert result == 0

    def test_custom_days(self, repo):
        repo._conn.execute.return_value = []
        repo.prune_old_patterns(older_than_days=7)
        call_params = repo._conn.execute.call_args[0][1]
        assert call_params == (7,)

    def test_default_days(self, repo):
        repo._conn.execute.return_value = []
        repo.prune_old_patterns()
        call_params = repo._conn.execute.call_args[0][1]
        assert call_params == (30,)

    def test_error_returns_zero(self, repo):
        repo._conn.execute.side_effect = Exception("db error")
        result = repo.prune_old_patterns()
        assert result == 0
