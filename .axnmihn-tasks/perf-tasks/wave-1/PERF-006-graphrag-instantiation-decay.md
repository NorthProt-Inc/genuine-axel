# PERF-006: Stop re-instantiating GraphRAG in decay calculator

## Metadata
| Field | Value |
|-------|-------|
| ID | PERF-006 |
| Severity | CRITICAL |
| File | backend/memory/permanent/decay_calculator.py |
| Lines | 62-76 |
| Wave | 1 |
| Depends On | (none) |
| Blocks | (none) |
| Test File | tests/memory/ |

## Context
`get_connection_count` creates a NEW `GraphRAG()` instance per call. `GraphRAG()` creates `KnowledgeGraph()` which loads the entire graph from JSON file. Called for EVERY memory during consolidation/eviction -- 500 memories = 500 JSON file loads.

## Current Code
```python
# backend/memory/permanent/decay_calculator.py:62-76
def get_connection_count(memory_id: str) -> int:
    try:
        from backend.memory.graph_rag import GraphRAG
        graph = GraphRAG()  # loads entire graph from JSON
        return graph.get_connection_count(memory_id)
    except ImportError:
        return 0
```

## Target Optimization
Accept a pre-built graph instance as parameter, or use a module-level singleton/cache. Callers already have access to the graph.

## Acceptance Criteria
- [ ] GraphRAG instantiated at most once per consolidation/eviction run
- [ ] Connection count still accurate
- [ ] Existing tests pass
- [ ] ruff check passes

## Estimated Impact
Before: 500 JSON loads per consolidation (~minutes)
After: 0-1 JSON loads per consolidation (~milliseconds)
