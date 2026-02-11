"""Tests for backend.memory.pg.graph_repository — PgGraphRepository.

Covers:
- add_entity() and upsert behavior
- get_entity() found and not found
- find_entities_by_name()
- find_entities_by_type()
- entity_exists() true and false
- deduplicate_entity() found and not found
- count_entities()
- add_relation()
- get_relations_for_entity()
- count_relations()
- get_neighbors()
- find_path() found and not found
- get_stats()
"""

from unittest.mock import MagicMock, patch

import pytest

from backend.memory.pg.graph_repository import PgGraphRepository


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def repo(conn_mgr_with_mocks):
    return PgGraphRepository(conn_mgr_with_mocks)


# ============================================================================
# Entity CRUD
# ============================================================================

class TestAddEntity:

    @patch("backend.memory.pg.graph_repository.now_vancouver")
    def test_returns_entity_id(self, mock_now, repo):
        mock_now.return_value.isoformat.return_value = "2025-01-01T00:00:00"
        result = repo.add_entity("ent-1", "Python", "technology")
        assert result == "ent-1"
        repo._conn.execute.assert_called_once()

    @patch("backend.memory.pg.graph_repository.now_vancouver")
    def test_passes_properties_as_json(self, mock_now, repo):
        mock_now.return_value.isoformat.return_value = "2025-01-01T00:00:00"
        repo.add_entity("ent-1", "Python", "tech", properties={"version": "3.12"})
        call_args = repo._conn.execute.call_args[0][1]
        assert '"version": "3.12"' in call_args[3]  # props_json param

    @patch("backend.memory.pg.graph_repository.now_vancouver")
    def test_default_properties_empty(self, mock_now, repo):
        mock_now.return_value.isoformat.return_value = "2025-01-01T00:00:00"
        repo.add_entity("ent-1", "Python", "tech")
        call_args = repo._conn.execute.call_args[0][1]
        assert call_args[3] == "{}"


class TestGetEntity:

    def test_found(self, repo):
        repo._conn.execute_dict.return_value = [
            {"entity_id": "ent-1", "name": "Python", "entity_type": "tech"}
        ]
        result = repo.get_entity("ent-1")
        assert result is not None
        assert result["name"] == "Python"

    def test_not_found(self, repo):
        repo._conn.execute_dict.return_value = []
        result = repo.get_entity("nonexistent")
        assert result is None


class TestFindEntitiesByName:

    def test_returns_matching_entities(self, repo):
        repo._conn.execute_dict.return_value = [
            {"entity_id": "e1", "name": "Python"},
            {"entity_id": "e2", "name": "Python 3"},
        ]
        result = repo.find_entities_by_name("Python")
        assert len(result) == 2

    def test_empty_result(self, repo):
        repo._conn.execute_dict.return_value = []
        result = repo.find_entities_by_name("nonexistent")
        assert result == []


class TestFindEntitiesByType:

    def test_returns_matching_entities(self, repo):
        repo._conn.execute_dict.return_value = [
            {"entity_id": "e1", "name": "Python", "entity_type": "technology"}
        ]
        result = repo.find_entities_by_type("technology")
        assert len(result) == 1


class TestEntityExists:

    def test_exists(self, repo):
        repo._conn.execute_one.return_value = (1,)
        assert repo.entity_exists("ent-1") is True

    def test_not_exists(self, repo):
        repo._conn.execute_one.return_value = None
        assert repo.entity_exists("nonexistent") is False


class TestDeduplicateEntity:

    def test_found(self, repo):
        repo._conn.execute_one.return_value = ("existing-id",)
        result = repo.deduplicate_entity("Python")
        assert result == "existing-id"

    def test_not_found(self, repo):
        repo._conn.execute_one.return_value = None
        result = repo.deduplicate_entity("NewEntity")
        assert result is None


