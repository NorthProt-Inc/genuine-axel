# PERF-039/040/041: Low-priority optimizations bundle

## Metadata
| Field | Value |
|-------|-------|
| ID | PERF-039, PERF-040, PERF-041 |
| Severity | LOW |
| File | Multiple files |
| Wave | 3 |
| Depends On | Wave 1 + Wave 2 |
| Blocks | INTEGRATION-VERIFY |

## Issues

### PERF-039: Minor inefficiencies in memory subsystem
- `meta_memory.py:65` — `_patterns` list grows unbounded; use bounded `deque(maxlen=10000)`
- `event_buffer.py:68` — `get_recent` copies entire buffer then slices; use deque indexing
- `permanent/__init__.py:66-83` — `apply_adaptive_decay` creates new calculator per call; use module singleton
- `pg/interaction_logger.py:69-76` — `_resolve_session_id` does DB query per log; cache known IDs in set
- `permanent/migrator.py:97-136` — `migrate()` fetches data twice (analyze + migrate); reuse from analyze

### PERF-040: Minor inefficiencies in core modules
- `utils/path_validator.py:65-66` — Double-slash removal via while loop; use `re.sub(r'/+', '/')`
- `utils/file_utils.py:62` — Sequential directory cleanup at startup; use `asyncio.gather`
- `utils/opus_shared.py:127` — UTF-8 encode for size check; use `len(content) * 4` as upper bound
- `core/mcp_client.py:25-40` — CORE_TOOLS is list; change to `frozenset`
- `utils/pdf.py:61` — Double base64 decode for logging; use `len(data) * 3 // 4`

### PERF-041: Minor inefficiencies in API/protocols layer
- `config.py` — 60+ os.getenv at import time (one-time cost, LOW impact)
- `wake/detector.py:53` — Redundant numpy import inside reset method
- `wake/list_mics.py:9-12` — Redundant device info lookups (call twice per device)
- `wake/run_wake.py:20-27` — New event loop per wakeword detection
- `wake/player.py:33-37` — `capture_output=True` but output never used
- `app.py:249-252` — `import traceback` inside exception handler
- `protocols/mcp/research_server.py:44-222` — Tool schema objects rebuilt per list_tools call
- `protocols/mcp/server.py:236-326` — if/elif dispatch chain; consider dict dispatch
- `protocols/mcp/multiple files` — Repeated `sys.path.insert(0, ...)` without dedup check
- `memory/recent/interaction_logger.py:49-53` — Hedge phrase check without regex; compile single pattern

## Acceptance Criteria
- [ ] All LOW issues addressed or documented as "won't fix" with rationale
- [ ] No regressions in existing tests
- [ ] ruff check passes
- [ ] mypy check passes

## Estimated Impact
Individual items: <10ms each
Cumulative: Minor startup and per-request improvements
