# PERF-043: Miscellaneous protocol layer optimizations

## Metadata
| Field | Value |
|-------|-------|
| ID | PERF-043 |
| Severity | MEDIUM |
| File | backend/protocols/mcp/memory_server.py, backend/protocols/mcp/research/browser.py, backend/protocols/mcp/research/page_visitor.py |
| Lines | memory_server:12-21,132-133; browser:26; page_visitor:125-193 |
| Wave | 3 |
| Depends On | PERF-031, PERF-032 |
| Blocks | INTEGRATION-VERIFY |

## Context
1. `_get_memory_components()` re-imports and re-fetches on every tool call (memory_server:12-21)
2. `import asyncio` inside function body (memory_server:132-133)
3. `BrowserManager._lock` created at class definition time (browser:26)
4. O(n²) string concatenation via `+=` in page visitor (page_visitor:125-193)

## Target Optimization
1. Cache memory components after first retrieval
2. Move all imports to module level
3. Move lock to `__init__`
4. Use list+join pattern for string building

## Acceptance Criteria
- [ ] Memory components cached
- [ ] All imports at top of file
- [ ] Lock created in __init__
- [ ] No O(n²) string concatenation
- [ ] Existing tests pass
- [ ] ruff check passes

## Estimated Impact
Before: Redundant lookups and imports per call
After: Cached values, clean code
