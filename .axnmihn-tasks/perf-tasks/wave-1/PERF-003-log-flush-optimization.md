# PERF-003: Remove per-message handler flush in logger

## Metadata
| Field | Value |
|-------|-------|
| ID | PERF-003 |
| Severity | CRITICAL |
| File | backend/core/logging/logging.py |
| Lines | 423-424 |
| Wave | 1 |
| Depends On | (none) |
| Blocks | (none) |
| Test File | tests/core/test_logging.py |

## Context
Every log message triggers a flush on ALL handlers. A conversation turn logging 50+ messages causes 50+ system calls. File handler flush is particularly expensive as it forces disk I/O.

## Current Code
```python
# backend/core/logging/logging.py:423-424
self._logger.handle(record)
for h in self._logger.handlers:
    h.flush()
```

## Target Optimization
Remove per-message flush. Flush only for WARNING/ERROR and above, or rely on Python's default buffered logging.

## Acceptance Criteria
- [ ] No flush on DEBUG/INFO level messages
- [ ] WARNING/ERROR/CRITICAL still flush
- [ ] Existing tests pass (`python -m pytest tests/core/test_logging.py`)
- [ ] ruff check passes

## Estimated Impact
Before: ~50 system calls per conversation turn
After: ~2-5 system calls (only on warnings/errors)
