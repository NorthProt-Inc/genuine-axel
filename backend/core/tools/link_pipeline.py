"""URL content ingestion pipeline."""

import asyncio
import re
from typing import Optional
from backend.core.logging import get_logger
from backend.core.utils.http_pool import get_client

_log = get_logger("tools.link_pipeline")

MAX_CONCURRENT = 3
IMPORTANCE_BASE = 0.4
IMPORTANCE_KEYWORDS = {"important", "remember", "\uc911\uc694", "\uae30\uc5b5", "save", "\uc800\uc7a5"}

_semaphore = asyncio.Semaphore(MAX_CONCURRENT)

URL_PATTERN = re.compile(r'https?://[^\s<>"{}|\\^`\[\]]+')

_link_cache: "LinkCache | None" = None


def _get_link_cache() -> "LinkCache":
    global _link_cache
    if _link_cache is None:
        _link_cache = LinkCache()
    return _link_cache


class LinkCache:
    """Simple LRU-style cache for link content with max size eviction."""

    def __init__(self, max_size: int = 100) -> None:
        self._max_size = max_size
        self._data: dict[str, object] = {}

    def get(self, url: str) -> object | None:
        return self._data.get(url)

    def set(self, url: str, value: object) -> None:
        if len(self._data) >= self._max_size and url not in self._data:
            oldest = next(iter(self._data))
            del self._data[oldest]
        self._data[url] = value

    def has(self, url: str) -> bool:
        return url in self._data

    def clear(self) -> None:
        self._data.clear()


def extract_urls(text: str) -> list[str]:
    """Extract URLs from text.

    Args:
        text: Input text

    Returns:
        List of extracted URLs
    """
    return URL_PATTERN.findall(text)


def calculate_importance(context: str) -> float:
    """Calculate importance score based on context keywords.

    Args:
        context: Surrounding context text

    Returns:
        Importance score (0.0-1.0)
    """
    importance = IMPORTANCE_BASE
    context_lower = context.lower()
    for kw in IMPORTANCE_KEYWORDS:
        if kw in context_lower:
            importance += 0.15
            break
    return min(importance, 1.0)


async def ingest_url(
    url: str,
    context: str = "",
    memory_store=None,
) -> Optional[dict]:
    """Fetch URL content and optionally store to memory.

    Args:
        url: URL to fetch
        context: Surrounding context for importance calculation
        memory_store: Optional memory store to save content

    Returns:
        Dict with url, chars, importance or None on failure
    """
    if not url or not url.startswith(("http://", "https://")):
        return None

    cache = _get_link_cache()
    cached = cache.get(url)
    if cached is not None:
        return cached  # type: ignore[return-value]

    async with _semaphore:
        try:
            client = await get_client("link_pipeline", timeout=15.0)
            resp = await client.get(url)
            resp.raise_for_status()
            text = resp.text[:50000]  # Limit content size

            importance = calculate_importance(context)

            if memory_store and text:
                try:
                    memory_store.add(
                        content=f"[URL: {url}]\n{text[:2000]}",
                        memory_type="reference",
                        importance=importance,
                    )
                except Exception as e:
                    _log.warning("Memory store failed", url=url[:50], error=str(e)[:80])

            result = {
                "url": url,
                "chars": len(text),
                "importance": importance,
            }
            cache.set(url, result)
            return result

        except Exception as e:
            _log.warning("URL fetch failed", url=url[:50], error=str(e)[:80])
            return None
