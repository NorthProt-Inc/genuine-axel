# PERF-001: Reuse aiohttp session in MCP client

## Metadata
| Field | Value |
|-------|-------|
| ID | PERF-001 |
| Severity | CRITICAL |
| File | backend/core/mcp_client.py |
| Lines | 102 |
| Wave | 1 |
| Depends On | (none) |
| Blocks | (none) |
| Test File | tests/core/test_mcp_client.py |

## Context
Every MCP tool call via HTTP creates a new `aiohttp.ClientSession`. Session creation involves TCP+TLS setup. Multiple tool calls per conversation add hundreds of ms latency and prevent connection reuse.

## Current Code
```python
# backend/core/mcp_client.py:102
async with aiohttp.ClientSession() as session:
    async with session.post(url, json=payload, timeout=timeout) as resp:
```

## Target Optimization
Create a persistent `aiohttp.ClientSession` as instance attribute, reuse across calls. Close in shutdown.

## Acceptance Criteria
- [ ] Single ClientSession reused across all HTTP calls
- [ ] Session closed cleanly on shutdown
- [ ] Existing tests pass (`python -m pytest tests/core/test_mcp_client.py`)
- [ ] ruff check passes
- [ ] mypy check passes

## Estimated Impact
Before: ~200-500ms TCP+TLS overhead per tool call
After: ~0ms (connection reused via keep-alive)
