"""Token counting with SHA-256 LRU cache."""

import hashlib
from collections import OrderedDict
from backend.core.logging import get_logger

_log = get_logger("core.token_counter")


class TokenCounter:
    """Estimates token count with LRU caching."""

    CHARS_PER_TOKEN = 4  # fallback estimate

    def __init__(self, cache_size: int = 1000):
        self._cache: OrderedDict[str, int] = OrderedDict()
        self._cache_size = cache_size

    def count(self, text: str) -> int:
        """Count tokens in text with caching.

        Args:
            text: Input text

        Returns:
            Estimated token count
        """
        key = hashlib.sha256(text.encode()).hexdigest()[:16]
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]

        tokens = len(text) // self.CHARS_PER_TOKEN
        if len(self._cache) >= self._cache_size:
            self._cache.popitem(last=False)
        self._cache[key] = tokens
        return tokens

    def clear(self) -> int:
        """Clear cache and return number of entries cleared."""
        count = len(self._cache)
        self._cache.clear()
        return count
