# PERF-005: Eliminate double embedding in facade.add()

## Metadata
| Field | Value |
|-------|-------|
| ID | PERF-005 |
| Severity | CRITICAL |
| File | backend/memory/permanent/facade.py |
| Lines | 341, 348 |
| Wave | 1 |
| Depends On | (none) |
| Blocks | (none) |
| Test File | tests/memory/test_facade.py |

## Context
`add()` generates TWO separate embedding API calls per memory: one for `_find_similar()` (task_type="retrieval_query") and one for storage (task_type="retrieval_document"). Both embed the same text but different task types mean different cache keys.

## Current Code
```python
# backend/memory/permanent/facade.py:341
existing = self._find_similar(content, threshold=MemoryConfig.DUPLICATE_THRESHOLD)
# backend/memory/permanent/facade.py:348
embedding = self._embedding_service.get_embedding(content)
```

## Target Optimization
Generate embedding once with `retrieval_document` task type, use for both similarity search and storage. `query_by_embedding` already accepts pre-computed embeddings.

## Acceptance Criteria
- [ ] Only ONE embedding API call per `add()` invocation
- [ ] Deduplication still works correctly
- [ ] Existing tests pass (`python -m pytest tests/memory/test_facade.py`)
- [ ] ruff check passes

## Estimated Impact
Before: 2 embedding API calls per memory add (~400ms)
After: 1 embedding API call per memory add (~200ms) -- 50% reduction
