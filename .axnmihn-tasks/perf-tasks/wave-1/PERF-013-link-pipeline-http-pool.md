# PERF-013: Use shared HTTP pool in link pipeline

## Metadata
| Field | Value |
|-------|-------|
| ID | PERF-013 |
| Severity | HIGH |
| File | backend/core/tools/link_pipeline.py |
| Lines | 72 |
| Wave | 1 |
| Depends On | (none) |
| Blocks | (none) |
| Test File | tests/core/test_link_pipeline.py |

## Context
Creates new `httpx.AsyncClient` per URL fetch despite `http_pool.py` existing with a shared pool.

## Current Code
```python
# backend/core/tools/link_pipeline.py:72
async with httpx.AsyncClient(timeout=15.0) as client:
    resp = await client.get(url, follow_redirects=True)
```

## Target Optimization
Import and use the shared HTTP pool from `http_pool.py`.

## Acceptance Criteria
- [ ] Uses shared HTTP pool
- [ ] Connection reuse verified
- [ ] Existing tests pass
- [ ] ruff check passes

## Estimated Impact
Before: New TCP connection per URL
After: Reused connection
