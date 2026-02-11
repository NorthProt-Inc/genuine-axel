# PERF-032: Cache manifest and parallelize search in MCP server

## Metadata
| Field | Value |
|-------|-------|
| ID | PERF-032 |
| Severity | MEDIUM |
| File | backend/protocols/mcp/server.py |
| Lines | 230-231, 389-401, 452-481 |
| Wave | 2 |
| Depends On | (none) |
| Blocks | (none) |
| Test File | tests/core/test_mcp_server.py |

## Context
1. `import time` inside `handle_request` hot path (line 230)
2. Sequential web+memory search when source is "both" (lines 389-401)
3. `get_manifest()` rebuilds full dict from scratch every call (lines 452-481)

## Target Optimization
1. Move `import time` to module level
2. Use `asyncio.gather` for parallel web+memory search
3. Cache manifest, invalidate on register

## Acceptance Criteria
- [ ] No imports inside hot-path functions
- [ ] Parallel search via gather
- [ ] Manifest cached after setup
- [ ] Existing tests pass
- [ ] ruff check passes

## Estimated Impact
Before: Sequential searches, dict rebuild per call
After: Parallel searches, cached manifest
