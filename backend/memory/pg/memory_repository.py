"""M3 Semantic Memory — pgvector-backed MemoryRepositoryProtocol implementation."""

import uuid
from typing import Any, Dict, List, Optional

from backend.core.logging import get_logger
from backend.core.utils.timezone import now_vancouver

from .connection import PgConnectionManager

_log = get_logger("memory.pg.memory")


class PgMemoryRepository:
    """PostgreSQL + pgvector replacement for ChromaDBRepository.

    Implements the same public surface as ``MemoryRepositoryProtocol``
    so that ``LongTermMemory``, ``MemoryConsolidator``, and ``MemGPTManager``
    work without changes.
    """

    def __init__(self, conn_mgr: PgConnectionManager):
        self._conn = conn_mgr

    # ── Write ────────────────────────────────────────────────────────

    def add(
        self,
        content: str,
        embedding: List[float],
        metadata: Dict[str, Any],
        doc_id: str = None,
    ) -> str:
        doc_id = doc_id or str(uuid.uuid4())
        now = now_vancouver().isoformat()

        sql = """
            INSERT INTO memories
                (uuid, content, memory_type, importance, embedding,
                 source_session, source_channel,
                 created_at, last_accessed)
            VALUES
                (%s, %s, %s, %s, %s::vector,
                 %s, %s,
                 %s, %s)
        """
        params = (
            doc_id,
            content,
            metadata.get("type", "insight"),
            metadata.get("importance", 0.5),
            str(embedding),
            metadata.get("source_session"),
            metadata.get("source_channel"),
            metadata.get("created_at", now),
            metadata.get("last_accessed", now),
        )

        self._conn.execute(sql, params)
        _log.debug("Memory added", id=doc_id[:8])
        return doc_id

    # ── Read ─────────────────────────────────────────────────────────

    def get_all(
        self,
        include: List[str] = None,
        limit: int = None,
    ) -> Dict[str, Any]:
        """Return memories in ChromaDB-compatible dict format."""
        include = include or ["documents", "metadatas"]

        # PERF-026: Build dynamic column list, exclude embedding when not needed
        columns = ["uuid", "created_at"]
        if "documents" in include:
            columns.append("content")
        if "metadatas" in include:
            columns.extend(
                [
                    "memory_type",
                    "importance",
                    "access_count",
                    "last_accessed",
                    "source_session",
                    "source_channel",
                    "decayed_importance",
                ]
            )
        if "embeddings" in include:
            columns.append("embedding")

        col_list = ", ".join(columns)
        rows = self._conn.execute_dict(
            f"SELECT {col_list} FROM memories ORDER BY created_at DESC LIMIT %s",
            (limit or 10000,),
        )

        ids = []
        documents = []
        metadatas = []
        embeddings_out = []

        for r in rows:
            ids.append(r["uuid"])

            if "documents" in include:
                documents.append(r.get("content", ""))
            if "metadatas" in include:
                metadatas.append(self._row_to_metadata(r))
            if "embeddings" in include:
                embeddings_out.append(r.get("embedding"))

        result: Dict[str, Any] = {"ids": ids}
        if "documents" in include:
            result["documents"] = documents
        if "metadatas" in include:
            result["metadatas"] = metadatas
        if "embeddings" in include:
            result["embeddings"] = embeddings_out

        return result

    def get_by_id(self, doc_id: str) -> Optional[Dict[str, Any]]:
        rows = self._conn.execute_dict("SELECT * FROM memories WHERE uuid = %s", (doc_id,))
        if not rows:
            return None

        r = rows[0]
        return {
            "id": r["uuid"],
            "content": r["content"],
            "metadata": self._row_to_metadata(r),
        }

    def query_by_embedding(
        self,
        embedding: List[float],
        n_results: int,
        where: Dict[str, Any] = None,
        include: List[str] = None,
    ) -> List[Dict[str, Any]]:
        """Cosine similarity search using pgvector halfvec HNSW index."""
        where_sql, where_params = self._build_where(where)
        emb_str = str(embedding)

        # PERF-026: Use CTE to send embedding once
        sql = f"""
            WITH q AS (SELECT %s::halfvec(3072) AS qvec)
            SELECT *,
                   1 - (embedding::halfvec(3072) <=> q.qvec) AS similarity
            FROM memories, q
            {where_sql}
            ORDER BY embedding::halfvec(3072) <=> q.qvec
            LIMIT %s
        """
        params = (emb_str, *where_params, n_results)

        rows = self._conn.execute_dict(sql, params)

        results = []
        for r in rows:
            item = {
                "id": r["uuid"],
                "content": r["content"],
                "metadata": self._row_to_metadata(r),
                "similarity": float(r.get("similarity", 0)),
                "distance": 1 - float(r.get("similarity", 0)),
            }
            results.append(item)
        return results

    # ── Update ───────────────────────────────────────────────────────

    def update_metadata(self, doc_id: str, metadata: Dict[str, Any]) -> bool:
        set_parts = []
        params: list = []

        field_map = {
            "importance": "importance",
            "last_accessed": "last_accessed",
            "access_count": "access_count",
            "type": "memory_type",
            "source_session": "source_session",
            "source_channel": "source_channel",
            "decayed_importance": "decayed_importance",
        }

        for meta_key, col in field_map.items():
            if meta_key in metadata:
                set_parts.append(f"{col} = %s")
                params.append(metadata[meta_key])

        if not set_parts:
            return True

        params.append(doc_id)
        sql = f"UPDATE memories SET {', '.join(set_parts)} WHERE uuid = %s"
        self._conn.execute(sql, tuple(params))
        return True

    def batch_update_metadata(self, doc_ids: List[str], metadatas: List[Dict[str, Any]]) -> int:
        """Batch update metadata for multiple documents.

        Args:
            doc_ids: List of document IDs
            metadatas: List of metadata dicts (one per doc_id)

        Returns:
            Number of successfully updated documents
        """
        if not doc_ids or not metadatas or len(doc_ids) != len(metadatas):
            return 0

        updated = 0
        for doc_id, metadata in zip(doc_ids, metadatas):
            if self.update_metadata(doc_id, metadata):
                updated += 1
        return updated

    # ── Delete ───────────────────────────────────────────────────────

    def delete(self, doc_ids: List[str]) -> int:
        if not doc_ids:
            return 0
        rows = self._conn.execute(
            "DELETE FROM memories WHERE uuid = ANY(%s) RETURNING uuid",
            (doc_ids,),
        )
        deleted = len(rows)
        _log.debug("Memories deleted", count=deleted)
        return deleted

    # ── Count ────────────────────────────────────────────────────────

    def count(self) -> int:
        row = self._conn.execute_one("SELECT COUNT(*) FROM memories")
        return row[0] if row else 0

    # ── Collection property stub (for backward compat) ───────────────

    @property
    def collection(self):
        """Stub: callers should migrate to get_all / query_by_embedding."""
        return self

    def get(self, include=None, limit=None, **kwargs):
        """ChromaDB collection.get() shim."""
        return self.get_all(include=include, limit=limit)

    def get_type_counts(self) -> Dict[str, int]:
        """Get count of memories by type."""
        try:
            rows = self._conn.execute_dict(
                "SELECT memory_type, COUNT(*) AS cnt FROM memories GROUP BY memory_type"
            )
            return {r["memory_type"]: int(r["cnt"]) for r in rows}
        except Exception as e:
            _log.error("Type counts failed", error=str(e))
            return {}

    # ── Internals ────────────────────────────────────────────────────

    @staticmethod
    def _row_to_metadata(r: dict) -> dict:
        return {
            "type": r.get("memory_type", "insight"),
            "importance": float(r.get("importance", 0.5)),
            "source_session": r.get("source_session", ""),
            "source_channel": r.get("source_channel", ""),
            "created_at": str(r.get("created_at", "")),
            "last_accessed": str(r.get("last_accessed", "")),
            "access_count": r.get("access_count", 1),
            "decayed_importance": r.get("decayed_importance"),
        }

    @staticmethod
    def _build_where(where: Optional[Dict[str, Any]]) -> tuple:
        """Convert ChromaDB-style where filter to SQL WHERE clause."""
        if not where:
            return "", ()

        conditions = []
        params: list = []

        def _process(filt: dict):
            if "$and" in filt:
                for sub in filt["$and"]:
                    _process(sub)
                return
            if "$or" in filt:
                or_parts = []
                or_params_local: list = []
                for sub in filt["$or"]:
                    sub_sql, sub_params = PgMemoryRepository._build_single_condition(sub)
                    if sub_sql:
                        or_parts.append(sub_sql)
                        or_params_local.extend(sub_params)
                if or_parts:
                    conditions.append(f"({' OR '.join(or_parts)})")
                    params.extend(or_params_local)
                return
            sql_part, sql_params = PgMemoryRepository._build_single_condition(filt)
            if sql_part:
                conditions.append(sql_part)
                params.extend(sql_params)

        _process(where)

        if conditions:
            return "WHERE " + " AND ".join(conditions), tuple(params)
        return "", ()

    @staticmethod
    def _build_single_condition(filt: dict) -> tuple:
        """Convert a single {field: value} or {field: {$op: value}} to SQL."""
        for key, value in filt.items():
            if key.startswith("$"):
                continue

            col_map = {
                "type": "memory_type",
                "importance": "importance",
                "source_session": "source_session",
                "created_at": "created_at",
            }
            col = col_map.get(key, key)

            if isinstance(value, dict):
                for op, val in value.items():
                    if op == "$gte":
                        return f"{col} >= %s", [val]
                    elif op == "$lte":
                        return f"{col} <= %s", [val]
                    elif op == "$gt":
                        return f"{col} > %s", [val]
                    elif op == "$lt":
                        return f"{col} < %s", [val]
                    elif op == "$ne":
                        return f"{col} != %s", [val]
            else:
                return f"{col} = %s", [value]

        return "", []
