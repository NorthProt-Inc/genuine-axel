# PERF-008: Fix O(n^2) algorithms in GraphRAG

## Metadata
| Field | Value |
|-------|-------|
| ID | PERF-008 |
| Severity | HIGH |
| File | backend/memory/graph_rag.py |
| Lines | 223-228, 305-308, 409-431, 447-461 |
| Wave | 1 |
| Depends On | (none) |
| Blocks | (none) |
| Test File | tests/memory/ |

## Context
Multiple O(n^2) or worse algorithms:
1. Entity deduplication: O(n^2) pairwise name comparison (lines 223-228)
2. `get_entity_relations`: O(R) scan per entity (lines 305-308)
3. TF-IDF weights: O(R*C) nested scan (lines 409-431)
4. BFS uses `list.pop(0)` -- O(n) dequeue (lines 447-461)

## Current Code
```python
# Line 223-228: O(n^2) dedup
for existing in self.entities.values():
    if self._names_match(entity.name, existing.name):
        existing.mention_count += 1
        return existing.id

# Line 305-308: O(R) per entity
[r for r in self.relations.values()
 if r.source_id == entity_id or r.target_id == entity_id]

# Line 447-461: O(n) pop(0)
while queue:
    current, path = queue.pop(0)
```

## Target Optimization
1. Add name-to-entity index dict for O(1) lookups
2. Build relation index `Dict[str, List[Relation]]` keyed by entity_id
3. Pre-compute cooccurrence counts in single pass
4. Use `collections.deque` and `popleft()` for BFS

## Acceptance Criteria
- [ ] Entity lookup is O(1) via index
- [ ] Relation lookup is O(1) via index
- [ ] TF-IDF calculation is O(R + C) not O(R * C)
- [ ] BFS uses deque for O(1) dequeue
- [ ] Existing tests pass
- [ ] ruff check passes

## Estimated Impact
Before: O(n^2) entity dedup, O(E*R) relation queries
After: O(1) lookups, O(V+E) BFS
