# PERF-031: Optimize timestamp parsing in MCP memory server

## Metadata
| Field | Value |
|-------|-------|
| ID | PERF-031 |
| Severity | MEDIUM |
| File | backend/protocols/mcp/memory_server.py |
| Lines | 97-115, 163-201, 205-206, 240 |
| Wave | 2 |
| Depends On | (none) |
| Blocks | (none) |
| Test File | tests/protocols/test_memory_server_functions.py |

## Context
1. Timestamps parsed twice per memory result (sort + format)
2. `_parse_timestamp` tries 4 strptime formats before fromisoformat (slow path first)
3. `from datetime import datetime, timezone` inside per-result functions (3-4N imports)
4. `_format_memory_age` defined but never used (dead code)

## Target Optimization
1. Parse once, store result, reuse in formatting
2. Try `fromisoformat` first (C-implemented fast path in Python 3.11+)
3. Move imports to top of file
4. Remove dead `_format_memory_age` function

## Acceptance Criteria
- [ ] Timestamps parsed once per result
- [ ] `fromisoformat` tried first
- [ ] All imports at module level
- [ ] Dead code removed
- [ ] Existing tests pass
- [ ] ruff check passes

## Estimated Impact
Before: Up to 100 strptime calls per 10 results, N redundant imports
After: ~10 fromisoformat calls, 0 in-function imports
