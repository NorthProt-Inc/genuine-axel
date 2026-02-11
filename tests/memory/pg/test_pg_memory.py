"""Tests for backend.memory.pg.memory_repository — PgMemoryRepository.

Covers:
- add() generates UUID and inserts
- get_all() with various include options
- get_by_id() found and not found
- query_by_embedding() cosine similarity search
- update_metadata() with various fields
- delete() with and without doc_ids
- count()
- collection property stub and get() shim
- _row_to_metadata()
- _build_where() with $and, $or, operators, and empty input
- _build_single_condition() with all comparison operators
"""

from unittest.mock import MagicMock, patch

import pytest

from backend.memory.pg.memory_repository import PgMemoryRepository


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def repo(conn_mgr_with_mocks):
    return PgMemoryRepository(conn_mgr_with_mocks)


@pytest.fixture
def sample_row():
    return {
        "uuid": "abc-123",
        "content": "test content",
        "memory_type": "fact",
        "importance": 0.8,
        "source_session": "sess-1",
        "source_channel": "web",
        "created_at": "2025-01-01T00:00:00",
        "last_accessed": "2025-01-02T00:00:00",
        "access_count": 3,
        "decayed_importance": 0.7,
        "embedding": "[0.1, 0.2]",
    }


# ============================================================================
# add()
# ============================================================================


class TestAdd:

    @patch("backend.memory.pg.memory_repository.now_vancouver")
    def test_add_returns_doc_id(self, mock_now, repo):
        mock_now.return_value.isoformat.return_value = "2025-01-01T00:00:00"
        result = repo.add(
            content="test",
            embedding=[0.1, 0.2],
            metadata={"type": "fact", "importance": 0.9},
        )
        assert isinstance(result, str)
        assert len(result) > 0
        repo._conn.execute.assert_called_once()

    @patch("backend.memory.pg.memory_repository.now_vancouver")
    def test_add_with_custom_doc_id(self, mock_now, repo):
        mock_now.return_value.isoformat.return_value = "2025-01-01T00:00:00"
        result = repo.add(
            content="test",
            embedding=[0.1],
            metadata={},
            doc_id="custom-id",
        )
        assert result == "custom-id"

    @patch("backend.memory.pg.memory_repository.now_vancouver")
    def test_add_passes_metadata_fields(self, mock_now, repo):
        mock_now.return_value.isoformat.return_value = "2025-01-01T00:00:00"
        repo.add(
            content="hello",
            embedding=[1.0],
            metadata={
                "type": "insight",
                "importance": 0.5,
                "source_session": "s1",
                "source_channel": "api",
            },
        )
        args = repo._conn.execute.call_args
        params = args[0][1]
        assert params[2] == "insight"  # type
        assert params[3] == 0.5  # importance


# ============================================================================
# get_all()
# ============================================================================


class TestGetAll:

    def test_get_all_returns_ids_documents_metadatas(self, repo, sample_row):
        repo._conn.execute_dict.return_value = [sample_row]
        result = repo.get_all()
        assert "ids" in result
        assert "documents" in result
        assert "metadatas" in result
        assert result["ids"] == ["abc-123"]
        assert result["documents"] == ["test content"]

    def test_get_all_with_embeddings_include(self, repo, sample_row):
        repo._conn.execute_dict.return_value = [sample_row]
        result = repo.get_all(include=["documents", "metadatas", "embeddings"])
        assert "embeddings" in result
        assert result["embeddings"] == ["[0.1, 0.2]"]

    def test_get_all_empty_include_defaults_to_docs_and_meta(self, repo, sample_row):
        """Empty list is falsy, so include defaults to ['documents', 'metadatas']."""
        repo._conn.execute_dict.return_value = [sample_row]
        result = repo.get_all(include=[])
        assert "ids" in result
        # Empty list is falsy -> include defaults
        assert "documents" in result
        assert "metadatas" in result

    def test_get_all_empty_db(self, repo):
        repo._conn.execute_dict.return_value = []
        result = repo.get_all()
        assert result["ids"] == []

    def test_get_all_with_limit(self, repo):
        repo._conn.execute_dict.return_value = []
        repo.get_all(limit=5)
        call_params = repo._conn.execute_dict.call_args[0][1]
        assert call_params == (5,)


# ============================================================================
# get_by_id()
# ============================================================================


