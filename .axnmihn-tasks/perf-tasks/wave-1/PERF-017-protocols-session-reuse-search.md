# PERF-017: Reuse aiohttp session in search engines

## Metadata
| Field | Value |
|-------|-------|
| ID | PERF-017 |
| Severity | HIGH |
| File | backend/protocols/mcp/research/search_engines.py |
| Lines | 73-74, 89-93, 75 |
| Wave | 1 |
| Depends On | (none) |
| Blocks | (none) |
| Test File | (none) |

## Context
New `aiohttp.ClientSession` created per search request. Also `import urllib.parse` inside loop, and deprecated bare int timeout.

## Current Code
```python
# Line 73-74
async with aiohttp.ClientSession() as session:
    async with session.get(search_url, headers=headers, timeout=15) as response:

# Line 89-93 (inside loop)
import urllib.parse
```

## Target Optimization
Accept or create reusable session. Move imports to module level. Use `aiohttp.ClientTimeout`.

## Acceptance Criteria
- [ ] Session reused across search calls
- [ ] No imports inside loops
- [ ] Proper ClientTimeout usage
- [ ] ruff check passes

## Estimated Impact
Before: New TCP+TLS per search
After: Reused connection
