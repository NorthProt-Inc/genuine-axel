# PERF-035/036: Core module caching (brain, counter, telemetry)

## Metadata
| Field | Value |
|-------|-------|
| ID | PERF-035, PERF-036 |
| Severity | MEDIUM |
| File | backend/core/identity/ai_brain.py, backend/core/context/token_counter.py, backend/core/telemetry/interaction_log.py, backend/core/services/context_service.py |
| Lines | ai_brain:153-161,176-247; token_counter:28; interaction_log:87; context_service:291,401 |
| Wave | 2 |
| Depends On | (none) |
| Blocks | (none) |
| Test File | tests/core/ |

## Context
1. O(n) insight dedup with substring matching (ai_brain:153-161)
2. System prompt rebuilt every call despite rare changes (ai_brain:176-247)
3. SHA-256 for simple cache key — overkill (token_counter:28)
4. PRAGMA query on every interaction log read (interaction_log:87)
5. Duplicate `parse_temporal_query` calls (context_service:291,401)

## Target Optimization
1. Consider normalized hash set for insight dedup
2. Cache system prompt with dirty flag
3. Use `hash()` instead of SHA-256 for cache key
4. Cache column names after first query
5. Parse temporal query once, pass to both sub-methods

## Acceptance Criteria
- [ ] System prompt cached with invalidation
- [ ] Faster cache key generation
- [ ] Column names cached
- [ ] Single temporal parse per request
- [ ] Existing tests pass
- [ ] ruff check passes

## Estimated Impact
Before: Redundant computation per request
After: Cached values reused
