"""M5 Meta Memory — Access pattern tracking and hot memory surfacing.

Tracks query-memory access patterns for:
- Hot memory detection (most frequently accessed)
- Channel diversity counting (for T-02 decay integration)
- Prefetch candidate identification
"""

import json
from collections import Counter, defaultdict
from datetime import timedelta
from typing import Any, Dict, List, Optional, Set

from backend.core.logging import get_logger
from backend.core.utils.timezone import now_vancouver

_log = get_logger("memory.meta")


class MetaMemory:
    """Track query-memory access patterns for hot memory detection and channel diversity."""

    def __init__(self, conn_mgr=None):
        """Initialize MetaMemory.

        Args:
            conn_mgr: Optional SQLiteConnectionManager for persistence.
                      If None, operates in memory-only mode.
        """
        self._conn_mgr = conn_mgr
        # In-memory tracking (persisted to SQLite periodically)
        self._memory_access: Counter = Counter()  # memory_id -> access_count
        self._memory_channels: defaultdict[str, Set[str]] = defaultdict(set)  # memory_id -> {channel_ids}
        self._patterns: List[Dict[str, Any]] = []

    def record_access(
        self,
        query_text: str,
        matched_memory_ids: List[str],
        relevance_scores: Optional[List[float]] = None,
        channel_id: str = "default",
    ) -> None:
        """Record a query-memory access pattern.

        Args:
            query_text: The query that triggered the access
            matched_memory_ids: Memory IDs that matched the query
            relevance_scores: Optional relevance scores for each match
            channel_id: Channel where the access occurred
        """
        for mem_id in matched_memory_ids:
            self._memory_access[mem_id] += 1
            self._memory_channels[mem_id].add(channel_id)

        pattern = {
            "query_text": query_text[:200],
            "matched_memory_ids": matched_memory_ids,
            "relevance_scores": relevance_scores or [],
            "channel_id": channel_id,
            "created_at": now_vancouver().isoformat(),
        }
        self._patterns.append(pattern)

        if self._conn_mgr:
            self._persist_pattern(pattern)

        _log.info(
            "Access pattern recorded",
            query_preview=query_text[:30],
            matched=len(matched_memory_ids),
        )

    def get_hot_memories(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get most frequently accessed memories.

        Args:
            limit: Maximum number of results

        Returns:
            List of dicts with memory_id, access_count, channel_diversity
        """
        hot = self._memory_access.most_common(limit)
        return [
            {
                "memory_id": mid,
                "access_count": count,
                "channel_diversity": len(self._memory_channels.get(mid, set())),
            }
            for mid, count in hot
        ]

    def get_channel_mentions(self, memory_id: str) -> int:
        """Get number of distinct channels that accessed a memory.

        Args:
            memory_id: Memory document ID

        Returns:
            Number of distinct channels
        """
        return len(self._memory_channels.get(memory_id, set()))

    def prune_old_patterns(self, older_than_days: int = 30) -> int:
        """Remove patterns older than specified days.

        Args:
            older_than_days: Age threshold in days

        Returns:
            Number of patterns pruned
        """
        if not self._conn_mgr:
            return 0

        cutoff = (now_vancouver() - timedelta(days=older_than_days)).isoformat()

        try:
            with self._conn_mgr.get_connection() as conn:
                cursor = conn.execute(
                    "DELETE FROM access_patterns WHERE created_at < ?",
                    (cutoff,),
                )
                deleted = cursor.rowcount
                conn.commit()
                _log.info("Pruned old access patterns", deleted=deleted, cutoff_days=older_than_days)
                return deleted
        except Exception as e:
            _log.warning("Prune failed", error=str(e))
            return 0

    def _persist_pattern(self, pattern: Dict[str, Any]) -> None:
        """Persist a single pattern to SQLite."""
        try:
            with self._conn_mgr.get_connection() as conn:
                conn.execute(
                    """INSERT INTO access_patterns
                       (query_text, matched_memory_ids, relevance_scores, channel_id, created_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        pattern["query_text"],
                        json.dumps(pattern["matched_memory_ids"]),
                        json.dumps(pattern["relevance_scores"]),
                        pattern["channel_id"],
                        pattern["created_at"],
                    ),
                )
                conn.commit()
        except Exception as e:
            _log.warning("Pattern persist failed", error=str(e))

    @property
    def stats(self) -> Dict[str, int]:
        """Get meta memory statistics."""
        return {
            "tracked_memories": len(self._memory_access),
            "total_patterns": len(self._patterns),
            "unique_channels": len(
                set().union(*(channels for channels in self._memory_channels.values()))
                if self._memory_channels
                else set()
            ),
        }
