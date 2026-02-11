"""Adaptive decay calculator for memory importance."""

import math
from datetime import datetime
from typing import List, Optional

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

# Recency paradox thresholds
RECENCY_AGE_HOURS = 168  # 1 week — memory considered "old"
RECENCY_ACCESS_HOURS = 24  # memory considered "recently accessed"
RECENCY_BOOST = 1.3  # boost multiplier for old-but-recently-accessed


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


_cached_graph: object | None = None


def _get_or_create_graph():
    """Return a module-level cached GraphRAG instance.

    Avoids re-loading the knowledge graph JSON on every call.
    Returns None if GraphRAG is not importable.
    """
    global _cached_graph
    if _cached_graph is not None:
        return _cached_graph
    try:
        from backend.memory.graph_rag import GraphRAG

        _cached_graph = GraphRAG()
        return _cached_graph
    except ImportError:
        return None


def get_connection_count(memory_id: str, *, graph=None) -> int:
    """Get number of graph connections for a memory.

    Args:
        memory_id: Memory document ID
        graph: Optional pre-built GraphRAG instance.  When omitted a
            module-level cached instance is used so that the knowledge
            graph JSON is loaded at most once.

    Returns:
        Number of connections, 0 if unavailable
    """
    try:
        g = graph or _get_or_create_graph()
        if g is None:
            return 0
        return g.get_connection_count(memory_id)

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

    def __init__(self, config: Optional[MemoryConfig] = None, peak_hours: Optional[List[int]] = None):
        """Initialize calculator.

        Args:
            config: Optional MemoryConfig override
            peak_hours: Optional peak activity hours (0-23) for circadian stability
        """
        self.config = config or MemoryConfig
        self.peak_hours = peak_hours or []

    def calculate(
        self,
        importance: float,
        created_at: str,
        access_count: int = 0,
        connection_count: int = 0,
        last_accessed: Optional[str] = None,
        memory_type: Optional[str] = None,
        channel_mentions: int = 0,
    ) -> float:
        """Calculate decayed importance score.

        Args:
            importance: Original importance (0-1)
            created_at: ISO timestamp of creation
            access_count: Number of times accessed
            connection_count: Number of graph connections
            last_accessed: ISO timestamp of last access
            memory_type: Memory category (fact, preference, insight, conversation)
            channel_mentions: Number of distinct channels mentioning this memory

        Returns:
            Decayed importance score (never below MIN_RETENTION * original)
        """
        if not created_at:
            return importance

        try:
            hours_passed = get_memory_age_hours(created_at)

            # W2-2: Apply circadian stability to access count
            effective_access_count = access_count
            if self.peak_hours and last_accessed:
                from .dynamic_decay import apply_circadian_stability
                try:
                    last_dt = datetime.fromisoformat(last_accessed.replace("Z", "+00:00"))
                    last_hour = last_dt.hour
                    effective_access_count = apply_circadian_stability(
                        access_count, last_hour, self.peak_hours
                    )
                except Exception:
                    pass

            # Stability from access count (more access = slower decay)
            stability = 1 + self.config.ACCESS_STABILITY_K * math.log(1 + effective_access_count)

            # Resistance from connections (more connections = slower decay)
            resistance = min(1.0, connection_count * self.config.RELATION_RESISTANCE_K)

            # Type-specific decay rate
            type_multiplier = MEMORY_TYPE_DECAY_MULTIPLIERS.get(memory_type or "", 1.0)

            # T-02: Channel diversity boost (more channels = slower decay)
            channel_boost = 1.0 / (1 + self.config.CHANNEL_DIVERSITY_K * channel_mentions)

            # Calculate effective decay rate
            effective_rate = (
                self.config.BASE_DECAY_RATE * type_multiplier * channel_boost / stability * (1 - resistance)
            )

            decayed = importance * math.exp(-effective_rate * hours_passed)

            # Recency paradox: old memory recently accessed gets a boost
            if last_accessed:
                last_access_hours = get_memory_age_hours(last_accessed)

                # If memory is old but accessed recently
                if hours_passed > RECENCY_AGE_HOURS and last_access_hours < RECENCY_ACCESS_HOURS:
                    decayed = decayed * RECENCY_BOOST
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
        processed: list[Optional[dict[str, float]]] = []
        for mem in memories:
            created_at = mem.get("created_at")
            if not created_at:
                processed.append(None)
                continue

            hours_passed = get_memory_age_hours(created_at)
            last_accessed = mem.get("last_accessed")
            last_access_hours = get_memory_age_hours(last_accessed) if last_accessed else -1.0

            # W2-2: Extract hour-of-day for circadian stability
            last_accessed_hour = -1
            if last_accessed:
                try:
                    la_dt = datetime.fromisoformat(last_accessed.replace("Z", "+00:00"))
                    last_accessed_hour = la_dt.hour
                except Exception:
                    pass

            processed.append({
                "importance": float(mem.get("importance", 0.5)),
                "hours_passed": hours_passed,
                "access_count": int(mem.get("access_count", 0)),
                "connection_count": int(mem.get("connection_count", 0)),
                "last_access_hours": last_access_hours,
                "last_accessed_hour": last_accessed_hour,
                "memory_type": type_to_int.get(mem.get("memory_type") or "", 0),
                "channel_mentions": int(mem.get("channel_mentions", 0)),
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
        importance = np.array([d["importance"] for d in valid_data], dtype=np.float64)
        hours_passed = np.array([d["hours_passed"] for d in valid_data], dtype=np.float64)
        access_count = np.array([d["access_count"] for d in valid_data], dtype=np.int32)
        connection_count = np.array([d["connection_count"] for d in valid_data], dtype=np.int32)
        last_access_hours = np.array([d["last_access_hours"] for d in valid_data], dtype=np.float64)
        memory_type = np.array([d["memory_type"] for d in valid_data], dtype=np.int32)
        channel_mentions = np.array([d.get("channel_mentions", 0) for d in valid_data], dtype=np.int32)

        # Create config
        config = _native.decay_ops.DecayConfig()
        config.base_decay_rate = self.config.BASE_DECAY_RATE
        config.min_retention = self.config.MIN_RETENTION
        config.access_stability_k = self.config.ACCESS_STABILITY_K
        config.relation_resistance_k = self.config.RELATION_RESISTANCE_K
        config.set_type_multipliers(1.0, 0.3, 0.5, 0.7)  # conv, fact, pref, insight

        # T-02: Set channel diversity k if native module supports it
        if hasattr(config, "channel_diversity_k"):
            config.channel_diversity_k = self.config.CHANNEL_DIVERSITY_K

        # Call native batch function
        try:
            results_arr = _native.decay_ops.calculate_batch_numpy(
                importance, hours_passed, access_count,
                connection_count, last_access_hours, memory_type,
                channel_mentions, config,
            )
        except TypeError:
            # Fallback: native module not yet rebuilt with channel_mentions
            results_arr = _native.decay_ops.calculate_batch_numpy(
                importance, hours_passed, access_count,
                connection_count, last_access_hours, memory_type,
                config,
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
        from .dynamic_decay import apply_circadian_stability

        results = []
        for p in processed:
            if p is None:
                results.append(0.5)
                continue

            # W2-2: Apply circadian stability to access count
            access_count = p["access_count"]
            if self.peak_hours and p.get("last_accessed_hour", -1) >= 0:
                access_count = apply_circadian_stability(
                    access_count, p["last_accessed_hour"], self.peak_hours
                )

            # Stability from access count
            stability = 1 + self.config.ACCESS_STABILITY_K * math.log(1 + access_count)

            # Resistance from connections
            resistance = min(1.0, p["connection_count"] * self.config.RELATION_RESISTANCE_K)

            # Type-specific decay rate (convert int back to multiplier)
            type_multipliers = [1.0, 0.3, 0.5, 0.7]  # conv, fact, pref, insight
            type_multiplier = type_multipliers[p["memory_type"]]

            # T-02: Channel diversity boost
            channel_mentions = p.get("channel_mentions", 0)
            channel_boost = 1.0 / (1 + self.config.CHANNEL_DIVERSITY_K * channel_mentions)

            # Effective decay rate
            effective_rate = (
                self.config.BASE_DECAY_RATE * type_multiplier * channel_boost / stability * (1 - resistance)
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
