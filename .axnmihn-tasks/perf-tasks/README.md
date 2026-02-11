# Performance Optimization Tasks

**Generated**: 2026-02-10
**Analysis scope**: Full project (`backend/`)
**Total issues**: 116 (CRITICAL 8, HIGH 35, MEDIUM 46, LOW 27)
**Consolidated into**: 43 PERF IDs across 25 task files

## Summary

| Severity | Count | Key Themes |
|----------|-------|------------|
| CRITICAL | 8 | Session-per-request, sync blocking in async, excessive flushing, double embedding, GraphRAG re-instantiation |
| HIGH | 35 | N+1 DB patterns, O(n^2) algorithms, regex recompilation, sequential I/O, missing batch operations |
| MEDIUM | 46 | Redundant computation, missing caching, unnecessary copies, import overhead |
| LOW | 27 | Minor polish, dead code, startup optimization |

## Dependency Graph

```
Wave 1 (18 tasks — max parallel)
  ├── PERF-001  Session reuse: mcp_client
  ├── PERF-002  Session reuse: error_monitor
  ├── PERF-003  Log flush optimization
  ├── PERF-004  Async emotion classification
  ├── PERF-005  Double embedding elimination ──────┐
  ├── PERF-006  GraphRAG instantiation fix          │
  ├── PERF-007  MemGPT batch operations             │
  ├── PERF-008  GraphRAG O(n²) algorithms ─────────┼──┐
  ├── PERF-009  Regex pre-compilation               │  │
  ├── PERF-010  Parallel execution patterns         │  │
  ├── PERF-011  Wake conversation session reuse     │  │
  ├── PERF-012  Sync I/O in async (multi-file)      │  │
  ├── PERF-013  Link pipeline HTTP pool             │  │
  ├── PERF-014  OpenAI string concat + list→set ───┼──┼──┐
  ├── PERF-015  Media upload I/O removal            │  │  │
  ├── PERF-016  DOM traversal optimization          │  │  │
  ├── PERF-017  Search engine session reuse         │  │  │
  └── PERF-018  Async research I/O fix              │  │  │
                                                    │  │  │
Wave 2 (12 tasks — after Wave 1)                    │  │  │
  ├── PERF-019/020  Facade batch ops ───────────────┘  │  │
  ├── PERF-021/022  Consolidator batch ────────────────┘  │
  ├── PERF-023/024  Recent repo batch inserts             │
  ├── PERF-025/026  PG repo batch + SELECT optimization   │
  ├── PERF-027      Embedding service LRU + sleep fix     │
  ├── PERF-028      Unified memory optimization           │
  ├── PERF-029/030  Current memory copy elimination       │
  ├── PERF-031      Memory server timestamp parsing       │
  ├── PERF-032      MCP server caching + parallel search  │
  ├── PERF-033/034  API layer caching ────────────────────┘
  ├── PERF-035/036  Core module caching
  └── PERF-037/038  App startup + shutdown

Wave 3 (3 tasks — after Wave 2)
  ├── PERF-039/040/041  Low-priority bundle
  ├── PERF-042          GraphRAG I/O + query optimization
  └── PERF-043          Protocol layer misc

Wave 4 (1 task — final)
  └── INTEGRATION-VERIFY  Full verification suite
```

## File Conflict Bundles

Issues sharing the same file are bundled to prevent merge conflicts:

| Bundle | File | Issues |
|--------|------|--------|
| PERF-005 + PERF-019/020 | `facade.py` | Double embedding + batch ops + stats |
| PERF-007 | `memgpt.py` | Full table load + one-by-one delete + sync LLM |
| PERF-008 + PERF-042 | `graph_rag.py` | Algorithms (W1) + I/O (W3) |
| PERF-014 | `openai.py` | String concat + list→set |
| PERF-023/024 | `recent/repository.py` | Batch insert + redundant sort + stats |
| PERF-025/026 | `pg/session_repository.py + pg/memory_repository.py` | Batch + SELECT * |
| PERF-033/034 | `status.py + deps.py + memory.py` | Caching + key check |
| PERF-035/036 | `ai_brain.py + token_counter.py + interaction_log.py` | Caching bundle |
| PERF-037/038 | `app.py` | Startup + shutdown |

## Wave Execution Plan

| Wave | Tasks | Agent Slots | Est. Time |
|------|-------|-------------|-----------|
| 1 | 18 | 18 parallel | ~30 min |
| 2 | 12 | 12 parallel | ~20 min |
| 3 | 3 | 3 parallel | ~15 min |
| 4 | 1 | 1 sequential | ~10 min |

