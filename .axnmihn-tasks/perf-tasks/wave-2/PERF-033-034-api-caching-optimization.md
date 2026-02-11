# PERF-033/034: API layer caching and optimization

## Metadata
| Field | Value |
|-------|-------|
| ID | PERF-033, PERF-034 |
| Severity | MEDIUM |
| File | backend/api/status.py, backend/api/deps.py, backend/api/memory.py |
| Lines | status:30,93,167-175; deps:220-241; memory:32-44,144-188 |
| Wave | 2 |
| Depends On | PERF-014 |
| Blocks | (none) |
| Test File | tests/api/ |

## Context
1. `get_all_providers()` calls `os.getenv` on every invocation — cacheable (status.py)
2. `require_api_key` extracts API key twice on failure (deps.py:220-241)
3. `_evolve_persona_from_memories` fetches 30 but uses only 20 (memory.py:32-44)
4. Sequential search + linear session scan in search endpoint (memory.py:144-188)
5. Excessive debug logging with eager evaluation on every request (deps.py)

## Target Optimization
1. Cache `get_all_providers()` result (static after startup)
2. Extract key once, check directly
3. Change `limit=30` to `limit=20`
4. Parallelize search + cache `query.lower()`
5. Guard debug logs with level check

## Acceptance Criteria
- [ ] Provider list cached
- [ ] API key checked without redundant extraction
- [ ] Correct fetch limit
- [ ] Parallel memory search
- [ ] Debug logging guarded
- [ ] Existing tests pass
- [ ] ruff check passes

## Estimated Impact
Before: Redundant env lookups, double key extraction per request
After: Cached values, single key check
