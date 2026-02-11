# PERF-004: Async emotion classification in memory persistence

## Metadata
| Field | Value |
|-------|-------|
| ID | PERF-004 |
| Severity | CRITICAL |
| File | backend/core/services/memory_persistence_service.py |
| Lines | 168 |
| Wave | 1 |
| Depends On | (none) |
| Blocks | (none) |
| Test File | tests/services/ |

## Context
`classify_emotion_sync` makes a synchronous Gemini API call from async context, blocking the entire event loop for 200-2000ms. All concurrent requests stall.

## Current Code
```python
# backend/core/services/memory_persistence_service.py:168
def add_assistant_message(self, response: str) -> None:
    if response and self.memory_manager:
        emotion = classify_emotion_sync(response)  # sync Gemini API call
        self.memory_manager.add_message("assistant", response, emotional_context=emotion)
```

## Target Optimization
Use `await asyncio.to_thread(classify_emotion_sync, response)` or create an async variant using the async Gemini client.

## Acceptance Criteria
- [ ] Emotion classification no longer blocks event loop
- [ ] Same classification quality maintained
- [ ] Existing tests pass
- [ ] ruff check passes

## Estimated Impact
Before: Event loop blocked 200-2000ms per assistant message
After: 0ms event loop blocking (offloaded to thread)