class TestGetById:

    def test_found(self, repo, sample_row):
        repo._conn.execute_dict.return_value = [sample_row]
        result = repo.get_by_id("abc-123")
        assert result is not None
        assert result["id"] == "abc-123"
        assert result["content"] == "test content"
        assert result["metadata"]["type"] == "fact"

    def test_not_found(self, repo):
        repo._conn.execute_dict.return_value = []
        result = repo.get_by_id("nonexistent")
        assert result is None


# ============================================================================
# query_by_embedding()
# ============================================================================


class TestQueryByEmbedding:

    def test_returns_results_with_similarity(self, repo, sample_row):
        sample_row["similarity"] = 0.95
        repo._conn.execute_dict.return_value = [sample_row]

        results = repo.query_by_embedding(embedding=[0.1, 0.2], n_results=5)
        assert len(results) == 1
        assert results[0]["id"] == "abc-123"
        assert results[0]["similarity"] == 0.95
        assert results[0]["distance"] == pytest.approx(0.05)

    def test_empty_results(self, repo):
        repo._conn.execute_dict.return_value = []
        results = repo.query_by_embedding(embedding=[0.1], n_results=10)
        assert results == []

    def test_with_where_filter(self, repo, sample_row):
        sample_row["similarity"] = 0.8
        repo._conn.execute_dict.return_value = [sample_row]

        results = repo.query_by_embedding(
            embedding=[0.1],
            n_results=5,
            where={"type": "fact"},
        )
        assert len(results) == 1
        sql = repo._conn.execute_dict.call_args[0][0]
        assert "WHERE" in sql


# ============================================================================
# update_metadata()
# ============================================================================


class TestUpdateMetadata:

    def test_update_single_field(self, repo):
        result = repo.update_metadata("doc-1", {"importance": 0.9})
        assert result is True
        call_sql = repo._conn.execute.call_args[0][0]
        assert "importance" in call_sql

    def test_update_multiple_fields(self, repo):
        result = repo.update_metadata(
            "doc-1",
            {
                "importance": 0.8,
                "last_accessed": "2025-06-01",
                "type": "fact",
            },
        )
        assert result is True
        call_sql = repo._conn.execute.call_args[0][0]
        assert "importance" in call_sql
        assert "last_accessed" in call_sql
        assert "memory_type" in call_sql

    def test_update_no_matching_fields(self, repo):
        result = repo.update_metadata("doc-1", {"unknown_field": "value"})
        assert result is True
        repo._conn.execute.assert_not_called()

    def test_update_decayed_importance(self, repo):
        repo.update_metadata("doc-1", {"decayed_importance": 0.3})
        call_sql = repo._conn.execute.call_args[0][0]
        assert "decayed_importance" in call_sql


# ============================================================================
# delete()
# ============================================================================


class TestDelete:

    def test_delete_returns_count(self, repo):
        repo._conn.execute.return_value = [("id1",), ("id2",)]
        result = repo.delete(["id1", "id2"])
        assert result == 2

    def test_delete_empty_list(self, repo):
        result = repo.delete([])
        assert result == 0
        repo._conn.execute.assert_not_called()

    def test_delete_none_found(self, repo):
        repo._conn.execute.return_value = []
        result = repo.delete(["nonexistent"])
        assert result == 0


# ============================================================================
# count()
# ============================================================================


class TestCount:

    def test_count_returns_number(self, repo):
        repo._conn.execute_one.return_value = (42,)
        assert repo.count() == 42

    def test_count_returns_zero_when_no_row(self, repo):
        repo._conn.execute_one.return_value = None
        assert repo.count() == 0


# ============================================================================
# collection property and get() shim
# ============================================================================


class TestCollectionCompat:

    def test_collection_returns_self(self, repo):
        assert repo.collection is repo

    def test_get_shim_delegates_to_get_all(self, repo):
        repo._conn.execute_dict.return_value = []
        result = repo.get(include=["documents"], limit=10)
        assert "ids" in result


# ============================================================================
# _row_to_metadata()
# ============================================================================


class TestRowToMetadata:

    def test_full_row(self, sample_row):
        meta = PgMemoryRepository._row_to_metadata(sample_row)
        assert meta["type"] == "fact"
        assert meta["importance"] == 0.8
        assert meta["source_session"] == "sess-1"
        assert meta["source_channel"] == "web"
        assert meta["access_count"] == 3
        assert meta["decayed_importance"] == 0.7

    def test_defaults_for_missing_fields(self):
        meta = PgMemoryRepository._row_to_metadata({})
        assert meta["type"] == "insight"
        assert meta["importance"] == 0.5
        assert meta["source_session"] == ""
        assert meta["source_channel"] == ""
        assert meta["access_count"] == 1
        assert meta["decayed_importance"] is None