## Task File Index

### Wave 1 — CRITICAL + HIGH (No Dependencies)
- [`PERF-001`](wave-1/PERF-001-session-reuse-mcp-client.md) — Session reuse: mcp_client
- [`PERF-002`](wave-1/PERF-002-session-reuse-error-monitor.md) — Session reuse: error_monitor
- [`PERF-003`](wave-1/PERF-003-log-flush-optimization.md) — Log flush optimization
- [`PERF-004`](wave-1/PERF-004-async-emotion-classification.md) — Async emotion classification
- [`PERF-005`](wave-1/PERF-005-double-embedding-facade.md) — Double embedding elimination
- [`PERF-006`](wave-1/PERF-006-graphrag-instantiation-decay.md) — GraphRAG instantiation fix
- [`PERF-007`](wave-1/PERF-007-memgpt-batch-operations.md) — MemGPT batch operations
- [`PERF-008`](wave-1/PERF-008-graph-rag-algorithms.md) — GraphRAG O(n^2) algorithms
- [`PERF-009`](wave-1/PERF-009-regex-precompilation.md) — Regex pre-compilation
- [`PERF-010`](wave-1/PERF-010-parallel-execution-patterns.md) — Parallel execution patterns
- [`PERF-011`](wave-1/PERF-011-session-reuse-conversation.md) — Wake conversation fixes
- [`PERF-012`](wave-1/PERF-012-sync-io-in-async-bundle.md) — Sync I/O in async bundle
- [`PERF-013`](wave-1/PERF-013-link-pipeline-http-pool.md) — Link pipeline HTTP pool
- [`PERF-014`](wave-1/PERF-014-openai-string-concat.md) — OpenAI string concat + list→set
- [`PERF-015`](wave-1/PERF-015-media-upload-io.md) — Media upload I/O removal
- [`PERF-016`](wave-1/PERF-016-protocols-html-dom-traversal.md) — DOM traversal optimization
- [`PERF-017`](wave-1/PERF-017-protocols-session-reuse-search.md) — Search engine session reuse
- [`PERF-018`](wave-1/PERF-018-protocols-async-research-io.md) — Async research I/O fix

### Wave 2 — MEDIUM/HIGH (Depends on Wave 1)
- [`PERF-019/020`](wave-2/PERF-019-020-facade-batch-ops.md) — Facade batch operations
- [`PERF-021/022`](wave-2/PERF-021-022-consolidator-batch.md) — Consolidator batch updates
- [`PERF-023/024`](wave-2/PERF-023-024-recent-repo-batch.md) — Recent repo batch inserts
- [`PERF-025/026`](wave-2/PERF-025-026-pg-repo-batch.md) — PG repo batch + optimization
- [`PERF-027`](wave-2/PERF-027-embedding-service-fixes.md) — Embedding service fixes
- [`PERF-028`](wave-2/PERF-028-unified-memory-optimization.md) — Unified memory optimization
- [`PERF-029/030`](wave-2/PERF-029-030-current-memory-copies.md) — Current memory copies
- [`PERF-031`](wave-2/PERF-031-memory-server-timestamp.md) — Memory server timestamps
- [`PERF-032`](wave-2/PERF-032-mcp-server-caching.md) — MCP server caching
- [`PERF-033/034`](wave-2/PERF-033-034-api-caching-optimization.md) — API layer caching
- [`PERF-035/036`](wave-2/PERF-035-036-core-caching.md) — Core module caching
- [`PERF-037/038`](wave-2/PERF-037-038-app-startup.md) — App startup optimization

### Wave 3 — LOW + Dependent MEDIUM
- [`PERF-039/040/041`](wave-3/PERF-039-040-041-low-priority-bundle.md) — Low-priority bundle
- [`PERF-042`](wave-3/PERF-042-graph-rag-io.md) — GraphRAG I/O optimization
- [`PERF-043`](wave-3/PERF-043-protocols-misc.md) — Protocol layer misc

### Wave 4 — Integration
- [`INTEGRATION-VERIFY`](wave-4/INTEGRATION-VERIFY.md) — Full verification suite

## Execution Instructions

```bash
# Wave 1: Maximum parallelism — all 18 tasks can run simultaneously
# Each task is self-contained with its own acceptance criteria

# Wave 2: Start after ALL Wave 1 tasks complete
# 12 tasks can run in parallel within this wave

# Wave 3: Start after ALL Wave 2 tasks complete
# 3 tasks can run in parallel

# Wave 4: Integration verification — must run last
python -m pytest --tb=short -q
ruff check backend/
mypy backend/ --ignore-missing-imports
```
