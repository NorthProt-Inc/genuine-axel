"""ChromaDB repository for memory storage."""

import uuid
from typing import Dict, List, Optional, Any

import chromadb

from backend.core.logging import get_logger
from backend.config import CHROMADB_PATH

_log = get_logger("memory.repository")


class ChromaDBRepository:
    """Repository for ChromaDB memory storage operations.

    Provides CRUD operations for memory documents with embeddings.
    """

    def __init__(
        self,
        db_path: str = None,
        collection_name: str = "axnmihn_memory",
        client: chromadb.ClientAPI = None,
    ):
        """Initialize repository.

        Args:
            db_path: Path to ChromaDB persistent storage
            collection_name: Name of the collection
            client: Optional pre-configured ChromaDB client
        """
        self.db_path = db_path or str(CHROMADB_PATH)

        if client:
            self._client = client
        else:
            self._client = chromadb.PersistentClient(path=self.db_path)

        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    @property
    def collection(self) -> chromadb.Collection:
        """Get underlying ChromaDB collection (for backward compatibility)."""
        return self._collection

    def add(
        self,
        content: str,
        embedding: List[float],
        metadata: Dict[str, Any],
        doc_id: str = None,
    ) -> str:
        """Add a memory to storage.

        Args:
            content: Memory content text
            embedding: Embedding vector
            metadata: Memory metadata
            doc_id: Optional document ID (generated if not provided)

        Returns:
            Document ID of the added memory
        """
        doc_id = doc_id or str(uuid.uuid4())

        try:
            self._collection.add(
                documents=[content],
                embeddings=[embedding],
                metadatas=[metadata],
                ids=[doc_id],
            )
            _log.debug("Memory added", id=doc_id[:8])
            return doc_id

        except Exception as e:
            _log.error(
                "ChromaDB add failed",
                error=str(e),
                error_type=type(e).__name__,
                doc_id=doc_id,
            )
            raise

    def get_all(
        self,
        include: List[str] = None,
        limit: int = None,
    ) -> Dict[str, Any]:
        """Get all memories from storage.

        Args:
            include: Fields to include (documents, metadatas, embeddings)
            limit: Maximum number of results

        Returns:
            Dict with ids, documents, metadatas, embeddings
        """
        include = include or ["documents", "metadatas"]

        try:
            if limit:
                return self._collection.get(include=include, limit=limit)
            return self._collection.get(include=include)

        except Exception as e:
            _log.error("Get all failed", error=str(e))
            return {"ids": [], "documents": [], "metadatas": [], "embeddings": []}

    def get_by_id(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific memory by ID.

        Args:
            doc_id: Document ID

        Returns:
            Memory dict with id, content, metadata or None
        """
        try:
            result = self._collection.get(
                ids=[doc_id],
                include=["documents", "metadatas"],
            )

            if result["ids"]:
                return {
                    "id": result["ids"][0],
                    "content": result["documents"][0] if result["documents"] else "",
                    "metadata": result["metadatas"][0] if result["metadatas"] else {},
                }

        except Exception as e:
            _log.error("Get by ID failed", error=str(e), doc_id=doc_id)

        return None

    def query_by_embedding(
        self,
        embedding: List[float],
        n_results: int,
        where: Dict[str, Any] = None,
        include: List[str] = None,
    ) -> List[Dict[str, Any]]:
        """Query memories by embedding similarity.

        Args:
            embedding: Query embedding vector
            n_results: Number of results to return
            where: Filter conditions
            include: Fields to include

        Returns:
            List of memory dicts with similarity scores
        """
        include = include or ["documents", "metadatas", "distances"]

        try:
            results = self._collection.query(
                query_embeddings=[embedding],
                n_results=n_results,
                where=where,
                include=include,
            )

            memories = []
            if results["ids"] and results["ids"][0]:
                for i, doc_id in enumerate(results["ids"][0]):
                    memory = {
                        "id": doc_id,
                        "content": (
                            results["documents"][0][i]
                            if results.get("documents") and results["documents"][0]
                            else ""
                        ),
                        "metadata": (
                            results["metadatas"][0][i]
                            if results.get("metadatas") and results["metadatas"][0]
                            else {}
                        ),
                    }

                    if results.get("distances") and results["distances"][0]:
                        distance = results["distances"][0][i]
                        memory["distance"] = distance
                        memory["similarity"] = 1 - distance

                    memories.append(memory)

            return memories

        except Exception as e:
            _log.error("Query failed", error=str(e))
            return []

    def update_metadata(self, doc_id: str, metadata: Dict[str, Any]) -> bool:
        """Update memory metadata.

        Args:
            doc_id: Document ID
            metadata: Metadata fields to update (merged with existing)

        Returns:
            True if successful
        """
        try:
            self._collection.update(
                ids=[doc_id],
                metadatas=[metadata],
            )
            return True

        except Exception as e:
            _log.error("Update failed", error=str(e), doc_id=doc_id)
            return False

    def update_document(
        self,
        doc_id: str,
        document: str,
        embedding: List[float],
    ) -> bool:
        """Update document content and embedding.

        Args:
            doc_id: Document ID to update
            document: New document content
            embedding: New embedding vector

        Returns:
            True if successful
        """
        try:
            self._collection.update(
                ids=[doc_id],
                documents=[document],
                embeddings=[embedding],
            )
            _log.debug("Document updated", id=doc_id[:8])
            return True

        except Exception as e:
            _log.error(
                "Document update failed",
                error=str(e),
                error_type=type(e).__name__,
                doc_id=doc_id,
            )
            return False

    def delete(self, doc_ids: List[str]) -> int:
        """Delete memories by ID.

        Args:
            doc_ids: List of document IDs to delete

        Returns:
            Number of deleted memories
        """
        if not doc_ids:
            return 0

        try:
            self._collection.delete(ids=doc_ids)
            _log.debug("Memories deleted", count=len(doc_ids))
            return len(doc_ids)

        except Exception as e:
            _log.error("Delete failed", error=str(e))
            return 0

    def count(self) -> int:
        """Get total memory count.

        Returns:
            Number of memories in storage
        """
        try:
            return self._collection.count()
        except Exception as e:
            _log.error("Count failed", error=str(e))
            return 0
