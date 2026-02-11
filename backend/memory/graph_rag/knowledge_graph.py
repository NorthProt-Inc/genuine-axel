"""Knowledge graph data structures and operations."""

import json
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Any

from backend.config import KNOWLEDGE_GRAPH_PATH
from backend.core.utils.timezone import now_vancouver

from .utils import (
    _log,
    aiofiles,
    _HAS_NATIVE_GRAPH,
    _native,
    _NATIVE_BFS_THRESHOLD,
    ENTITY_STOPWORDS,
)


@dataclass
class Entity:

    id: str
    name: str
    entity_type: str
    properties: Dict[str, Any] = field(default_factory=dict)
    mentions: int = 1
    created_at: str = ""
    last_accessed: str = ""

    def __hash__(self):
        return hash(self.id)

@dataclass
class Relation:

    source_id: str
    target_id: str
    relation_type: str
    weight: float = 1.0
    context: str = ""
    created_at: str = ""

    @property
    def id(self) -> str:
        return f"{self.source_id}--{self.relation_type}-->{self.target_id}"

@dataclass
class GraphQueryResult:

    entities: List[Entity]
    relations: List[Relation]
    paths: List[List[str]]
    context: str
    relevance_score: float

class KnowledgeGraph:

    def __init__(self, persist_path: Optional[str] = None, pg_repository=None):
        self._pg = pg_repository
        self.entities: Dict[str, Entity] = {}
        self.relations: Dict[str, Relation] = {}
        self.adjacency: Dict[str, Set[str]] = defaultdict(set)
        self.persist_path = persist_path if persist_path else str(KNOWLEDGE_GRAPH_PATH)

        # PERF-008: O(1) name→entity_id index for dedup
        self._name_index: Dict[str, str] = {}  # normalized_lower_name → entity_id

        # PERF-008: O(1) entity_id→[Relation] index for relation lookups
        self._relation_index: Dict[str, List[Relation]] = defaultdict(list)

        # PERF-008: O(1) entity_id→cooccurrence count for TF-IDF
        self._entity_cooccur_count: Dict[str, int] = defaultdict(int)

        # Native index (string↔int mapping for C++ graph_ops)
        self._node_to_idx: Dict[str, int] = {}
        self._idx_to_node: Dict[int, str] = {}
        self._native_adjacency: Dict[int, list[int]] = {}
        self._native_index_dirty: bool = True

        # T-08: Co-occurrence tracking for TF-IDF relation weights
        from collections import Counter as _Counter
        self._cooccurrence: Dict[tuple, int] = defaultdict(int)  # (src, tgt) sorted pair → count
        self._entity_mentions: _Counter = _Counter()  # entity_id → total message mentions

        self._load()

    @staticmethod
    def _pg_row_to_entity(row: dict) -> Entity:
        """Convert a PG entity row dict to an Entity dataclass."""
        props = row.get("properties") or {}
        if isinstance(props, str):
            import json as _json
            props = _json.loads(props)
        return Entity(
            id=row["entity_id"],
            name=row["name"],
            entity_type=row["entity_type"],
            properties=props,
            mentions=row.get("mentions", 1),
            created_at=str(row.get("created_at", "")),
            last_accessed=str(row.get("last_accessed", "")),
        )

    def _normalize_entity_name(self, name: str) -> str:
        """Normalize entity name: collapse whitespace, strip."""
        return " ".join(name.strip().split())

    def _deduplicate_entity(self, entity: Entity) -> Optional[str]:
        """Check for existing entity with same lowercase name.

        Returns existing entity_id if duplicate found, None otherwise.
        If duplicate: prefers non-CONCEPT type, merges mentions.
        """
        if self._pg:
            existing_id = self._pg.deduplicate_entity(entity.name)
            if existing_id:
                # PG ON CONFLICT handles merge; just return the ID
                self._pg.add_entity(
                    entity_id=existing_id,
                    name=entity.name,
                    entity_type=entity.entity_type,
                    properties=entity.properties,
                    mentions=entity.mentions,
                )
                return existing_id
            return None

        normalized = self._normalize_entity_name(entity.name).lower()
        # PERF-008: O(1) lookup via name index instead of O(n) scan
        existing_id = self._name_index.get(normalized)
        if existing_id is not None and existing_id in self.entities:
            existing = self.entities[existing_id]
            # Merge mentions
            existing.mentions += entity.mentions
            existing.last_accessed = now_vancouver().isoformat()
            # Prefer specific type over CONCEPT
            if existing.entity_type == "concept" and entity.entity_type != "concept":
                existing.entity_type = entity.entity_type
            # Merge properties
            existing.properties.update(entity.properties)
            return existing_id
        return None

    def add_entity(self, entity: Entity) -> str:
        """Add or update an entity in the graph."""
        # Stopword filter for CONCEPT type
        normalized_name = self._normalize_entity_name(entity.name)
        if entity.entity_type == "concept" and normalized_name.lower() in ENTITY_STOPWORDS:
            _log.debug("Stopword entity filtered", name=entity.name)
            return ""

        entity.name = normalized_name

        # Check for duplicate
        existing_id = self._deduplicate_entity(entity)
        if existing_id:
            _log.debug("Entity deduplicated", name=entity.name, existing_id=existing_id[:8])
            return existing_id

        if self._pg:
            self._pg.add_entity(
                entity_id=entity.id,
                name=entity.name,
                entity_type=entity.entity_type,
                properties=entity.properties,
                mentions=entity.mentions,
            )
            return entity.id

        if entity.id in self.entities:
            existing = self.entities[entity.id]
            existing.mentions += 1
            existing.last_accessed = now_vancouver().isoformat()
            existing.properties.update(entity.properties)
        else:
            entity.created_at = now_vancouver().isoformat()
            entity.last_accessed = entity.created_at
            self.entities[entity.id] = entity
            # PERF-008: Update name index for O(1) dedup
            self._name_index[self._normalize_entity_name(entity.name).lower()] = entity.id
            self._native_index_dirty = True

        return entity.id

    def add_relation(self, relation: Relation) -> str:
        """Add a relation between two entities.

        Args:
            relation: Relation to add

        Returns:
            Relation ID or empty string if entities not found
        """
        if self._pg:
            # PG mode: entities live in PG, check existence there
            if not self._pg.entity_exists(relation.source_id):
                _log.warning("Source entity not found", id=relation.source_id)
                return ""
            if not self._pg.entity_exists(relation.target_id):
                _log.warning("Target entity not found", id=relation.target_id)
                return ""
            return self._pg.add_relation(
                source_id=relation.source_id,
                target_id=relation.target_id,
                relation_type=relation.relation_type,
                weight=relation.weight,
                context=relation.context,
            )

        if relation.source_id not in self.entities:
            _log.warning("Source entity not found", id=relation.source_id)
            return ""
        if relation.target_id not in self.entities:
            _log.warning("Target entity not found", id=relation.target_id)
            return ""

        if relation.id in self.relations:
            existing = self.relations[relation.id]
            # T-08: Track co-occurrence instead of naive +0.1
            pair = tuple(sorted([relation.source_id, relation.target_id]))
            self._cooccurrence[pair] += 1
            self._entity_mentions[relation.source_id] += 1
            self._entity_mentions[relation.target_id] += 1
            existing.weight += 0.1  # Keep naive increment as baseline until recalculate
            return existing.id

        relation.created_at = now_vancouver().isoformat()
        self.relations[relation.id] = relation

        self.adjacency[relation.source_id].add(relation.target_id)
        self.adjacency[relation.target_id].add(relation.source_id)
        # PERF-008: Update relation index for O(1) lookups
        self._relation_index[relation.source_id].append(relation)
        self._relation_index[relation.target_id].append(relation)
        self._native_index_dirty = True

        return relation.id

    def get_entity(self, entity_id: str) -> Optional[Entity]:
        """Get entity by ID."""
        if self._pg:
            row = self._pg.get_entity(entity_id)
            if row:
                return self._pg_row_to_entity(row)
            return None
        return self.entities.get(entity_id)

    def find_entities_by_name(self, name: str) -> List[Entity]:
        """Find entities by partial name match (case-insensitive)."""
        if self._pg:
            rows = self._pg.find_entities_by_name(name)
            return [self._pg_row_to_entity(r) for r in rows]
        name_lower = name.lower()
        return [
            e for e in self.entities.values()
            if name_lower in e.name.lower()
        ]

    def find_entities_by_names_batch(self, names: List[str]) -> Dict[str, List[Entity]]:
        """PERF-042: Batch version of find_entities_by_name."""
        if self._pg:
            rows = self._pg.find_entities_by_names_batch(names)
            result: dict[str, list[Entity]] = {name: [] for name in names}
            for row in rows:
                entity = self._pg_row_to_entity(row)
                # Match to original name(s)
                for name in names:
                    if name.lower() in entity.name.lower():
                        result[name].append(entity)
            return result
        # In-memory fallback
        result = {name: [] for name in names}
        for name in names:
            name_lower = name.lower()
            result[name] = [
                e for e in self.entities.values()
                if name_lower in e.name.lower()
            ]
        return result

    def find_entities_by_type(self, entity_type: str) -> List[Entity]:
        """Find all entities of a specific type."""
        if self._pg:
            rows = self._pg.find_entities_by_type(entity_type)
            return [self._pg_row_to_entity(r) for r in rows]
        return [
            e for e in self.entities.values()
            if e.entity_type == entity_type
        ]

    def _rebuild_native_index(self) -> None:
        """Rebuild string↔int mapping for native C++ graph_ops.

        Maps entity string IDs to sequential integers and converts
        the adjacency dict to int-keyed format for C++ consumption.
        """
        self._node_to_idx = {eid: i for i, eid in enumerate(self.entities)}
        self._idx_to_node = {i: eid for eid, i in self._node_to_idx.items()}
        self._native_adjacency = {}

        for node_str, neighbors_str in self.adjacency.items():
            if node_str in self._node_to_idx:
                idx = self._node_to_idx[node_str]
                self._native_adjacency[idx] = [
                    self._node_to_idx[n]
                    for n in neighbors_str
                    if n in self._node_to_idx
                ]

        self._native_index_dirty = False
        _log.debug(
            "Native graph index rebuilt",
            nodes=len(self._node_to_idx),
            edges=sum(len(v) for v in self._native_adjacency.values()),
        )

    def get_neighbors(self, entity_id: str, depth: int = 1) -> Set[str]:
        """Get neighboring entity IDs up to specified depth.

        Uses native C++ BFS when available and graph has >= 100 entities.
        Falls back to Python BFS otherwise.
        """
        if self._pg:
            return self._pg.get_neighbors(entity_id, depth)

        if entity_id not in self.entities:
            return set()

        use_native = (
            _HAS_NATIVE_GRAPH
            and len(self.entities) >= _NATIVE_BFS_THRESHOLD
        )

        if use_native:
            if self._native_index_dirty:
                self._rebuild_native_index()

            start_idx = self._node_to_idx.get(entity_id)
            if start_idx is None:
                return set()

            visited_indices = _native.graph_ops.bfs_neighbors(
                self._native_adjacency, [start_idx], depth
            )
            # Convert back to string IDs, exclude start node
            return {
                self._idx_to_node[idx]
                for idx in visited_indices
                if idx in self._idx_to_node and idx != start_idx
            }

        # Python fallback
        visited = {entity_id}
        frontier = {entity_id}

        for _ in range(depth):
            new_frontier = set()
            for node in frontier:
                for neighbor in self.adjacency[node]:
                    if neighbor not in visited:
                        visited.add(neighbor)
                        new_frontier.add(neighbor)
            frontier = new_frontier

        visited.discard(entity_id)
        return visited

    def get_relations_for_entity(self, entity_id: str) -> List[Relation]:
        """Get all relations involving an entity."""
        if self._pg:
            rows = self._pg.get_relations_for_entity(entity_id)
            return [
                Relation(
                    source_id=r["source_id"],
                    target_id=r["target_id"],
                    relation_type=r["relation_type"],
                    weight=float(r.get("weight", 1.0)),
                    context=r.get("context", ""),
                    created_at=str(r.get("created_at", "")),
                )
                for r in rows
            ]
        # PERF-008: O(1) lookup via relation index instead of O(R) scan
        return list(self._relation_index.get(entity_id, []))

    def recalculate_weights(self) -> Dict[str, int]:
        """Recalculate relation weights using TF-IDF scoring.

        Formula:
            TF = pair_count / source_msg_count
            IDF = ln(total_entities / (1 + source_cooccur_count))
            weight = 0.7 * TF * IDF + 0.3 * baseline

        Returns:
            Dict with 'total' and 'changed' counts
        """
        import math
        import time as _time

        t0 = _time.monotonic()
        total_entities = max(len(self.entities), 1)
        changed = 0

        # PERF-008: Pre-build entity→cooccurrence_count in single O(C) pass
        # instead of O(R*C) nested scan
        entity_cooccur_count: Dict[str, int] = defaultdict(int)
        for pair in self._cooccurrence:
            entity_cooccur_count[pair[0]] += 1
            entity_cooccur_count[pair[1]] += 1

        for rel_id, rel in self.relations.items():
            pair = tuple(sorted([rel.source_id, rel.target_id]))
            pair_count = self._cooccurrence.get(pair, 1)
            source_total = max(self._entity_mentions.get(rel.source_id, 1), 1)
            source_cooccur = entity_cooccur_count.get(rel.source_id, 0)

            tf = pair_count / source_total
            idf = math.log(total_entities / (1 + source_cooccur))
            baseline = rel.weight
            new_weight = max(0.0, min(1.0, 0.7 * tf * idf + 0.3 * baseline))

            if abs(new_weight - rel.weight) > 0.001:
                rel.weight = new_weight
                changed += 1

        dur_ms = int((_time.monotonic() - t0) * 1000)
        _log.info(
            "Relation weights recalculated",
            relations=len(self.relations),
            changed=changed,
            dur_ms=dur_ms,
        )
        return {"total": len(self.relations), "changed": changed}

    def find_path(self, source_id: str, target_id: str, max_depth: int = 3) -> List[str]:
        """Find shortest path between two entities using BFS."""
        if self._pg:
            return self._pg.find_path(source_id, target_id, max_depth)

        if source_id not in self.entities or target_id not in self.entities:
            return []

        if source_id == target_id:
            return [source_id]

        visited = {source_id}
        # PERF-008: Use deque for O(1) popleft instead of O(n) list.pop(0)
        queue = deque([(source_id, [source_id])])

        while queue:
            current, path = queue.popleft()

            if len(path) > max_depth:
                break

            for neighbor in self.adjacency[current]:
                if neighbor == target_id:
                    return path + [neighbor]

                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor]))

        return []

    def get_stats(self) -> Dict[str, Any]:
        """Get graph statistics including entity counts by type."""
        if self._pg:
            return self._pg.get_stats()

        type_counts: defaultdict[str, int] = defaultdict(int)
        for e in self.entities.values():
            type_counts[e.entity_type] += 1

        return {
            "total_entities": len(self.entities),
            "total_relations": len(self.relations),
            "entity_types": dict(type_counts),
            "avg_connections": sum(len(v) for v in self.adjacency.values()) / max(len(self.adjacency), 1)
        }

    def save(self):
        """Persist graph to JSON file (no-op in PG mode)."""
        if self._pg:
            return
        import os
        os.makedirs(os.path.dirname(self.persist_path), exist_ok=True)

        data = {
            "entities": {
                k: {
                    "id": v.id,
                    "name": v.name,
                    "entity_type": v.entity_type,
                    "properties": v.properties,
                    "mentions": v.mentions,
                    "created_at": v.created_at,
                    "last_accessed": v.last_accessed
                }
                for k, v in self.entities.items()
            },
            "relations": {
                k: {
                    "source_id": v.source_id,
                    "target_id": v.target_id,
                    "relation_type": v.relation_type,
                    "weight": v.weight,
                    "context": v.context,
                    "created_at": v.created_at
                }
                for k, v in self.relations.items()
            },
            # T-08: Persist co-occurrence data for TF-IDF
            "cooccurrence": {
                f"{k[0]}|{k[1]}": v for k, v in self._cooccurrence.items()
            },
            "entity_mentions": dict(self._entity_mentions),
        }

        # PERF-042: Use sync write (async version in save_async)
        with open(self.persist_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        _log.debug("MEM graph_save", entities=len(self.entities), rels=len(self.relations))

    async def save_async(self):
        """PERF-042: Async version of save() to avoid blocking async callers."""
        if self._pg:
            return
        if not aiofiles:
            # Fallback to sync if aiofiles not available
            self.save()
            return

        import os
        os.makedirs(os.path.dirname(self.persist_path), exist_ok=True)

        data = {
            "entities": {
                k: {
                    "id": v.id,
                    "name": v.name,
                    "entity_type": v.entity_type,
                    "properties": v.properties,
                    "mentions": v.mentions,
                    "created_at": v.created_at,
                    "last_accessed": v.last_accessed
                }
                for k, v in self.entities.items()
            },
            "relations": {
                k: {
                    "source_id": v.source_id,
                    "target_id": v.target_id,
                    "relation_type": v.relation_type,
                    "weight": v.weight,
                    "context": v.context,
                    "created_at": v.created_at
                }
                for k, v in self.relations.items()
            },
            "cooccurrence": {
                f"{k[0]}|{k[1]}": v for k, v in self._cooccurrence.items()
            },
            "entity_mentions": dict(self._entity_mentions),
        }

        async with aiofiles.open(self.persist_path, 'w', encoding='utf-8') as f:
            await f.write(json.dumps(data, ensure_ascii=False, indent=2))

        _log.debug("MEM graph_save_async", entities=len(self.entities), rels=len(self.relations))

    def _load(self):
        """Load graph from JSON file if exists (no-op in PG mode)."""
        if self._pg:
            _log.debug("MEM graph PG mode — skipping JSON load")
            return
        import os
        if not os.path.exists(self.persist_path):
            return

        try:
            with open(self.persist_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            for k, v in data.get("entities", {}).items():
                self.entities[k] = Entity(**v)

            for k, v in data.get("relations", {}).items():
                rel = Relation(**v)
                self.relations[k] = rel
                self.adjacency[rel.source_id].add(rel.target_id)
                self.adjacency[rel.target_id].add(rel.source_id)

            # T-08: Load co-occurrence data
            from collections import Counter as _Counter
            for k_str, v in data.get("cooccurrence", {}).items():
                parts = k_str.split("|", 1)
                if len(parts) == 2:
                    self._cooccurrence[tuple(parts)] = v
            self._entity_mentions = _Counter(data.get("entity_mentions", {}))

            self._native_index_dirty = True
            _log.debug("MEM graph_load", entities=len(self.entities), rels=len(self.relations))

        except Exception as e:
            _log.warning("Failed to load graph", error=str(e))
