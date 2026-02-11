# PERF-007: Batch operations in MemGPT eviction/consolidation

## Metadata
| Field | Value |
|-------|-------|
| ID | PERF-007 |
| Severity | CRITICAL + HIGH |
| File | backend/memory/memgpt.py |
| Lines | 177-179, 231-236, 283-285, 321-325, 431-434 |
| Wave | 1 |
| Depends On | (none) |
| Blocks | (none) |
| Test File | tests/memory/test_memgpt.py |

## Context
Multiple severe performance issues in memgpt.py:
1. `smart_eviction` loads ALL memories into memory at once (line 177)
2. Deletes memories one-by-one in a loop (lines 231-236)
3. `episodic_to_semantic` also loads ALL memories (line 283)
4. Sequential LLM calls per topic group (lines 321-325)
5. Sync LLM call inside async method (lines 431-434)

## Current Code
```python
# Line 177: Full table load
all_memories = self.long_term.get_all_memories(include=["documents", "metadatas"])

# Lines 231-236: One-by-one deletion
for candidate in to_evict:
    try:
        self.long_term.delete_memories([candidate['id']])

# Lines 431-434: Sync in async
async def _extract_semantic_knowledge(self, ...):
    response = self.client.models.generate_content(...)  # sync call
```

## Target Optimization
1. Use cursor-based pagination for memory loading
2. Batch delete: collect all IDs, single `delete_memories([id1, id2, ...])`
3. Use `asyncio.gather` with semaphore for parallel LLM calls
4. Use `await self.client.aio.models.generate_content(...)` for async

## Acceptance Criteria
- [ ] No full-table memory loads
- [ ] Batch delete in single call
- [ ] Parallel LLM calls with concurrency limit
- [ ] Async Gemini client used
- [ ] Existing tests pass (`python -m pytest tests/memory/test_memgpt.py`)
- [ ] ruff check passes

## Estimated Impact
Before: Minutes for consolidation with 500+ memories, event loop blocked
After: Seconds, non-blocking
