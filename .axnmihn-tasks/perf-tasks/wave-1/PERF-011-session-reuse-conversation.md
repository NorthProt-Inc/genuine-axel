# PERF-011: Reuse httpx client in wake conversation handler

## Metadata
| Field | Value |
|-------|-------|
| ID | PERF-011 |
| Severity | HIGH |
| File | backend/wake/conversation.py |
| Lines | 56, 96-145, 149, 169, 198 |
| Wave | 1 |
| Depends On | (none) |
| Blocks | (none) |
| Test File | (none) |

## Context
Multiple performance issues in conversation handler:
1. Sync blocking `_record_until_silence()` called from async (line 56) -- blocks event loop up to 20s
2. New `httpx.AsyncClient` per HTTP call (lines 149, 169, 198) -- 5-sentence response = 5 TCP connections
3. Sync file I/O in async functions (lines 150, 258-259)
4. O(n^2) amplitude computation with pure Python byte parsing (lines 117-118)

## Target Optimization
1. `await asyncio.to_thread(self._record_until_silence)` for async offloading
2. Single `httpx.AsyncClient` as instance attribute
3. Use `aiofiles` or `asyncio.to_thread` for file I/O
4. Use `numpy.frombuffer` for amplitude computation

## Acceptance Criteria
- [ ] Recording doesn't block event loop
- [ ] Single httpx client reused across all HTTP calls
- [ ] File I/O is async
- [ ] Amplitude uses numpy
- [ ] ruff check passes

## Estimated Impact
Before: 20s event loop blocking, 5 TCP connections per response
After: 0ms blocking, 1 persistent connection
