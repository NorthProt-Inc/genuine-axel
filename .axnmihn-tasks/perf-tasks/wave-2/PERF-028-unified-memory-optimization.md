# PERF-028: Optimize unified memory query and session end

## Metadata
| Field | Value |
|-------|-------|
| ID | PERF-028 |
| Severity | HIGH + MEDIUM |
| File | backend/memory/unified.py |
| Lines | 147-149, 485-499, 605-611 |
| Wave | 2 |
| Depends On | (none) |
| Blocks | (none) |
| Test File | tests/memory/test_unified.py |

## Context
1. LOG_PATTERNS check scans 14 patterns via substring for every message (lines 147-149)
2. Sequential LLM calls for facts/insights in `end_session` (lines 485-499)
3. `query` copies working memory messages via property (lines 605-611)

## Current Code
```python
# Lines 147-149: 14 substring scans per message
if any(pattern in content for pattern in self.LOG_PATTERNS):
    return None

# Lines 485-499: Sequential add per fact/insight
for fact in summary_result.get("facts_discovered", []):
    self.long_term.add(content=fact, ...)
```

## Target Optimization
1. Compile single regex from LOG_PATTERNS at init
2. Batch embedding generation for facts+insights
3. Cache `query_lower` and access messages once

## Acceptance Criteria
- [ ] Single regex check instead of 14 substring scans
- [ ] Batch or parallel fact/insight storage
- [ ] Query method doesn't redundantly copy messages
- [ ] Existing tests pass (`python -m pytest tests/memory/test_unified.py`)
- [ ] ruff check passes

## Estimated Impact
Before: O(14 * len(content)) per message, ~20 sequential API calls
After: Single regex match, parallel/batch storage
