"""
Permanent memory module - Long-term memory storage with ChromaDB.

This module provides:
- LongTermMemory: Main facade for long-term memory operations
- EmbeddingService: Embedding generation with caching
- ChromaDBRepository: ChromaDB CRUD operations
- AdaptiveDecayCalculator: Memory importance decay calculations
- MemoryConsolidator: Memory cleanup and consolidation

Public API (backward compatible):
    from backend.memory.permanent import LongTermMemory, MemoryConfig
    from backend.memory.permanent import PromotionCriteria
    from backend.memory.permanent import calculate_importance_sync, calculate_importance_async
    from backend.memory.permanent import apply_adaptive_decay, get_memory_age_hours
"""

from .config import MemoryConfig
from .protocols import (
    EmbeddingServiceProtocol,
    MemoryRepositoryProtocol,
    DecayCalculatorProtocol,
    ConsolidatorProtocol,
)
from .embedding_service import EmbeddingService
from .repository import ChromaDBRepository
from .decay_calculator import (
    AdaptiveDecayCalculator,
    get_memory_age_hours,
    get_connection_count,
    MEMORY_TYPE_DECAY_MULTIPLIERS,
)
from .consolidator import MemoryConsolidator
from .facade import LongTermMemory, PromotionCriteria
from .importance import calculate_importance_async, calculate_importance_sync
from .migrator import LegacyMemoryMigrator

__all__ = [
    # Main classes
    "LongTermMemory",
    "MemoryConfig",
    "PromotionCriteria",
    # Service classes
    "EmbeddingService",
    "ChromaDBRepository",
    "AdaptiveDecayCalculator",
    "MemoryConsolidator",
    # Protocols
    "EmbeddingServiceProtocol",
    "MemoryRepositoryProtocol",
    "DecayCalculatorProtocol",
    "ConsolidatorProtocol",
    # Functions (backward compatibility)
    "calculate_importance_async",
    "calculate_importance_sync",
    "get_memory_age_hours",
    "get_connection_count",
    "MEMORY_TYPE_DECAY_MULTIPLIERS",
    # Aliases for backward compatibility
    "apply_adaptive_decay",
    # Migration
    "LegacyMemoryMigrator",
]


def apply_adaptive_decay(
    importance: float,
    created_at: str,
    access_count: int = 0,
    connection_count: int = 0,
    last_accessed: str = None,
    memory_type: str = None,
) -> float:
    """Backward compatible wrapper for AdaptiveDecayCalculator.calculate()."""
    calculator = AdaptiveDecayCalculator()
    return calculator.calculate(
        importance=importance,
        created_at=created_at,
        access_count=access_count,
        connection_count=connection_count,
        last_accessed=last_accessed,
        memory_type=memory_type,
    )
