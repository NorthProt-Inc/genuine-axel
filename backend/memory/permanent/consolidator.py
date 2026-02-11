"""Memory consolidation service."""

from typing import Dict, List

from backend.core.logging import get_logger
from .config import MemoryConfig
from .decay_calculator import AdaptiveDecayCalculator, get_connection_count, is_native_available

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
    ):
        """Initialize consolidator.

        Args:
            repository: ChromaDBRepository instance
            decay_calculator: Optional decay calculator
            config: Optional MemoryConfig override
        """
        self.repository = repository
        self.decay_calculator = decay_calculator or AdaptiveDecayCalculator()
        self.config = config or MemoryConfig

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

            # Process preservation first
            for doc_id, metadata in to_preserve:
                try:
                    self.repository.update_metadata(
                        doc_id,
                        {**metadata, "preserved": True},
                    )
                    report["preserved"] += 1
                except Exception as e:
                    _log.warning("Preserve update failed", error=str(e), id=doc_id)

            # Calculate decayed importance in batch
            to_delete, decayed_values = self._calculate_deletions_batch(batch_data)
            report["deleted"] = len(to_delete)

            # Delete faded memories
            if to_delete:
                self.repository.delete(to_delete)
                _log.info("Deleted faded memories", count=len(to_delete))

            # T-03: Update surviving memories' importance to decayed value
            surviving_updates = self._get_surviving_updates(
                batch_data, decayed_values, to_delete
            )
            if surviving_updates:
                updated = 0
                for doc_id, new_importance in surviving_updates:
                    try:
                        self.repository.update_metadata(
                            doc_id, {"importance": new_importance}
                        )
                        updated += 1
                    except Exception as e:
                        _log.warning("Surviving update failed", error=str(e), id=doc_id)
                report["surviving_updated"] = updated

            _log.info(
                "MEM consolidate",
                deleted=report["deleted"],
                preserved=report["preserved"],
                surviving_updated=report.get("surviving_updated", 0),
                native=is_native_available(),
            )

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

        # Prepare batch input for decay calculator
        memories_for_decay = []
        for _, doc_id, metadata in batch_data:
            created_at = metadata.get("created_at") or metadata.get("timestamp", "")
            importance = metadata.get("importance", 0.5)
            access_count = metadata.get("access_count", 0)
            connection_count = get_connection_count(doc_id)
            last_accessed = metadata.get("last_accessed")
            memory_type = metadata.get("type")

            memories_for_decay.append({
                "importance": importance,
                "created_at": created_at,
                "access_count": access_count,
                "connection_count": connection_count,
                "last_accessed": last_accessed,
                "memory_type": memory_type,
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
