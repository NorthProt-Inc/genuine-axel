# PERF-012: Fix sync file I/O in async functions (multi-file bundle)

## Metadata
| Field | Value |
|-------|-------|
| ID | PERF-012 |
| Severity | HIGH |
| File | backend/core/mcp_tools/memory_tools.py, backend/core/research_artifacts.py, backend/core/tools/system_observer.py |
| Lines | memory_tools.py:17-18,104,120; research_artifacts.py:113-114,149,183-205; system_observer.py:453-518 |
| Wave | 1 |
| Depends On | (none) |
| Blocks | (none) |
| Test File | tests/core/ |

## Context
Three modules use synchronous file I/O in async functions:
1. `memory_tools._read_file_safe()` uses sync `path.read_text()` (line 17-18)
2. `research_artifacts.list_artifacts()` reads ENTIRE file content just for title (line 194)
3. `system_observer.search_codebase_regex()` uses sync `os.walk` + file reads (line 453+)

## Target Optimization
1. Wrap in `asyncio.to_thread()` or use `aiofiles`
2. Read only first line for title extraction
3. Match pattern from `search_codebase` which already uses `asyncio.to_thread`

## Acceptance Criteria
- [ ] All file I/O in async functions uses async patterns
- [ ] `list_artifacts` reads only first line for title
- [ ] Existing tests pass
- [ ] ruff check passes

## Estimated Impact
Before: Event loop blocked during file I/O
After: Non-blocking I/O
