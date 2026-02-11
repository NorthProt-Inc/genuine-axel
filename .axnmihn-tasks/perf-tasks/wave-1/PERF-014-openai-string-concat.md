# PERF-014: Fix O(n^2) string concatenation in OpenAI endpoint

## Metadata
| Field | Value |
|-------|-------|
| ID | PERF-014 |
| Severity | CRITICAL |
| File | backend/api/openai.py |
| Lines | 293-297, 330-333 |
| Wave | 1 |
| Depends On | (none) |
| Blocks | (none) |
| Test File | tests/api/test_openai.py |

## Context
Two issues:
1. O(n^2) string concatenation via `+=` in streaming loop (line 293-297)
2. `active_streams` is a list causing O(n) membership test and removal (lines 330-333)

## Current Code
```python
# Line 293-297: O(n^2) string concat
full_response = ""
async for event in handler.process(request):
    if event.type == EventType.TEXT:
        full_response += event.content

# Line 330-333: O(n) list operations
if stream_id in state.active_streams:       # O(n)
    state.active_streams.remove(stream_id)  # O(n)
```

## Target Optimization
1. Use `list.append()` + `"".join()` pattern
2. Change `active_streams` from `list` to `set` in AppState

## Acceptance Criteria
- [ ] String building uses list+join pattern
- [ ] `active_streams` is a set with O(1) add/discard
- [ ] Existing tests pass
- [ ] ruff check passes

## Estimated Impact
Before: O(n^2) for long responses, O(n) per stream operation
After: O(n) string building, O(1) stream operations
