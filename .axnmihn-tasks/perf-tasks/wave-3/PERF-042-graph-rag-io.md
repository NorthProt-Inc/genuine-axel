# PERF-042: Graph RAG I/O and query optimization

## Metadata
| Field | Value |
|-------|-------|
| ID | PERF-042 |
| Severity | MEDIUM |
| File | backend/memory/graph_rag.py |
| Lines | 517, 964-974, 997-1000 |
| Wave | 3 |
| Depends On | PERF-008 |
| Blocks | INTEGRATION-VERIFY |

## Context
Issues that depend on PERF-008 (index structures) being in place:
1. Sync JSON file save blocks async callers (line 517)
2. Redundant entity lookups in `_format_graph_context` — N+1 pattern (lines 964-974)
3. `find_entities_by_name` called per query word — N DB round-trips (lines 997-1000)

## Current Code
```python
# Line 517: Sync file write from async context
with open(self.persist_path, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

# Lines 964-974: N+1 entity lookups
for r in relations[:cfg.max_format_relations]:
    source = self.graph.get_entity(r.source_id)  # DB call per entity

# Lines 997-1000: Per-word DB query
for word in words:
    if len(word) > 2:
        matches = self.graph.find_entities_by_name(word)  # SQL per word
```

## Target Optimization
1. Use `aiofiles` or debounced write-behind pattern
2. Pre-fetch all needed entities in single batch
3. Batch name search: `WHERE name ILIKE ANY(...)` or fulltext index

## Acceptance Criteria
- [ ] Async file I/O for graph persistence
- [ ] Batch entity lookups
- [ ] Batch name search
- [ ] Existing tests pass
- [ ] ruff check passes

## Estimated Impact
Before: N+1 queries, sync file I/O
After: Batch queries, async I/O
