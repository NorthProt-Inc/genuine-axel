# PERF-029/030: Eliminate redundant copies in current memory

## Metadata
| Field | Value |
|-------|-------|
| ID | PERF-029, PERF-030 |
| Severity | HIGH + MEDIUM |
| File | backend/memory/current.py (or backend/memory/recent/__init__.py) |
| Lines | 83-87, 168-170 |
| Wave | 2 |
| Depends On | (none) |
| Blocks | (none) |
| Test File | tests/memory/test_current.py |

## Context
1. `.messages` property copies entire deque on every access (lines 83-87) — called multiple times per request
2. `get_turn_count` calls `.messages` (full copy) just to count (lines 168-170)

## Current Code
```python
# Lines 83-87: Full copy every access
@property
def messages(self) -> List[TimestampedMessage]:
    with self._lock:
        return list(self._messages)

# Lines 168-170: Copy just to count
def get_turn_count(self) -> int:
    return len(self.messages) // 2
```

## Target Optimization
1. For `get_turn_count`: `with self._lock: return len(self._messages) // 2`
2. Consider caching message snapshot or using read-only view

## Acceptance Criteria
- [ ] `get_turn_count` doesn't copy entire deque
- [ ] Thread safety maintained
- [ ] Existing tests pass
- [ ] ruff check passes

## Estimated Impact
Before: Multiple full deque copies per request
After: Direct length check, minimal copies
