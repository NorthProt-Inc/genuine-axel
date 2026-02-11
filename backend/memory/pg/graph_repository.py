"""M4 Knowledge Graph — PostgreSQL replacement for JSON file graph storage."""

import json
from typing import Any, Dict, List, Optional, Set

from backend.core.logging import get_logger
from backend.core.utils.timezone import now_vancouver

from .connection import PgConnectionManager

_log = get_logger("memory.pg.graph")


class PgGraphRepository:
    """PostgreSQL-backed knowledge graph operations.

    Replaces the JSON file load/save cycle with per-operation SQL,
    using the existing ``entities`` and ``relations`` tables.
    """

    def __init__(self, conn_mgr: PgConnectionManager):
        self._conn = conn_mgr

    # ── Entity CRUD ──────────────────────────────────────────────────

    def add_entity(self, entity_id: str, name: str, entity_type: str,
                   properties: Dict[str, Any] = None, mentions: int = 1) -> str:
        now = now_vancouver().isoformat()
        props_json = json.dumps(properties or {}, ensure_ascii=False)

        self._conn.execute(
            """INSERT INTO entities
                   (entity_id, name, entity_type, properties, mentions, created_at, last_accessed)
               VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s)
               ON CONFLICT (entity_id) DO UPDATE SET
                   mentions = entities.mentions + EXCLUDED.mentions,
                   properties = entities.properties || EXCLUDED.properties,
                   last_accessed = EXCLUDED.last_accessed""",
            (entity_id, name, entity_type, props_json, mentions, now, now),
        )
        return entity_id

    def get_entity(self, entity_id: str) -> Optional[dict]:
        rows = self._conn.execute_dict(
            "SELECT * FROM entities WHERE entity_id = %s", (entity_id,)
        )
        return rows[0] if rows else None

    def find_entities_by_name(self, name: str) -> List[dict]:
        """Fuzzy name search using gin_trgm_ops index."""
        return self._conn.execute_dict(
            "SELECT * FROM entities WHERE name ILIKE %s ORDER BY mentions DESC LIMIT 20",
            (f"%{name}%",),
        )

    def find_entities_by_names_batch(self, names: List[str]) -> List[dict]:
        """PERF-042: Batch version of find_entities_by_name using OR conditions."""
        if not names:
            return []
        # Build ILIKE conditions for each name
        conditions = " OR ".join(["name ILIKE %s"] * len(names))
        params = tuple(f"%{name}%" for name in names)
        query = f"SELECT * FROM entities WHERE {conditions} ORDER BY mentions DESC LIMIT 100"
        return self._conn.execute_dict(query, params)

    def find_entities_by_type(self, entity_type: str) -> List[dict]:
        return self._conn.execute_dict(
            "SELECT * FROM entities WHERE entity_type = %s ORDER BY mentions DESC",
            (entity_type,),
        )

    def entity_exists(self, entity_id: str) -> bool:
        row = self._conn.execute_one(
            "SELECT 1 FROM entities WHERE entity_id = %s", (entity_id,)
        )
        return row is not None

    def deduplicate_entity(self, name: str) -> Optional[str]:
        """Return existing entity_id if a case-insensitive name match exists."""
        row = self._conn.execute_one(
            "SELECT entity_id FROM entities WHERE LOWER(name) = LOWER(%s) LIMIT 1",
            (name,),
        )
        return row[0] if row else None

    def count_entities(self) -> int:
        row = self._conn.execute_one("SELECT COUNT(*) FROM entities")
        return row[0] if row else 0

    # ── Relation CRUD ────────────────────────────────────────────────

    def add_relation(self, source_id: str, target_id: str, relation_type: str,
                     weight: float = 1.0, context: str = "") -> str:
        now = now_vancouver().isoformat()

        self._conn.execute(
            """INSERT INTO relations
                   (source_id, target_id, relation_type, weight, context, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (source_id, target_id, relation_type) DO UPDATE SET
                   weight = relations.weight + 0.1,
                   context = EXCLUDED.context,
                   updated_at = EXCLUDED.updated_at""",
            (source_id, target_id, relation_type, weight, context, now, now),
        )
        return f"{source_id}--{relation_type}-->{target_id}"

    def get_relations_for_entity(self, entity_id: str) -> List[dict]:
        return self._conn.execute_dict(
            """SELECT * FROM relations
               WHERE source_id = %s OR target_id = %s
               ORDER BY weight DESC""",
            (entity_id, entity_id),
        )

    def count_relations(self) -> int:
        row = self._conn.execute_one("SELECT COUNT(*) FROM relations")
        return row[0] if row else 0

    # ── Graph traversal ──────────────────────────────────────────────

    def get_neighbors(self, entity_id: str, depth: int = 2) -> Set[str]:
        """Depth-bounded BFS using a recursive CTE with cycle detection."""
        rows = self._conn.execute(
            """
            WITH RECURSIVE neighbors(entity_id, depth, visited) AS (
                SELECT %s::text, 0, ARRAY[%s::text]
                UNION ALL
                SELECT
                    CASE WHEN r.source_id = n.entity_id
                         THEN r.target_id
                         ELSE r.source_id
                    END,
                    n.depth + 1,
                    n.visited || CASE WHEN r.source_id = n.entity_id
                                      THEN r.target_id
                                      ELSE r.source_id
                                 END
                FROM neighbors n
                JOIN relations r ON r.source_id = n.entity_id OR r.target_id = n.entity_id
                WHERE n.depth < %s
                  AND NOT (CASE WHEN r.source_id = n.entity_id
                                THEN r.target_id
                                ELSE r.source_id
                           END = ANY(n.visited))
            )
            SELECT DISTINCT entity_id FROM neighbors WHERE entity_id != %s
            """,
            (entity_id, entity_id, depth, entity_id),
        )
        return {row[0] for row in rows}

    def find_path(self, source_id: str, target_id: str, max_depth: int = 3) -> List[str]:
        """BFS shortest path between two entities."""
        rows = self._conn.execute(
            """
            WITH RECURSIVE paths(entity_id, path, depth) AS (
                SELECT %s::text, ARRAY[%s::text], 0
                UNION ALL
                SELECT
                    CASE WHEN r.source_id = p.entity_id
                         THEN r.target_id
                         ELSE r.source_id
                    END,
                    p.path || CASE WHEN r.source_id = p.entity_id
                                   THEN r.target_id
                                   ELSE r.source_id
                              END,
                    p.depth + 1
                FROM paths p
                JOIN relations r ON r.source_id = p.entity_id OR r.target_id = p.entity_id
                WHERE p.depth < %s
                  AND NOT (CASE WHEN r.source_id = p.entity_id
                                THEN r.target_id
                                ELSE r.source_id
                           END = ANY(p.path))
            )
            SELECT path FROM paths WHERE entity_id = %s ORDER BY depth LIMIT 1
            """,
            (source_id, source_id, max_depth, target_id),
        )
        if rows and rows[0]:
            return rows[0][0]
        return []

    # ── Stats ────────────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        entity_count = self.count_entities()
        relation_count = self.count_relations()

        type_rows = self._conn.execute(
            "SELECT entity_type, COUNT(*) FROM entities GROUP BY entity_type"
        )
        type_counts = {r[0]: r[1] for r in type_rows}

        avg_row = self._conn.execute_one(
            """SELECT AVG(conn_count) FROM (
                   SELECT COUNT(*) as conn_count
                   FROM relations
                   GROUP BY source_id
               ) sub"""
        )
        avg_connections = float(avg_row[0]) if avg_row and avg_row[0] else 0.0

        return {
            "total_entities": entity_count,
            "total_relations": relation_count,
            "entity_types": type_counts,
            "avg_connections": avg_connections,
        }
