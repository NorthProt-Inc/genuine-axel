"""Access tracking and batch update management."""

import time
from typing import Set

from backend.core.logging import get_logger
from backend.core.utils.timezone import now_vancouver

from .config import MemoryConfig
from .protocols import MemoryRepositoryProtocol

_log = get_logger("memory.permanent.access")


class AccessTracker:
    """Tracks memory access and manages batch updates.
    
    Accumulates access updates in memory and flushes them to storage
    based on count threshold or time interval.
    """

    def __init__(
        self,
        repository: MemoryRepositoryProtocol,
        flush_threshold: int = MemoryConfig.FLUSH_THRESHOLD,
        flush_interval: int = MemoryConfig.FLUSH_INTERVAL_SECONDS,
    ):
        """Initialize access tracker.
        
        Args:
            repository: Repository for persisting access updates
            flush_threshold: Number of pending updates to trigger auto-flush
            flush_interval: Seconds between auto-flushes
        """
        self._repository = repository
        self._flush_threshold = flush_threshold
        self._flush_interval = flush_interval
        
        self._pending_access_updates: Set[str] = set()
        self._last_flush_time: float = time.time()

    def track_access(self, doc_id: str) -> None:
        """Track memory access.
        
        Args:
            doc_id: Document ID that was accessed
        """
        self._pending_access_updates.add(doc_id)

    def maybe_flush(self) -> None:
        """Check if access updates should be flushed and flush if needed."""
        should_flush = False

        if len(self._pending_access_updates) >= self._flush_threshold:
            should_flush = True
            _log.debug(
                "Auto-flush triggered (threshold)",
                pending=len(self._pending_access_updates),
                threshold=self._flush_threshold,
            )

        elapsed = time.time() - self._last_flush_time
        if elapsed >= self._flush_interval and self._pending_access_updates:
            should_flush = True
            _log.debug(
                "Auto-flush triggered (interval)",
                elapsed_sec=round(elapsed, 1),
                interval=self._flush_interval,
            )

        if should_flush:
            self.flush()

    def flush(self) -> int:
        """Flush pending access updates to storage.

        Returns:
            Number of successfully updated memories
        """
        if not self._pending_access_updates:
            return 0

        ids_to_update = list(self._pending_access_updates)
        self._pending_access_updates.clear()
        self._last_flush_time = time.time()

        now = now_vancouver().isoformat()

        # Batch update (PERF-019)
        metadatas = [{"last_accessed": now} for _ in ids_to_update]
        updated = self._repository.batch_update_metadata(ids_to_update, metadatas)

        if updated < len(ids_to_update):
            _log.warning(
                "Some access updates failed",
                failed_count=len(ids_to_update) - updated,
                total=len(ids_to_update),
            )

        if updated > 0:
            _log.debug("MEM flush", count=updated)

        return updated

    @property
    def pending_count(self) -> int:
        """Get number of pending access updates."""
        return len(self._pending_access_updates)

    def clear_pending(self) -> None:
        """Clear all pending updates without flushing."""
        self._pending_access_updates.clear()
