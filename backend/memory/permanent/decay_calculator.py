"""Adaptive decay calculator for memory importance."""

import math
from datetime import datetime
from typing import List, Tuple, Optional

from backend.core.logging import get_logger
from backend.core.utils.timezone import VANCOUVER_TZ, now_vancouver
from .config import MemoryConfig

_log = get_logger("memory.decay")

# Try to import native module for optimized calculations
try:
    import axnmihn_native as _native
    _HAS_NATIVE = True
    _log.info("Native decay module loaded", has_avx2=_native.has_avx2())
except ImportError:
    _native = None
    _HAS_NATIVE = False
    _log.debug("Native decay module not available, using Python fallback")

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

    def calculate_batch(
        self,
        memories: List[dict],
    ) -> List[float]:
        """Calculate decayed importance for a batch of memories.

        Uses native C++ implementation when available for ~50-100x speedup.

        Args:
            memories: List of memory dicts with keys:
                - importance: float (0-1)
                - created_at: ISO timestamp string
                - access_count: int (optional, default 0)
                - connection_count: int (optional, default 0)
                - last_accessed: ISO timestamp string (optional)
                - memory_type: str (optional, one of fact/preference/insight/conversation)

        Returns:
            List of decayed importance scores
        """
        if not memories:
            return []

        # Memory type string to int mapping for native module
        type_to_int = {"conversation": 0, "fact": 1, "preference": 2, "insight": 3}

        # Pre-process: convert timestamps to hours
        processed = []
        for mem in memories:
            created_at = mem.get("created_at")
            if not created_at:
                processed.append(None)
                continue

            hours_passed = get_memory_age_hours(created_at)
            last_accessed = mem.get("last_accessed")
            last_access_hours = get_memory_age_hours(last_accessed) if last_accessed else -1.0

            processed.append({
                "importance": float(mem.get("importance", 0.5)),
                "hours_passed": hours_passed,
                "access_count": int(mem.get("access_count", 0)),
                "connection_count": int(mem.get("connection_count", 0)),
                "last_access_hours": last_access_hours,
                "memory_type": type_to_int.get(mem.get("memory_type"), 0),
            })

        # Use native implementation if available
        if _HAS_NATIVE and len(memories) >= 10:
            return self._calculate_batch_native(processed)

        # Python fallback
        return self._calculate_batch_python(processed)

    def _calculate_batch_native(self, processed: List[Optional[dict]]) -> List[float]:
        """Batch calculation using native C++ module."""
        import numpy as np

        # Filter valid entries and track indices
        valid_indices = []
        valid_data = []
        for i, p in enumerate(processed):
            if p is not None:
                valid_indices.append(i)
                valid_data.append(p)

        if not valid_data:
            return [p["importance"] if p else 0.5 for p in processed]

        # Build numpy arrays
        n = len(valid_data)
        importance = np.array([d["importance"] for d in valid_data], dtype=np.float64)
        hours_passed = np.array([d["hours_passed"] for d in valid_data], dtype=np.float64)
        access_count = np.array([d["access_count"] for d in valid_data], dtype=np.int32)
        connection_count = np.array([d["connection_count"] for d in valid_data], dtype=np.int32)
        last_access_hours = np.array([d["last_access_hours"] for d in valid_data], dtype=np.float64)
        memory_type = np.array([d["memory_type"] for d in valid_data], dtype=np.int32)

        # Create config
        config = _native.decay_ops.DecayConfig()
        config.base_decay_rate = self.config.BASE_DECAY_RATE
        config.min_retention = self.config.MIN_RETENTION
        config.access_stability_k = self.config.ACCESS_STABILITY_K
        config.relation_resistance_k = self.config.RELATION_RESISTANCE_K
        config.set_type_multipliers(1.0, 0.3, 0.5, 0.7)  # conv, fact, pref, insight

        # Call native batch function
        results_arr = _native.decay_ops.calculate_batch_numpy(
            importance, hours_passed, access_count,
            connection_count, last_access_hours, memory_type,
            config
        )

        # Map results back to original indices
        results = []
        valid_idx = 0
        for i, p in enumerate(processed):
            if p is None:
                results.append(0.5)  # Default for invalid entries
            else:
                results.append(float(results_arr[valid_idx]))
                valid_idx += 1

        return results

    def _calculate_batch_python(self, processed: List[Optional[dict]]) -> List[float]:
        """Batch calculation using Python (fallback)."""
        results = []
        for p in processed:
            if p is None:
                results.append(0.5)
                continue

            # Stability from access count
            stability = 1 + self.config.ACCESS_STABILITY_K * math.log(1 + p["access_count"])

            # Resistance from connections
            resistance = min(1.0, p["connection_count"] * self.config.RELATION_RESISTANCE_K)

            # Type-specific decay rate (convert int back to multiplier)
            type_multipliers = [1.0, 0.3, 0.5, 0.7]  # conv, fact, pref, insight
            type_multiplier = type_multipliers[p["memory_type"]]

            # Effective decay rate
            effective_rate = (
                self.config.BASE_DECAY_RATE * type_multiplier / stability * (1 - resistance)
            )

            # Apply decay
            decayed = p["importance"] * math.exp(-effective_rate * p["hours_passed"])

            # Recency paradox boost
            if p["last_access_hours"] >= 0 and p["hours_passed"] > 168 and p["last_access_hours"] < 24:
                decayed *= 1.3

            # Minimum retention
            result = max(decayed, p["importance"] * self.config.MIN_RETENTION)
            results.append(result)

        return results


def is_native_available() -> bool:
    """Check if native C++ module is available."""
    return _HAS_NATIVE
