"""Memory promotion criteria and utilities."""

import re
from typing import Dict

from .config import MemoryConfig


def _text_similarity(a: str, b: str) -> float:
    """Fast text similarity score (0-1)."""
    from difflib import SequenceMatcher
    return SequenceMatcher(None, a.lower()[:500], b.lower()[:500]).ratio()


class PromotionCriteria:
    """Criteria for promoting memories to long-term storage."""

    @classmethod
    def should_promote(
        cls,
        content: str,
        repetitions: int = 1,
        importance: float = 0.5,
        force: bool = False,
    ) -> tuple[bool, str]:
        """Check if memory should be promoted to long-term storage.

        Args:
            content: Memory content
            repetitions: Number of times seen
            importance: Importance score (0-1)
            force: Force promotion regardless of criteria

        Returns:
            Tuple of (should_promote, reason)
        """
        if force:
            return True, "forced_promotion"

        if importance >= MemoryConfig.MIN_IMPORTANCE:
            return True, f"importance:{importance:.2f}"

        if repetitions >= 2 and importance >= 0.35:
            return True, f"repetitions:{repetitions},importance:{importance:.2f}"

        return False, f"low_importance:{importance:.2f}"


class ContentKeyGenerator:
    """Generate normalized content keys for deduplication."""

    def __init__(self):
        """Initialize key generator with particle pattern."""
        # Compile regex for particle removal (PERF-019)
        particles = [
            "은", "는", "이", "가", "을", "를", "의", "에", "와", "과", "로", "으로",
            "에서", "까지", "부터", "도", "만", "뿐", "이다", "입니다", "이에요", "예요", "임", "임.",
            "'s", "is", "the", "a", "an",
        ]
        self._particle_pattern = re.compile("|".join(re.escape(p) for p in particles))

    def get_content_key(self, content: str) -> str:
        """Generate normalized content key for deduplication.
        
        Args:
            content: Original content text
            
        Returns:
            Normalized key string (max 100 chars)
        """
        text = content.lower().strip()

        # Remove common particles using single regex (PERF-019)
        text = self._particle_pattern.sub("", text)

        text = re.sub(r"[^\w\s가-힣]", "", text)
        text = re.sub(r"\s+", " ", text).strip()

        return text[:100]


class RepetitionCache:
    """Cache for tracking memory repetition counts."""

    def __init__(self):
        """Initialize empty cache."""
        self._cache: Dict[str, int] = {}

    def increment(self, key: str) -> int:
        """Increment repetition count for key.
        
        Args:
            key: Content key
            
        Returns:
            New repetition count
        """
        self._cache[key] = self._cache.get(key, 0) + 1
        return self._cache[key]

    def get(self, key: str) -> int:
        """Get repetition count for key.
        
        Args:
            key: Content key
            
        Returns:
            Repetition count (0 if not found)
        """
        return self._cache.get(key, 0)

    def set(self, key: str, count: int) -> None:
        """Set repetition count for key.
        
        Args:
            key: Content key
            count: Repetition count
        """
        self._cache[key] = count

    def __len__(self) -> int:
        """Get cache size."""
        return len(self._cache)

    def clear(self) -> None:
        """Clear all cached counts."""
        self._cache.clear()
