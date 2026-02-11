# PERF-015: Remove pointless file I/O in media upload

## Metadata
| Field | Value |
|-------|-------|
| ID | PERF-015 |
| Severity | HIGH |
| File | backend/api/media.py |
| Lines | 60-89 |
| Wave | 1 |
| Depends On | (none) |
| Blocks | (none) |
| Test File | tests/api/test_media.py |

## Context
Upload handler writes file to /tmp, never reads it back, then immediately deletes it. Completely wasted I/O. Also, `os.remove()` is synchronous in async context.

## Current Code
```python
# Lines 60-89
async with aiofiles.open(file_path, "wb") as buffer:  # write to disk
    await buffer.write(content)
# ... build result from content (not from file) ...
try:
    os.remove(file_path)   # immediately delete (sync!)
```

## Target Optimization
Remove entire file write/delete block. Process from in-memory `content` directly.

## Acceptance Criteria
- [ ] No temporary file created for uploads
- [ ] Same upload functionality maintained
- [ ] Existing tests pass
- [ ] ruff check passes

## Estimated Impact
Before: 2 unnecessary disk I/O operations per upload
After: 0 disk I/O operations