class TestCountEntities:

    def test_returns_count(self, repo):
        repo._conn.execute_one.return_value = (15,)
        assert repo.count_entities() == 15

    def test_returns_zero_when_no_row(self, repo):
        repo._conn.execute_one.return_value = None
        assert repo.count_entities() == 0


# ============================================================================
# Relation CRUD
# ============================================================================

class TestAddRelation:

    @patch("backend.memory.pg.graph_repository.now_vancouver")
    def test_returns_relation_key(self, mock_now, repo):
        mock_now.return_value.isoformat.return_value = "2025-01-01T00:00:00"
        result = repo.add_relation("src", "tgt", "KNOWS")
        assert result == "src--KNOWS-->tgt"
        repo._conn.execute.assert_called_once()

    @patch("backend.memory.pg.graph_repository.now_vancouver")
    def test_custom_weight_and_context(self, mock_now, repo):
        mock_now.return_value.isoformat.return_value = "2025-01-01T00:00:00"
        repo.add_relation("src", "tgt", "USES", weight=2.5, context="daily")
        call_args = repo._conn.execute.call_args[0][1]
        assert call_args[3] == 2.5
        assert call_args[4] == "daily"


class TestGetRelationsForEntity:

    def test_returns_relations(self, repo):
        repo._conn.execute_dict.return_value = [
            {"source_id": "e1", "target_id": "e2", "relation_type": "KNOWS"}
        ]
        result = repo.get_relations_for_entity("e1")
        assert len(result) == 1

    def test_empty(self, repo):
        repo._conn.execute_dict.return_value = []
        result = repo.get_relations_for_entity("e1")
        assert result == []


class TestCountRelations:

    def test_returns_count(self, repo):
        repo._conn.execute_one.return_value = (42,)
        assert repo.count_relations() == 42

    def test_returns_zero_when_no_row(self, repo):
        repo._conn.execute_one.return_value = None
        assert repo.count_relations() == 0


# ============================================================================
# Graph traversal
# ============================================================================

class TestGetNeighbors:

    def test_returns_set_of_entity_ids(self, repo):
        repo._conn.execute.return_value = [("e2",), ("e3",)]
        result = repo.get_neighbors("e1")
        assert result == {"e2", "e3"}

    def test_empty_graph(self, repo):
        repo._conn.execute.return_value = []
        result = repo.get_neighbors("e1")
        assert result == set()

    def test_custom_depth(self, repo):
        repo._conn.execute.return_value = [("e2",)]
        result = repo.get_neighbors("e1", depth=1)
        assert "e2" in result
        call_params = repo._conn.execute.call_args[0][1]
        assert call_params[2] == 1  # depth parameter


class TestFindPath:

    def test_path_found(self, repo):
        repo._conn.execute.return_value = [(["e1", "e2", "e3"],)]
        result = repo.find_path("e1", "e3")
        assert result == ["e1", "e2", "e3"]

    def test_no_path(self, repo):
        repo._conn.execute.return_value = []
        result = repo.find_path("e1", "e99")
        assert result == []

    def test_empty_result_row(self, repo):
        repo._conn.execute.return_value = [()]
        result = repo.find_path("e1", "e3")
        assert result == []


# ============================================================================
# get_stats()
# ============================================================================

class TestGetStats:

    def test_returns_complete_stats(self, repo):
        repo._conn.execute_one.side_effect = [
            (10,),  # count_entities
            (25,),  # count_relations
            (3.5,),  # avg_connections
        ]
        repo._conn.execute.return_value = [("person", 5), ("tech", 5)]
        result = repo.get_stats()
        assert result["total_entities"] == 10
        assert result["total_relations"] == 25
        assert result["entity_types"] == {"person": 5, "tech": 5}
        assert result["avg_connections"] == 3.5

    def test_avg_connections_none(self, repo):
        repo._conn.execute_one.side_effect = [
            (0,),   # count_entities
            (0,),   # count_relations
            (None,), # avg_connections (no data)
        ]
        repo._conn.execute.return_value = []
        result = repo.get_stats()
        assert result["avg_connections"] == 0.0
