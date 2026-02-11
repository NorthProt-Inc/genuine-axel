"""M5 Meta Memory — PostgreSQL access pattern tracking."""

import json
from typing import Any, Dict, List

from backend.core.logging import get_logger

from .connection import PgConnectionManager

_log = get_logger("memory.pg.meta")


class PgMetaMemoryRepository:
    """PostgreSQL replacement for MetaMemory's SQLite persistence.

    The in-memory Counter / defaultdict(set) still live in ``MetaMemory``.
    This class handles the durable storage side.
    """

    def __init__(self, conn_mgr: PgConnectionManager):
        self._conn = conn_mgr

    def persist_pattern(self, pattern: Dict[str, Any]) -> None:
        """Insert a single access pattern record."""
        try:
            self._conn.execute(
                """INSERT INTO memory_access_patterns
                       (query_text, matched_memory_ids, relevance_scores, channel_id, created_at)
                   VALUES (%s, %s::jsonb, %s::jsonb, %s, %s)""",
                (
                    pattern["query_text"],
                    json.dumps(pattern["matched_memory_ids"], ensure_ascii=False),
                    json.dumps(pattern["relevance_scores"]),
                    pattern["channel_id"],
                    pattern["created_at"],
                ),
            )
        except Exception as e:
            _log.warning("Pattern persist failed", error=str(e))

    def get_hot_memories(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get most frequently accessed memories.

        Uses materialized view ``hot_memories`` if it exists,
        otherwise falls back to a direct aggregation query.
        """
        try:
            rows = self._conn.execute_dict(
                "SELECT * FROM hot_memories LIMIT %s", (limit,)
            )
            return rows
        except Exception:
            # Materialized view doesn't exist — aggregate manually
            try:
                rows = self._conn.execute_dict(
                    """SELECT memory_id, access_count, channel_diversity
                       FROM (
                           SELECT
                               unnest(
                                   ARRAY(SELECT jsonb_array_elements_text(matched_memory_ids))
                               ) AS memory_id,
                               COUNT(*) AS access_count,
                               COUNT(DISTINCT channel_id) AS channel_diversity
                           FROM memory_access_patterns
                           GROUP BY 1
                       ) sub
                       ORDER BY access_count DESC
                       LIMIT %s""",
                    (limit,),
                )
                return rows
            except Exception as e2:
                _log.warning("Hot memories query failed", error=str(e2))
                return []

    def prune_old_patterns(self, older_than_days: int = 30) -> int:
        """Remove patterns older than the given threshold."""
        try:
            rows = self._conn.execute(
                """DELETE FROM memory_access_patterns
                   WHERE created_at < NOW() - %s * INTERVAL '1 day'
                   RETURNING id""",
                (older_than_days,),
            )
            deleted = len(rows)
            _log.info("Pruned old access patterns", deleted=deleted, cutoff_days=older_than_days)
            return deleted
        except Exception as e:
            _log.warning("Prune failed", error=str(e))
            return 0
