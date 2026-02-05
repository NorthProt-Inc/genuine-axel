"""Protocol definitions for permanent memory module.

These protocols define the interfaces for dependency injection and testing.
"""

from typing import Protocol, List, Dict, Optional, Any


class EmbeddingServiceProtocol(Protocol):
    """Protocol for embedding generation service."""

    def get_embedding(
        self, text: str, task_type: str = "retrieval_document"
    ) -> Optional[List[float]]:
        """Generate embedding vector for text.

        Args:
            text: Input text to embed
            task_type: Embedding task type (retrieval_document, retrieval_query)

        Returns:
            768-dimensional embedding vector or None on failure
        """
        ...

    def clear_cache(self) -> int:
        """Clear embedding cache.

        Returns:
            Number of cached entries cleared
        """
        ...


class MemoryRepositoryProtocol(Protocol):
    """Protocol for memory storage operations."""

    def add(
        self,
        content: str,
        embedding: List[float],
        metadata: Dict[str, Any],
    ) -> str:
        """Add a memory to storage.

        Args:
            content: Memory content text
            embedding: Embedding vector
            metadata: Memory metadata

        Returns:
            Document ID of the added memory
        """
        ...

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
        ...

    def get_by_id(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific memory by ID.

        Args:
            doc_id: Document ID

        Returns:
            Memory dict with id, content, metadata or None
        """
        ...

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
        ...

    def update_metadata(self, doc_id: str, metadata: Dict[str, Any]) -> bool:
        """Update memory metadata.

        Args:
            doc_id: Document ID
            metadata: Metadata fields to update

        Returns:
            True if successful
        """
        ...

    def delete(self, doc_ids: List[str]) -> int:
        """Delete memories by ID.

        Args:
            doc_ids: List of document IDs to delete

        Returns:
            Number of deleted memories
        """
        ...

    def count(self) -> int:
        """Get total memory count.

        Returns:
            Number of memories in storage
        """
        ...


class DecayCalculatorProtocol(Protocol):
    """Protocol for memory importance decay calculation."""

    def calculate(
        self,
        importance: float,
        created_at: str,
        access_count: int = 0,
        connection_count: int = 0,
        last_accessed: str = None,
        memory_type: str = None,
    ) -> float:
        """Calculate decayed importance score.

        Args:
            importance: Original importance (0-1)
            created_at: ISO timestamp of creation
            access_count: Number of times accessed
            connection_count: Number of graph connections
            last_accessed: ISO timestamp of last access
            memory_type: Memory category

        Returns:
            Decayed importance score
        """
        ...


class ConsolidatorProtocol(Protocol):
    """Protocol for memory consolidation operations."""

    def consolidate(self) -> Dict[str, int]:
        """Run memory consolidation.

        Deletes low-score memories and marks high-repetition ones as preserved.

        Returns:
            Report dict with deleted, preserved, checked counts
        """
        ...
