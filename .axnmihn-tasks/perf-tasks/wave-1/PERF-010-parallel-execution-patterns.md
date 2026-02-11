# PERF-010: Parallelize independent async operations

## Metadata
| Field | Value |
|-------|-------|
| ID | PERF-010 |
| Severity | HIGH |
| File | backend/core/health/health_check.py, backend/core/tools/hass_ops.py, backend/core/services/tool_service.py |
| Lines | health_check.py:38-47, hass_ops.py:345-356, tool_service.py:143 |
| Wave | 1 |
| Depends On | (none) |
| Blocks | (none) |
| Test File | tests/core/test_health_check.py |

## Context
Three modules execute independent async operations sequentially:
1. Health checks run one-by-one (4 checks x 500ms = 2s)
2. Light control runs per-light sequentially (10 lights x 50ms = 500ms)
3. Deferred tools execute one at a time

## Current Code
```python
# health_check.py:38-47
for name, fn in self._checks.items():
    results[name] = await fn()

# hass_ops.py:345-356
for i, light_id in enumerate(lights):
    result = await hass_control_device(light_id, action, ...)
    await asyncio.sleep(0.05)

# tool_service.py:143
for call in deferred:
    result = await self._execute_single_tool(call, ...)
```

## Target Optimization
Use `asyncio.gather` for all three. Add semaphore for light control to limit concurrency.

## Acceptance Criteria
- [ ] Health checks run concurrently via `asyncio.gather`
- [ ] Light control uses gather with semaphore(5)
- [ ] Independent deferred tools run in parallel
- [ ] Results order preserved
- [ ] Existing tests pass
- [ ] ruff check passes

## Estimated Impact
Before: Wall-clock = sum of all operations
After: Wall-clock = max of all operations
