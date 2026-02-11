# PERF-037/038: App startup optimization and shutdown improvement

## Metadata
| Field | Value |
|-------|-------|
| ID | PERF-037, PERF-038 |
| Severity | MEDIUM |
| File | backend/app.py |
| Lines | 92, 143-146, 249-252, 278, 280-288 |
| Wave | 2 |
| Depends On | (none) |
| Blocks | (none) |
| Test File | tests/test_app.py |

## Context
1. `ensure_data_directories()` called at module import AND in lifespan (double call)
2. `IdentityManager` created at import time (eager loading)
3. Shutdown uses fixed sleep instead of event-based waiting (lines 143-146)
4. Global exception handler imports `traceback` lazily (line 249)

## Target Optimization
1. Move `ensure_data_directories()` inside lifespan only
2. Move `IdentityManager` creation into lifespan
3. Use event-based shutdown with timeout
4. Move `import traceback` to module level

## Acceptance Criteria
- [ ] No duplicate directory creation
- [ ] IdentityManager created in lifespan
- [ ] Event-based graceful shutdown
- [ ] Top-level traceback import
- [ ] Existing tests pass
- [ ] ruff check passes

## Estimated Impact
Before: Slow imports, duplicate init, sleep-based shutdown
After: Fast imports, single init, responsive shutdown
