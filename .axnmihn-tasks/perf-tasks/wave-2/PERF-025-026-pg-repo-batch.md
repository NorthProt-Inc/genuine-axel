# PERF-025/026: Batch inserts and optimize PG repositories

## Metadata
| Field | Value |
|-------|-------|
| ID | PERF-025, PERF-026 |
| Severity | HIGH |
| File | backend/memory/pg/session_repository.py, backend/memory/pg/memory_repository.py |
| Lines | session_repo:84-98,331-373,397-411; memory_repo:73-76,128-136 |
| Wave | 2 |
| Depends On | (none) |
| Blocks | (none) |
| Test File | tests/memory/pg/ |

## Context
PG-specific issues:
1. `save_session` inserts messages one-by-one (lines 84-98) — use execute_batch
2. `get_interaction_stats` makes 4 separate queries (lines 331-373)
3. `archive_session` inserts one-by-one (lines 397-411)
4. `get_all` fetches `SELECT *` including 24KB embedding vectors (memory_repo:73-76)
5. `query_by_embedding` sends embedding string twice (memory_repo:128-136)

## Target Optimization
1. Use `psycopg2.extras.execute_batch()` or `execute_values()`
2. Combine stats queries with CTEs
3. Build column list dynamically (exclude embedding when not needed)
4. Use CTE for query embedding: `WITH q AS (SELECT %s::halfvec AS qvec)`

## Acceptance Criteria
- [ ] Batch inserts using execute_batch/execute_values
- [ ] Stats in single query
- [ ] No SELECT * when embeddings not needed
- [ ] Embedding sent once via CTE
- [ ] Existing tests pass
- [ ] ruff check passes

## Estimated Impact
Before: N network round-trips per save, 24KB wasted per row in get_all
After: 1 round-trip, only needed columns fetched
