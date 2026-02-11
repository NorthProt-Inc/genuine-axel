# PERF-002: Reuse aiohttp session in error monitor

## Metadata
| Field | Value |
|-------|-------|
| ID | PERF-002 |
| Severity | CRITICAL |
| File | backend/core/logging/error_monitor.py |
| Lines | 104 |
| Wave | 1 |
| Depends On | (none) |
| Blocks | (none) |
| Test File | tests/core/test_error_monitor.py |

## Context
Each Discord alert creates a new `aiohttp.ClientSession`. During error cascades multiple alerts fire rapidly, each with full TCP+TLS overhead.

## Current Code
```python
# backend/core/logging/error_monitor.py:104
async with aiohttp.ClientSession() as session:
    async with session.post(self._discord_webhook, json=message) as resp:
```

## Target Optimization
Store a shared `aiohttp.ClientSession` as instance attribute, created lazily on first use, closed on shutdown.

## Acceptance Criteria
- [ ] Single ClientSession reused across all alerts
- [ ] Lazy initialization (no session until first alert)
- [ ] Session closed cleanly on shutdown
- [ ] Existing tests pass (`python -m pytest tests/core/test_error_monitor.py`)
- [ ] ruff check passes

## Estimated Impact
Before: ~200-500ms per alert during cascades
After: ~0ms (reused connection)
