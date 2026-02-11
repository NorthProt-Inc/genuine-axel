# PERF-027: Fix LRU cache and blocking sleep in embedding service

## Metadata
| Field | Value |
|-------|-------|
| ID | PERF-027 |
| Severity | HIGH + MEDIUM |
| File | backend/memory/permanent/embedding_service.py |
| Lines | 74, 111-119, 125-131 |
| Wave | 2 |
| Depends On | PERF-005 |
| Blocks | (none) |
| Test File | tests/memory/test_embedding_service.py |

## Context
Three issues:
1. `time.sleep(0.5)` blocks event loop in rate limiter (lines 111-119)
2. LRU cache is actually FIFO — evicts by insertion order, not access order (lines 125-131)
3. `hash()` used for cache key has collision risk across restarts (line 74)

## Current Code
```python
# Line 74: Collision-prone cache key
cache_key = f"{hash(text[:500])}:{task_type}"

# Lines 111-119: Blocking sleep
time.sleep(0.5)

# Lines 125-131: FIFO not LRU
if len(self._cache) >= self._cache_size:
    oldest_key = next(iter(self._cache))
    del self._cache[oldest_key]
self._cache[key] = value
```

## Target Optimization
1. Provide async variant with `asyncio.sleep`
2. On cache hit, move key to end: `self._cache[key] = self._cache.pop(key)`
3. Use deterministic hash: `hashlib.sha256(text[:500].encode()).hexdigest()[:16]`

## Acceptance Criteria
- [ ] True LRU eviction (access order, not insertion order)
- [ ] Deterministic cache keys
- [ ] Async sleep variant available
- [ ] Existing tests pass (`python -m pytest tests/memory/test_embedding_service.py`)
- [ ] ruff check passes

## Estimated Impact
Before: Frequently accessed embeddings evicted, collision risk
After: True LRU behavior, collision-safe keys
