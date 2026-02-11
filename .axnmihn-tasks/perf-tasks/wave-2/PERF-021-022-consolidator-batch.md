# PERF-021/022: Batch updates in consolidator

## Metadata
| Field | Value |
|-------|-------|
| ID | PERF-021, PERF-022 |
| Severity | HIGH |
| File | backend/memory/permanent/consolidator.py |
| Lines | 85-93, 110-117 |
| Wave | 2 |
| Depends On | PERF-019 |
| Blocks | (none) |
| Test File | tests/memory/ |

## Context
Two N+1 update patterns:
1. Preservation updates one-by-one (lines 85-93)
2. Surviving importance updates one-by-one (lines 110-117)

## Current Code
```python
# Lines 85-93
for doc_id, metadata in to_preserve:
    self.repository.update_metadata(doc_id, {**metadata, "preserved": True})

# Lines 110-117
for doc_id, new_importance in surviving_updates:
    self.repository.update_metadata(doc_id, {"importance": new_importance})
```

## Target Optimization
Batch both operations. For PG: `UPDATE memories SET preserved = true WHERE uuid = ANY(%s)`. For ChromaDB: `collection.update(ids=[...], metadatas=[...])`.

## Acceptance Criteria
- [ ] Preservation updates batched into single call
- [ ] Importance updates batched into single call
- [ ] Works for both ChromaDB and PG backends
- [ ] Existing tests pass
- [ ] ruff check passes

## Estimated Impact
Before: 200+ DB calls per consolidation
After: 2 DB calls per consolidation
