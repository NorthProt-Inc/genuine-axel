# PERF-023/024: Batch inserts and remove redundant sort in recent repository

## Metadata
| Field | Value |
|-------|-------|
| ID | PERF-023, PERF-024 |
| Severity | HIGH + MEDIUM |
| File | backend/memory/recent/repository.py |
| Lines | 84-97, 282-284, 344-358, 452-465 |
| Wave | 2 |
| Depends On | (none) |
| Blocks | (none) |
| Test File | tests/memory/ |

## Context
1. `save_session` inserts messages one-by-one (lines 84-97) — use executemany
2. `get_recent_summaries` re-sorts already-sorted DB data (lines 282-284)
3. `get_stats` makes 3 separate queries for counts (lines 344-358)
4. `archive_session` inserts messages one-by-one (lines 452-465)

## Target Optimization
1. Use `executemany()` for batch inserts
2. Remove redundant Python-side sort
3. Combine 3 count queries into single query
4. Use `executemany()` for archive inserts

## Acceptance Criteria
- [ ] All message inserts use `executemany()`
- [ ] Redundant sort removed
- [ ] Stats query combined into single SQL statement
- [ ] Existing tests pass
- [ ] ruff check passes

## Estimated Impact
Before: 100 INSERT calls per session save
After: 1 executemany call
