# PERF-019/020: Batch operations in facade (access updates + stats)

## Metadata
| Field | Value |
|-------|-------|
| ID | PERF-019, PERF-020 |
| Severity | HIGH |
| File | backend/memory/permanent/facade.py |
| Lines | 243-253, 260-300, 592-598, 658-667 |
| Wave | 2 |
| Depends On | PERF-005 |
| Blocks | (none) |
| Test File | tests/memory/test_facade.py |

## Context
Four issues bundled (same file as PERF-005):
1. `_load_repetition_cache` loads ALL memory metadata on init (lines 243-253)
2. `_get_content_key` iterates 25 Korean particles with sequential `str.replace` (lines 260-300)
3. `flush_access_updates` updates metadata one-by-one in loop (lines 592-598)
4. `get_stats` loads ALL metadata just to count types (lines 658-667)

## Current Code
```python
# Lines 592-598: One-by-one update
for doc_id in ids_to_update:
    try:
        self._repository.update_metadata(doc_id, {"last_accessed": now})

# Lines 658-667: Full table load for stats
results = self._repository.get_all(include=["metadatas"])
type_counts = {}
for m in results.get("metadatas", []):
    t = m.get("type", "unknown")
    type_counts[t] = type_counts.get(t, 0) + 1

# Lines 260-300: 25 sequential str.replace
particles = ["은", "는", "이", "가", ...]
for p in particles:
    text = text.replace(p, "")
```

## Target Optimization
1. Lazy-load repetition cache or use dedicated lightweight query
2. Compile single regex from all particles: `re.compile("|".join(re.escape(p) for p in particles))`
3. Batch update: `collection.update(ids=[...], metadatas=[...])`
4. For PG: `SELECT memory_type, COUNT(*) FROM memories GROUP BY memory_type`

## Acceptance Criteria
- [ ] Batch access updates in single DB call
- [ ] Stats use GROUP BY query (PG) or cached counts
- [ ] Korean particles use single regex substitution
- [ ] Repetition cache loads only needed columns
- [ ] Existing tests pass (`python -m pytest tests/memory/test_facade.py`)
- [ ] ruff check passes

## Estimated Impact
Before: N DB calls per flush, full table scan for stats
After: 1 DB call per flush, single aggregate query
