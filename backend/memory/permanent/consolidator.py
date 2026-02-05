"""Memory consolidation service."""

from typing import Dict, Any

from backend.core.logging import get_logger
from .config import MemoryConfig
from .decay_calculator import AdaptiveDecayCalculator, get_connection_count

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

        Returns:
            Report dict with deleted, preserved, checked counts
        """
        report = {"deleted": 0, "preserved": 0, "checked": 0}

        try:
            all_memories = self.repository.get_all(include=["metadatas"])
            ids = all_memories.get("ids", [])
            metadatas = all_memories.get("metadatas", [])

            to_delete = []

            for doc_id, metadata in zip(ids, metadatas):
                if not metadata:
                    continue

                report["checked"] += 1

                created_at = metadata.get("created_at") or metadata.get("timestamp", "")
                importance = metadata.get("importance", 0.5)
                repetitions = metadata.get("repetitions", 1)
                access_count = metadata.get("access_count", 0)
                is_preserved = metadata.get("preserved", False)

                # Skip already preserved memories
                if is_preserved:
                    continue

                # Calculate decayed importance
                connection_count = get_connection_count(doc_id)
                decayed_importance = self.decay_calculator.calculate(
                    importance,
                    created_at,
                    access_count=access_count,
                    connection_count=connection_count,
                )

                # Check deletion criteria
                if (
                    decayed_importance < self.config.DECAY_DELETE_THRESHOLD
                    and repetitions < 2
                    and access_count < 3
                ):
                    to_delete.append(doc_id)
                    report["deleted"] += 1
                    continue

                # Mark high-repetition memories as preserved
                if repetitions >= self.config.PRESERVE_REPETITIONS:
                    try:
                        self.repository.update_metadata(
                            doc_id,
                            {**metadata, "preserved": True},
                        )
                        report["preserved"] += 1

                    except Exception as e:
                        _log.warning("Preserve update failed", error=str(e), id=doc_id)

            # Delete faded memories
            if to_delete:
                self.repository.delete(to_delete)
                _log.info("Deleted faded memories", count=len(to_delete))

            _log.info(
                "MEM consolidate",
                deleted=report["deleted"],
                preserved=report["preserved"],
            )

            return report

        except Exception as e:
            _log.error("Consolidation error", error=str(e))
            return report
