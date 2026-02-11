# PERF-016: Optimize DOM traversal and HTML processing in protocols

## Metadata
| Field | Value |
|-------|-------|
| ID | PERF-016 |
| Severity | HIGH |
| File | backend/protocols/mcp/research/html_processor.py |
| Lines | 34-43, 38-44, 67-83 |
| Wave | 1 |
| Depends On | (none) |
| Blocks | (none) |
| Test File | (none) |

## Context
Three issues in HTML processor:
1. 47 full DOM traversals instead of 3 (lines 34-43): Each AD_PATTERN does 2 traversals (class + id)
2. 33 regex compilations per call (lines 38-44): `re.compile()` called for each pattern
3. `_Converter` class redefined per function call (lines 67-83): Class creation machinery on every call

## Target Optimization
1. Combine AD_PATTERNS into single regex, do 2 traversals total (class + id)
2. Pre-compile all regex patterns at module level
3. Move `_Converter` class to module scope, pass `base_url` via options

## Acceptance Criteria
- [ ] Maximum 3 DOM traversals per clean_html call
- [ ] All regex patterns pre-compiled at module level
- [ ] _Converter class defined once at module level
- [ ] Same HTML output quality
- [ ] ruff check passes

## Estimated Impact
Before: 47 DOM traversals, 33 regex compilations per page
After: 3 DOM traversals, 0 regex compilations
