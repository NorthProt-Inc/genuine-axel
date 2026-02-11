# PERF-009: Pre-compile regex patterns across core modules

## Metadata
| Field | Value |
|-------|-------|
| ID | PERF-009 |
| Severity | HIGH |
| File | backend/core/context_optimizer.py, backend/core/security/prompt_defense.py |
| Lines | context_optimizer.py:207, prompt_defense.py:24-26 |
| Wave | 1 |
| Depends On | (none) |
| Blocks | (none) |
| Test File | tests/core/test_context_optimizer.py, tests/core/test_prompt_defense.py |

## Context
Two hot-path modules recompile regex patterns on every call:
1. `context_optimizer._split_turns()` -- imports `re` inside method, recompiles pattern each call
2. `prompt_defense.sanitize_input()` -- calls `re.sub` with string pattern per INJECTION_PATTERN

Both are called on every user message.

## Current Code
```python
# context_optimizer.py:207
def _split_turns(self, content: str) -> List[str]:
    import re
    pattern = r'(?=\[(?:User|Assistant|...)\]:|\[\d+[분시간일])'
    turns = re.split(pattern, content)

# prompt_defense.py:24-26
def sanitize_input(text: str) -> str:
    for pattern in INJECTION_PATTERNS:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)
```

## Target Optimization
Pre-compile all patterns at module level. Remove in-function imports.

## Acceptance Criteria
- [ ] All regex patterns compiled once at module level
- [ ] No `import re` inside functions
- [ ] Same sanitization/splitting behavior
- [ ] Existing tests pass
- [ ] ruff check passes

## Estimated Impact
Before: Multiple regex compilations per user message
After: Zero compilations at runtime
