"""Memory consolidation service."""

from datetime import datetime, timezone
from typing import Dict, List

from backend.core.logging import get_logger
from .config import MemoryConfig
from .decay_calculator import AdaptiveDecayCalculator, get_connection_count, is_native_available
from .importance import calculate_importance_sync

_log = get_logger("memory.consolidator")


class MemoryConsolidator:
    """Service for memory consolidation and cleanup.

    Handles:
    - Deleting low-importance faded memories
    - Marking high-repetition memories as preserved
    - Periodic cleanup operations
    """

    def __init__(
        self,
        repository,
        decay_calculator: AdaptiveDecayCalculator = None,
        config: MemoryConfig = None,
        meta_memory=None,
        conn_mgr=None,
    ):
        """Initialize consolidator.

        Args:
            repository: ChromaDBRepository instance
            decay_calculator: Optional decay calculator
            config: Optional MemoryConfig override
            meta_memory: Optional MetaMemory for channel_mentions lookup
            conn_mgr: Optional connection manager for behavior metrics
        """
        self.repository = repository
        self.decay_calculator = decay_calculator or AdaptiveDecayCalculator()
        self.config = config or MemoryConfig
        self._meta_memory = meta_memory
        self._conn_mgr = conn_mgr

    def consolidate(self) -> Dict[str, int]:
        """Run memory consolidation.

        Deletes memories with:
        - Decayed importance below threshold
        - Low repetitions (<2)
        - Low access count (<3)

        Marks as preserved:
        - Memories with repetitions >= PRESERVE_REPETITIONS

        Uses batch processing with native C++ module when available
        for significant speedup (~50-70x) on large datasets.

        Returns:
            Report dict with deleted, preserved, checked counts
        """
        report = {"deleted": 0, "preserved": 0, "checked": 0}

        # W5-1: Apply dynamic decay config when feature-gated on
        from .dynamic_decay import DYNAMIC_DECAY_ENABLED

        if DYNAMIC_DECAY_ENABLED:
            from .dynamic_decay import calculate_dynamic_config, collect_behavior_metrics

            metrics = collect_behavior_metrics(self._conn_mgr)
            dynamic_config = calculate_dynamic_config(metrics)
            self.decay_calculator.config.BASE_DECAY_RATE = dynamic_config["base_rate"]
            self.decay_calculator.peak_hours = metrics.peak_hours
            _log.info(
                "Dynamic decay applied",
                base_rate=dynamic_config["base_rate"],
                recency_boost=dynamic_config["recency_boost"],
                peak_hours=metrics.peak_hours,
            )

        try:
            all_memories = self.repository.get_all(include=["metadatas"])
            ids = all_memories.get("ids", [])
            metadatas = all_memories.get("metadatas", [])

            # Filter and prepare batch data
            batch_data = []  # List of (index, doc_id, metadata) for non-preserved
            to_preserve = []  # Memories to mark as preserved

            for i, (doc_id, metadata) in enumerate(zip(ids, metadatas)):
                if not metadata:
                    continue

                report["checked"] += 1

                is_preserved = metadata.get("preserved", False)
                if is_preserved:
                    continue

                repetitions = metadata.get("repetitions", 1)

                # Check if should be preserved
                if repetitions >= self.config.PRESERVE_REPETITIONS:
                    to_preserve.append((doc_id, metadata))
                else:
                    batch_data.append((i, doc_id, metadata))

            # Process preservation first (PERF-021: batch update)
            if to_preserve:
                preserve_ids = [doc_id for doc_id, _ in to_preserve]
                preserve_metadatas = [{**metadata, "preserved": True} for _, metadata in to_preserve]
                preserved_count = self.repository.batch_update_metadata(preserve_ids, preserve_metadatas)
                report["preserved"] = preserved_count
                if preserved_count < len(to_preserve):
                    _log.warning("Some preservation updates failed",
                                failed=len(to_preserve) - preserved_count)

            # Calculate decayed importance in batch
            to_delete, decayed_values = self._calculate_deletions_batch(batch_data)
            report["deleted"] = len(to_delete)

            # Delete faded memories
            if to_delete:
                self.repository.delete(to_delete)
                _log.info("Deleted faded memories", count=len(to_delete))

            # T-03: Update surviving memories' importance to decayed value (PERF-022: batch update)
            surviving_updates = self._get_surviving_updates(
                batch_data, decayed_values, to_delete
            )
            if surviving_updates:
                update_ids = [doc_id for doc_id, _ in surviving_updates]
                update_metadatas = [{"importance": new_importance} for _, new_importance in surviving_updates]
                updated = self.repository.batch_update_metadata(update_ids, update_metadatas)
                report["surviving_updated"] = updated
                if updated < len(surviving_updates):
                    _log.warning("Some surviving updates failed",
                                failed=len(surviving_updates) - updated)

            _log.info(
                "MEM consolidate",
                deleted=report["deleted"],
                preserved=report["preserved"],
                surviving_updated=report.get("surviving_updated", 0),
                native=is_native_available(),
            )

            # W5-2: Reassess old, high-access memories
            reassessed = self._reassess_old_memories(ids, metadatas)
            report["reassessed"] = reassessed

            return report

        except Exception as e:
            _log.error("Consolidation error", error=str(e))
            return report

    def _calculate_deletions_batch(
        self,
        batch_data: List[tuple],
    ) -> tuple[List[str], List[float]]:
        """Calculate which memories should be deleted using batch processing.

        Args:
            batch_data: List of (index, doc_id, metadata) tuples

        Returns:
            Tuple of (doc_ids to delete, all decayed importance values)
        """
        if not batch_data:
            return [], []

        # Build a single GraphRAG instance for the entire batch so we
        # don't reload the knowledge-graph JSON for every memory.
        try:
            from backend.memory.graph_rag import GraphRAG
            shared_graph = GraphRAG()
        except ImportError:
            shared_graph = None

        # Prepare batch input for decay calculator
        memories_for_decay = []
        for _, doc_id, metadata in batch_data:
            created_at = metadata.get("created_at") or metadata.get("timestamp", "")
            importance = metadata.get("importance")
            if importance is None:
                importance = 0.5
                _log.warning("importance missing, using default", doc_id=doc_id[:8])
            access_count = metadata.get("access_count", 0)
            connection_count = get_connection_count(doc_id, graph=shared_graph)
            last_accessed = metadata.get("last_accessed")
            memory_type = metadata.get("type")

            memories_for_decay.append({
                "importance": importance,
                "created_at": created_at,
                "access_count": access_count,
                "connection_count": connection_count,
                "last_accessed": last_accessed,
                "memory_type": memory_type,
                "channel_mentions": (
                    self._meta_memory.get_channel_mentions(doc_id)
                    if self._meta_memory
                    else 0
                ),
            })

        # Batch calculate decayed importance
        decayed_values = self.decay_calculator.calculate_batch(memories_for_decay)

        # Determine deletions
        to_delete = []
        for (_, doc_id, metadata), decayed_importance in zip(batch_data, decayed_values):
            repetitions = metadata.get("repetitions", 1)
            access_count = metadata.get("access_count", 0)

            if (
                decayed_importance < self.config.DECAY_DELETE_THRESHOLD
                and repetitions < 2
                and access_count < 3
            ):
                to_delete.append(doc_id)

        return to_delete, decayed_values

    def _get_surviving_updates(
        self,
        batch_data: List[tuple],
        decayed_values: List[float],
        to_delete: List[str],
    ) -> List[tuple[str, float]]:
        """Get surviving memories that need importance updates.

        Args:
            batch_data: List of (index, doc_id, metadata) tuples
            decayed_values: Decayed importance for each batch item
            to_delete: Doc IDs marked for deletion

        Returns:
            List of (doc_id, new_importance) tuples
        """
        if not batch_data or not decayed_values:
            return []

        delete_set = set(to_delete)
        updates = []
        for (_, doc_id, _metadata), decayed in zip(batch_data, decayed_values):
            if doc_id not in delete_set:
                updates.append((doc_id, decayed))
        return updates

    def _reassess_old_memories(
        self,
        ids: List[str],
        metadatas: List[dict],
    ) -> int:
        """Reassess importance of old, high-access memories.

        Uses REASSESS_AGE_HOURS and REASSESS_BATCH_SIZE from config.
        Selects memories older than the threshold with high access counts,
        then recalculates importance using sync LLM evaluation.

        Args:
            ids: All memory IDs
            metadatas: All memory metadata dicts

        Returns:
            Number of reassessed memories
        """
        age_hours = self.config.REASSESS_AGE_HOURS
        batch_size = self.config.REASSESS_BATCH_SIZE
        now = datetime.now(timezone.utc)

        candidates = []
        for doc_id, metadata in zip(ids, metadatas):
            if not metadata:
                continue
            created_at = metadata.get("created_at", "")
            access_count = metadata.get("access_count", 0)
            if not created_at or access_count < 3:
                continue
            try:
                created_dt = datetime.fromisoformat(created_at)
                if created_dt.tzinfo is None:
                    created_dt = created_dt.replace(tzinfo=timezone.utc)
                age = (now - created_dt).total_seconds() / 3600
                if age >= age_hours:
                    candidates.append((doc_id, metadata, access_count))
            except (ValueError, TypeError):
                continue

        # Sort by access_count descending, take top batch_size
        candidates.sort(key=lambda x: x[2], reverse=True)
        candidates = candidates[:batch_size]

        if not candidates:
            return 0

        reassessed = 0

        for doc_id, metadata, _ac in candidates:
            try:
                content = metadata.get("content", "")
                new_importance = calculate_importance_sync(content, "", "")
                self.repository.batch_update_metadata(
                    [doc_id], [{"importance": new_importance}]
                )
                reassessed += 1
            except Exception as e:
                _log.warning("Reassessment failed", doc_id=doc_id[:8], error=str(e)[:80])

        if reassessed:
            _log.info("Reassessed old memories", count=reassessed)

        return reassessed
