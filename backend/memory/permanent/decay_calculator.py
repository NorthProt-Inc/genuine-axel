"""Adaptive decay calculator for memory importance."""

import math
from datetime import datetime
from typing import Optional

from backend.core.logging import get_logger
from backend.core.utils.timezone import VANCOUVER_TZ, now_vancouver
from .config import MemoryConfig

_log = get_logger("memory.decay")

# Memory type-specific decay multipliers (lower = slower decay)
MEMORY_TYPE_DECAY_MULTIPLIERS = {
    "fact": 0.3,  # Facts decay slowly (user name, important dates)
    "preference": 0.5,  # Preferences decay moderately
    "insight": 0.7,  # Insights decay somewhat faster
    "conversation": 1.0,  # Regular conversation decays at base rate
}


def get_memory_age_hours(created_at: str) -> float:
    """Calculate memory age in hours.

    Args:
        created_at: ISO timestamp of memory creation

    Returns:
        Age in hours, 0 if invalid
    """
    if not created_at:
        return 0

    try:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        now = now_vancouver()

        if created.tzinfo is None:
            created = created.replace(tzinfo=VANCOUVER_TZ)

        return (now - created).total_seconds() / 3600

    except Exception:
        return 0


def get_connection_count(memory_id: str) -> int:
    """Get number of graph connections for a memory.

    Args:
        memory_id: Memory document ID

    Returns:
        Number of connections, 0 if unavailable
    """
    try:
        from backend.memory.graph_rag import GraphRAG

        graph = GraphRAG()
        return graph.get_connection_count(memory_id)

    except ImportError:
        return 0  # GraphRAG module not available

    except Exception as e:
        _log.debug(
            "Graph connection count failed",
            memory_id=memory_id[:8],
            error=str(e),
        )
        return 0


class AdaptiveDecayCalculator:
    """Calculator for adaptive memory importance decay.

    Implements forgetting curve with factors:
    - Base decay rate
    - Memory type (facts decay slower)
    - Access count (more access = slower decay)
    - Graph connections (more connections = slower decay)
    - Recency paradox (old memory recently accessed gets boost)
    """

    def __init__(self, config: MemoryConfig = None):
        """Initialize calculator.

        Args:
            config: Optional MemoryConfig override
        """
        self.config = config or MemoryConfig

    def calculate(
        self,
        importance: float,
        created_at: str,
        access_count: int = 0,
        connection_count: int = 0,
        last_accessed: str = None,
        memory_type: str = None,
    ) -> float:
        """Calculate decayed importance score.

        Args:
            importance: Original importance (0-1)
            created_at: ISO timestamp of creation
            access_count: Number of times accessed
            connection_count: Number of graph connections
            last_accessed: ISO timestamp of last access
            memory_type: Memory category (fact, preference, insight, conversation)

        Returns:
            Decayed importance score (never below MIN_RETENTION * original)
        """
        if not created_at:
            return importance

        try:
            hours_passed = get_memory_age_hours(created_at)

            # Stability from access count (more access = slower decay)
            stability = 1 + self.config.ACCESS_STABILITY_K * math.log(1 + access_count)

            # Resistance from connections (more connections = slower decay)
            resistance = min(1.0, connection_count * self.config.RELATION_RESISTANCE_K)

            # Type-specific decay rate
            type_multiplier = MEMORY_TYPE_DECAY_MULTIPLIERS.get(memory_type, 1.0)

            # Calculate effective decay rate
            effective_rate = (
                self.config.BASE_DECAY_RATE * type_multiplier / stability * (1 - resistance)
            )

            decayed = importance * math.exp(-effective_rate * hours_passed)

            # Recency paradox: old memory recently accessed gets a boost
            if last_accessed:
                last_access_hours = get_memory_age_hours(last_accessed)

                # If memory is old (>1 week) but accessed recently (<24h)
                if hours_passed > 168 and last_access_hours < 24:
                    recency_boost = 1.3
                    decayed = decayed * recency_boost
                    _log.debug(
                        "Recency paradox boost applied",
                        memory_age_days=hours_passed / 24,
                        last_access_hours=last_access_hours,
                    )

            return max(decayed, importance * self.config.MIN_RETENTION)

        except Exception as e:
            _log.warning("Adaptive decay error", error=str(e), created_at=created_at)
            return importance