# ============================================================================
# _build_where()
# ============================================================================


class TestBuildWhere:

    def test_empty_where(self):
        sql, params = PgMemoryRepository._build_where(None)
        assert sql == ""
        assert params == ()

    def test_empty_dict(self):
        sql, params = PgMemoryRepository._build_where({})
        assert sql == ""

    def test_simple_equality(self):
        sql, params = PgMemoryRepository._build_where({"type": "fact"})
        assert "WHERE" in sql
        assert "memory_type = %s" in sql
        assert params == ("fact",)

    def test_gte_operator(self):
        sql, params = PgMemoryRepository._build_where({"importance": {"$gte": 0.5}})
        assert "importance >= %s" in sql
        assert params == (0.5,)

    def test_lte_operator(self):
        sql, params = PgMemoryRepository._build_where({"importance": {"$lte": 0.9}})
        assert "importance <= %s" in sql

    def test_gt_operator(self):
        sql, params = PgMemoryRepository._build_where({"importance": {"$gt": 0.3}})
        assert "importance > %s" in sql

    def test_lt_operator(self):
        sql, params = PgMemoryRepository._build_where({"importance": {"$lt": 0.8}})
        assert "importance < %s" in sql

    def test_ne_operator(self):
        sql, params = PgMemoryRepository._build_where({"type": {"$ne": "insight"}})
        assert "memory_type != %s" in sql

    def test_and_filter(self):
        where = {
            "$and": [
                {"type": "fact"},
                {"importance": {"$gte": 0.5}},
            ]
        }
        sql, params = PgMemoryRepository._build_where(where)
        assert "WHERE" in sql
        assert "AND" in sql
        assert len(params) == 2

    def test_or_filter(self):
        where = {
            "$or": [
                {"type": "fact"},
                {"type": "insight"},
            ]
        }
        sql, params = PgMemoryRepository._build_where(where)
        assert "OR" in sql
        assert len(params) == 2


# ============================================================================
# _build_single_condition()
# ============================================================================


class TestBuildSingleCondition:

    def test_dollar_key_skipped(self):
        sql, params = PgMemoryRepository._build_single_condition({"$and": []})
        assert sql == ""
        assert params == []

    def test_column_mapping(self):
        sql, params = PgMemoryRepository._build_single_condition({"type": "fact"})
        assert "memory_type" in sql

    def test_unmapped_column_used_as_is(self):
        sql, params = PgMemoryRepository._build_single_condition({"custom_col": "val"})
        assert "custom_col = %s" in sql


# ============================================================================
# batch_update_metadata()
# ============================================================================


class TestBatchUpdateMetadata:

    def test_batch_update_returns_count(self, repo):
        result = repo.batch_update_metadata(
            ["id1", "id2"],
            [{"importance": 0.9}, {"importance": 0.3}],
        )
        assert result == 2
        assert repo._conn.execute.call_count == 2

    def test_batch_update_empty_lists(self, repo):
        result = repo.batch_update_metadata([], [])
        assert result == 0
        repo._conn.execute.assert_not_called()

    def test_batch_update_mismatched_lengths(self, repo):
        result = repo.batch_update_metadata(["id1"], [{"a": 1}, {"b": 2}])
        assert result == 0

    def test_batch_update_skips_no_matching_fields(self, repo):
        result = repo.batch_update_metadata(
            ["id1"],
            [{"unknown_field": "value"}],
        )
        assert result == 1
        repo._conn.execute.assert_not_called()

    def test_batch_update_last_accessed(self, repo):
        result = repo.batch_update_metadata(
            ["id1", "id2"],
            [{"last_accessed": "2025-01-01"}, {"last_accessed": "2025-01-02"}],
        )
        assert result == 2
        for call in repo._conn.execute.call_args_list:
            assert "last_accessed" in call[0][0]

    def test_batch_update_with_preserved_metadata(self, repo):
        result = repo.batch_update_metadata(
            ["id1"],
            [{"importance": 0.8, "type": "fact"}],
        )
        assert result == 1
        call_sql = repo._conn.execute.call_args[0][0]
        assert "importance" in call_sql
        assert "memory_type" in call_sql
