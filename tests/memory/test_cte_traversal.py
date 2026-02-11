"""Tests for OptimizedCTETraversal (Wave 4.2)."""

import pytest

from backend.memory.cte_traversal import (
    TraverseOptions,
    TRAVERSE_QUERY,
    DEFAULT_OPTIONS,
    build_traverse_params,
)


class TestTraverseOptions:

    def test_defaults(self):
        assert DEFAULT_OPTIONS.max_depth == 2
        assert DEFAULT_OPTIONS.min_weight == 0.1
        assert DEFAULT_OPTIONS.max_results == 100

    def test_custom(self):
        opts = TraverseOptions(max_depth=3, min_weight=0.5, max_results=50)
        assert opts.max_depth == 3
        assert opts.min_weight == 0.5

    def test_merge_with_defaults(self):
        custom = TraverseOptions(max_depth=5)
        assert custom.min_weight == 0.1


class TestBuildTraverseParams:

    def test_returns_4_params(self):
        params = build_traverse_params("entity-123", DEFAULT_OPTIONS)
        assert len(params) == 4
        assert params[0] == "entity-123"
        assert params[1] == 2
        assert params[2] == 0.1
        assert params[3] == 100

    def test_custom_options(self):
        opts = TraverseOptions(max_depth=4, min_weight=0.3, max_results=50)
        params = build_traverse_params("e1", opts)
        assert params == ["e1", 4, 0.3, 50]


class TestTraverseQuery:

    def test_query_contains_recursive_cte(self):
        assert "WITH RECURSIVE" in TRAVERSE_QUERY

    def test_query_contains_lateral_join(self):
        assert "LATERAL" in TRAVERSE_QUERY

    def test_query_contains_cycle_detection(self):
        assert "ANY(t.path)" in TRAVERSE_QUERY

    def test_query_has_4_params(self):
        assert "$1" in TRAVERSE_QUERY
        assert "$4" in TRAVERSE_QUERY
