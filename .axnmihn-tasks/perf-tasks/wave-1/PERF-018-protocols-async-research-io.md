# PERF-018: Fix sync I/O and race conditions in async research

## Metadata
| Field | Value |
|-------|-------|
| ID | PERF-018 |
| Severity | HIGH |
| File | backend/protocols/mcp/async_research.py |
| Lines | 158, 179-207 |
| Wave | 1 |
| Depends On | (none) |
| Blocks | (none) |
| Test File | (none) |

## Context
Two issues:
1. Sync file I/O (`Path.write_text`, `Path.read_text`) in async functions blocks event loop
2. `_append_to_research_log` reads entire log file on every append to check for headers -- race condition with concurrent research tasks

## Target Optimization
1. Use `asyncio.to_thread` or `aiofiles` for all file I/O
2. Initialize header once at startup, only append thereafter

## Acceptance Criteria
- [ ] All file I/O uses async patterns
- [ ] Log header initialized once, not checked per-append
- [ ] No race conditions on concurrent appends
- [ ] ruff check passes

## Estimated Impact
Before: Event loop blocked during file I/O, redundant reads
After: Non-blocking, single-write appends
