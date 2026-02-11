"""Optimized recursive CTE for PostgreSQL graph traversal.

Ported from Axel's optimized-cte-traversal (ADR-024 Part 3).
Provides weight pruning, LATERAL JOIN expansion limits, cycle detection,
and DISTINCT ON deduplication.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TraverseOptions:
    """Traversal options for optimized graph queries."""

    max_depth: int = 2
    min_weight: float = 0.1
    max_results: int = 100


DEFAULT_OPTIONS = TraverseOptions()

TRAVERSE_QUERY = """
WITH RECURSIVE traversal AS (
  SELECT
    r.target_id,
    r.relation_type,
    r.weight,
    1 AS depth,
    ARRAY[r.source_id] AS path
  FROM relations r
  WHERE r.source_id = $1
    AND r.weight >= $3

  UNION ALL

  SELECT
    next_r.target_id,
    next_r.relation_type,
    next_r.weight,
    t.depth + 1,
    t.path || t.target_id
  FROM traversal t
  CROSS JOIN LATERAL (
    SELECT target_id, relation_type, weight
    FROM relations
    WHERE source_id = t.target_id
      AND NOT (target_id = ANY(t.path))
      AND weight >= $3
    ORDER BY weight DESC
    LIMIT 10
  ) next_r
  WHERE t.depth < $2
)
SELECT DISTINCT ON (e.entity_id)
  e.entity_id,
  e.name,
  e.entity_type,
  e.mentions AS mention_count,
  e.created_at,
  e.last_accessed AS updated_at,
  e.properties AS metadata,
  t.relation_type,
  t.weight,
  t.depth
FROM traversal t
JOIN entities e ON e.entity_id = t.target_id
ORDER BY e.entity_id, t.weight DESC
LIMIT $4;
"""


def build_traverse_params(
    entity_id: str, options: TraverseOptions | None = None
) -> list[str | int | float]:
    """Build parameter list for TRAVERSE_QUERY."""
    opts = options or DEFAULT_OPTIONS
    return [entity_id, opts.max_depth, opts.min_weight, opts.max_results]
