"""Core memory operations - initialization, add, query, delete."""

import uuid
from typing import Dict, List, Optional, Any

from backend.core.logging import get_logger
from backend.config import CHROMADB_PATH
from backend.core.utils.timezone import now_vancouver

from .config import MemoryConfig
from .embedding_service import EmbeddingService
from .repository import ChromaDBRepository
from .decay_calculator import AdaptiveDecayCalculator
from .consolidator import MemoryConsolidator
from .access_tracker import AccessTracker
from .retrieval import MemoryRetriever
from .promotion import (
    PromotionCriteria,
    ContentKeyGenerator,
    RepetitionCache,
)

_log = get_logger("memory.permanent")


class LongTermMemory:
    """Facade for long-term memory operations.

    Provides unified interface for:
    - Memory storage with deduplication
    - Similarity-based retrieval
    - Access tracking
    - Memory consolidation

    This class maintains backward compatibility with the original API.
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        embedding_model: Optional[str] = None,
        repository=None,
    ):
        """Initialize long-term memory.

        Args:
            db_path: Path to ChromaDB storage
            embedding_model: Model name for embeddings
            repository: Optional pre-built repository (e.g. PgMemoryRepository).
                        If provided, db_path is ignored.
        """
        self.db_path = db_path or str(CHROMADB_PATH)
        self.embedding_model = embedding_model or MemoryConfig.EMBEDDING_MODEL

        # Initialize components
        if repository is not None:
            self._repository = repository
        else:
            self._repository = ChromaDBRepository(db_path=self.db_path)
            
        self._init_embedding_service()
        self._decay_calculator = AdaptiveDecayCalculator()
        self._consolidator = MemoryConsolidator(
            repository=self._repository,
            decay_calculator=self._decay_calculator,
        )

        # Initialize sub-components
        self._content_key_generator = ContentKeyGenerator()
        self._repetition_cache = RepetitionCache()
        self._load_repetition_cache()

        self._access_tracker = AccessTracker(repository=self._repository)
        self._retriever = MemoryRetriever(
            repository=self._repository,
            embedding_service=self._embedding_service,
            decay_calculator=self._decay_calculator,
        )

    def _init_embedding_service(self) -> None:
        """Initialize embedding service with genai.Client."""
        try:
            from backend.core.utils.gemini_client import get_gemini_client

            client = get_gemini_client()
            self._embedding_service = EmbeddingService(
                client=client,
                embedding_model=self.embedding_model,
            )
            _log.debug("GenAI client initialized for embeddings")

        except Exception as e:
            _log.warning("GenAI client init failed", error=str(e))
            self._embedding_service = EmbeddingService(client=None)

    # =========================================================================
    # Backward compatibility: collection property
    # =========================================================================
    @property
    def collection(self):
        """Get underlying ChromaDB collection (for backward compatibility).

        WARNING: Direct access is deprecated. Use public methods instead.
        """
        return self._repository.collection

    @property
    def genai_client(self):
        """Get GenAI client (for backward compatibility)."""
        return self._embedding_service.client

    # =========================================================================
    # New public API (replacing direct collection access)
    # =========================================================================
    def get_all_memories(
        self,
        include: Optional[List[str]] = None,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Get all memories from storage.

        Args:
            include: Fields to include (documents, metadatas, embeddings)
            limit: Maximum number of results

        Returns:
            Dict with ids, documents, metadatas
        """
        return self._repository.get_all(include=include, limit=limit)

    def delete_memories(self, doc_ids: List[str]) -> int:
        """Delete memories by ID.

        Args:
            doc_ids: List of document IDs to delete

        Returns:
            Number of deleted memories
        """
        return self._repository.delete(doc_ids)

    def find_similar_memories(
        self,
        content: str,
        threshold: float = 0.8,
        n_results: int = 5,
    ) -> List[Dict[str, Any]]:
        """Find memories similar to given content using hybrid scoring.

        Combines vector similarity (70%) with text similarity (30%)
        for more accurate matching.

        Args:
            content: Content to compare
            threshold: Minimum similarity threshold (0-1)
            n_results: Maximum results to return

        Returns:
            List of similar memories with similarity scores
        """
        return self._retriever.find_similar_memories(content, threshold, n_results)

    def get_embedding_for_text(
        self,
        text: str,
        task_type: str = "retrieval_query",
    ) -> Optional[List[float]]:
        """Get embedding vector for text.

        Args:
            text: Text to embed
            task_type: Embedding task type

        Returns:
            Embedding vector or None
        """
        return self._retriever.get_embedding(text, task_type)

    # =========================================================================
    # Original public API (maintained for backward compatibility)
    # =========================================================================
    def _get_embedding(
        self, text: str, task_type: str = "retrieval_document"
    ) -> Optional[List[float]]:
        """Get embedding (backward compatibility wrapper)."""
        return self._embedding_service.get_embedding(text, task_type=task_type)

    def _load_repetition_cache(self) -> None:
        """Load repetition counts from storage."""
        try:
            results = self._repository.get_all(include=["metadatas"])

            for metadata in results.get("metadatas", []):
                if metadata:
                    key = self._content_key_generator.get_content_key(
                        metadata.get("content_hash", "")
                    )
                    self._repetition_cache.set(key, metadata.get("repetitions", 1))

            _log.debug("Repetition cache loaded", count=len(self._repetition_cache))

        except Exception as e:
            _log.error("Cache load error", error=str(e))

    def _get_content_key(self, content: str) -> str:
        """Generate normalized content key for deduplication."""
        return self._content_key_generator.get_content_key(content)

    def add(
        self,
        content: str,
        memory_type: str,
        importance: float = 0.5,
        source_session: Optional[str] = None,
        event_timestamp: Optional[str] = None,
        force: bool = False,
    ) -> Optional[str]:
        """Add memory to long-term storage.

        Args:
            content: Memory content
            memory_type: Type (fact, preference, insight, conversation)
            importance: Importance score (0-1)
            source_session: Source session ID
            event_timestamp: When event occurred
            force: Force storage regardless of criteria

        Returns:
            Document ID or None if rejected
        """
        content_key = self._get_content_key(content)
        repetitions = self._repetition_cache.increment(content_key)

        # Check promotion criteria
        should_store, reason = PromotionCriteria.should_promote(
            content=content,
            repetitions=repetitions,
            importance=importance,
            force=force,
        )

        if not should_store:
            _log.debug("Memory rejected", reason=reason, preview=content[:50])
            return None

        # Generate embedding once for both dedup search and storage (PERF-005)
        embedding = self._embedding_service.get_embedding(content)
        if not embedding:
            _log.error(
                "Memory storage failed: embedding generation failed",
                preview=content[:80],
                importance=importance,
            )
            return None

        # Check for existing similar memory using pre-computed embedding
        existing = self._retriever.find_similar_memory(
            content,
            threshold=MemoryConfig.DUPLICATE_THRESHOLD,
            embedding=embedding,
        )
        if existing:
            self._update_repetitions(existing["id"], repetitions)
            _log.debug("Updated existing memory", id=existing["id"])
            return existing["id"]

        # Create metadata
        doc_id = str(uuid.uuid4())
        now = now_vancouver().isoformat()

        metadata = {
            "type": memory_type,
            "importance": importance,
            "repetitions": repetitions,
            "promotion_reason": reason,
            "source_session": source_session or None,
            "content_hash": content_key,
            "created_at": now,
            "event_timestamp": event_timestamp or now,
            "last_accessed": now,
        }

        try:
            self._repository.add(
                content=content,
                embedding=embedding,
                metadata=metadata,
                doc_id=doc_id,
            )
            _log.info("MEM store", type=memory_type, content_len=len(content), id=doc_id[:8])
            return doc_id

        except Exception as e:
            _log.error(
                "ChromaDB add failed",
                error=str(e),
                error_type=type(e).__name__,
                doc_id=doc_id,
            )
            return None

    def _find_similar(
        self,
        content: str,
        threshold: float = 0.8,
        embedding: Optional[List[float]] = None,
    ) -> Optional[Dict]:
        """Find similar existing memory.

        Args:
            content: Content text to search for.
            threshold: Minimum similarity threshold (0-1).
            embedding: Pre-computed embedding to reuse. If None, a new
                embedding is generated with task_type ``retrieval_query``.
        """
        return self._retriever.find_similar_memory(content, threshold, embedding)

    def _update_repetitions(self, doc_id: str, repetitions: int) -> None:
        """Update memory repetition count."""
        try:
            self._repository.update_metadata(
                doc_id,
                {
                    "repetitions": repetitions,
                    "last_accessed": now_vancouver().isoformat(),
                },
            )
        except Exception as e:
            _log.error("Repetition update error", error=str(e), id=doc_id)

    def query(
        self,
        query_text: str,
        n_results: int = 5,
        memory_type: Optional[str] = None,
        temporal_filter: Optional[dict] = None,
    ) -> List[Dict[str, Any]]:
        """Query memories by semantic similarity.

        Args:
            query_text: Query text
            n_results: Number of results
            memory_type: Filter by type
            temporal_filter: Temporal filter config

        Returns:
            List of matching memories with scores
        """
        memories = self._retriever.query(
            query_text=query_text,
            n_results=n_results,
            memory_type=memory_type,
            temporal_filter=temporal_filter,
            access_callback=self._access_tracker.track_access,
        )
        
        self._access_tracker.maybe_flush()
        
        return memories

    def _maybe_flush_access_updates(self) -> None:
        """Check if access updates should be flushed (backward compat)."""
        self._access_tracker.maybe_flush()

    def flush_access_updates(self) -> int:
        """Flush pending access updates to storage.

        Returns:
            Number of successfully updated memories
        """
        return self._access_tracker.flush()

    def get_formatted_context(self, query: str, max_items: int = 5) -> str:
        """Get formatted context string for LLM.

        Args:
            query: Query text
            max_items: Maximum memories to include

        Returns:
            Formatted context string
        """
        return self._retriever.get_formatted_context(
            query=query,
            max_items=max_items,
            query_callback=self.query,
        )

    def count(self) -> int:
        """Get total memory count.

        Returns:
            Number of memories in storage
        """
        return self._repository.count()

    def get_stats(self) -> Dict[str, Any]:
        """Get memory statistics.

        Returns:
            Stats dict with counts and types
        """
        try:
            count = self.count()
            # Use optimized type counts query (PERF-020)
            type_counts = self._repository.get_type_counts()

            return {
                "total_memories": count,
                "by_type": type_counts,
                "cached_repetitions": len(self._repetition_cache),
                "pending_access_updates": self._access_tracker.pending_count,
            }

        except Exception as e:
            _log.error("Stats error", error=str(e))
            return {}

    def consolidate_memories(self) -> Dict[str, int]:
        """Run memory consolidation.

        Returns:
            Report dict with deleted, preserved, checked counts
        """
        self.flush_access_updates()
        return self._consolidator.consolidate()
