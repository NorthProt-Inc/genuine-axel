"""LongTermMemory facade - main public interface."""

import re
import time
import uuid
from typing import Dict, List, Optional, Any, Set

from backend.core.logging import get_logger
from backend.config import CHROMADB_PATH
from backend.core.utils.timezone import now_vancouver

from .config import MemoryConfig
from .embedding_service import EmbeddingService
from .repository import ChromaDBRepository
from .decay_calculator import AdaptiveDecayCalculator
from .consolidator import MemoryConsolidator

_log = get_logger("memory.permanent")


class PromotionCriteria:
    """Criteria for promoting memories to long-term storage."""

    @classmethod
    def should_promote(
        cls,
        content: str,
        repetitions: int = 1,
        importance: float = 0.5,
        force: bool = False,
    ) -> tuple[bool, str]:
        """Check if memory should be promoted to long-term storage.

        Args:
            content: Memory content
            repetitions: Number of times seen
            importance: Importance score (0-1)
            force: Force promotion regardless of criteria

        Returns:
            Tuple of (should_promote, reason)
        """
        if force:
            return True, "forced_promotion"

        if repetitions >= MemoryConfig.MIN_REPETITIONS:
            return True, f"repetitions:{repetitions}"

        if importance >= MemoryConfig.MIN_IMPORTANCE:
            return True, f"importance:{importance:.2f}"

        return False, f"low_importance:{importance:.2f}"


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
        db_path: str = None,
        embedding_model: str = None,
    ):
        """Initialize long-term memory.

        Args:
            db_path: Path to ChromaDB storage
            embedding_model: Model name for embeddings
        """
        self.db_path = db_path or str(CHROMADB_PATH)
        self.embedding_model = embedding_model or MemoryConfig.EMBEDDING_MODEL

        # Initialize components
        self._repository = ChromaDBRepository(db_path=self.db_path)
        self._init_embedding_service()
        self._decay_calculator = AdaptiveDecayCalculator()
        self._consolidator = MemoryConsolidator(
            repository=self._repository,
            decay_calculator=self._decay_calculator,
        )

        # Repetition cache
        self._repetition_cache: Dict[str, int] = {}
        self._load_repetition_cache()

        # Access update batching
        self._pending_access_updates: Set[str] = set()
        self._last_flush_time: float = time.time()

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
        include: List[str] = None,
        limit: int = None,
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
        """Find memories similar to given content.

        Args:
            content: Content to compare
            threshold: Minimum similarity threshold (0-1)
            n_results: Maximum results to return

        Returns:
            List of similar memories with similarity scores
        """
        embedding = self._embedding_service.get_embedding(
            content, task_type="retrieval_query"
        )
        if not embedding:
            return []

        results = self._repository.query_by_embedding(
            embedding=embedding,
            n_results=n_results,
            include=["documents", "metadatas", "distances"],
        )

        # Filter by threshold
        return [m for m in results if m.get("similarity", 0) >= threshold]

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
        return self._embedding_service.get_embedding(text, task_type=task_type)

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
                    key = self._get_content_key(metadata.get("content_hash", ""))
                    self._repetition_cache[key] = metadata.get("repetitions", 1)

            _log.debug("Repetition cache loaded", count=len(self._repetition_cache))

        except Exception as e:
            _log.error("Cache load error", error=str(e))

    def _get_content_key(self, content: str) -> str:
        """Generate normalized content key for deduplication."""
        text = content.lower().strip()

        # Remove common particles
        particles = [
            "은",
            "는",
            "이",
            "가",
            "을",
            "를",
            "의",
            "에",
            "와",
            "과",
            "로",
            "으로",
            "에서",
            "까지",
            "부터",
            "도",
            "만",
            "뿐",
            "이다",
            "입니다",
            "이에요",
            "예요",
            "임",
            "임.",
            "'s",
            "is",
            "the",
            "a",
            "an",
        ]
        for p in particles:
            text = text.replace(p, "")

        text = re.sub(r"[^\w\s가-힣]", "", text)
        text = re.sub(r"\s+", " ", text).strip()

        return text[:100]

    def add(
        self,
        content: str,
        memory_type: str,
        importance: float = 0.5,
        source_session: str = None,
        event_timestamp: str = None,
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
        self._repetition_cache[content_key] = self._repetition_cache.get(content_key, 0) + 1
        repetitions = self._repetition_cache[content_key]

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

        # Check for existing similar memory
        existing = self._find_similar(content, threshold=MemoryConfig.DUPLICATE_THRESHOLD)
        if existing:
            self._update_repetitions(existing["id"], repetitions)
            _log.debug("Updated existing memory", id=existing["id"])
            return existing["id"]

        # Generate embedding
        embedding = self._embedding_service.get_embedding(content)
        if not embedding:
            _log.error(
                "Memory storage failed: embedding generation failed",
                preview=content[:80],
                importance=importance,
            )
            return None

        # Create metadata
        doc_id = str(uuid.uuid4())
        now = now_vancouver().isoformat()

        metadata = {
            "type": memory_type,
            "importance": importance,
            "repetitions": repetitions,
            "promotion_reason": reason,
            "source_session": source_session or "unknown",
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

    def _find_similar(self, content: str, threshold: float = 0.8) -> Optional[Dict]:
        """Find similar existing memory."""
        embedding = self._embedding_service.get_embedding(
            content, task_type="retrieval_query"
        )
        if not embedding:
            return None

        try:
            results = self._repository.query_by_embedding(
                embedding=embedding,
                n_results=1,
                include=["documents", "metadatas", "distances"],
            )

            if results:
                first = results[0]
                if first.get("similarity", 0) >= threshold:
                    return {
                        "id": first["id"],
                        "content": first["content"],
                        "metadata": first["metadata"],
                        "similarity": first["similarity"],
                    }

        except Exception as e:
            _log.error("Similar search error", error=str(e))

        return None

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
        memory_type: str = None,
        temporal_filter: dict = None,
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
        embedding = self._embedding_service.get_embedding(
            query_text, task_type="retrieval_query"
        )
        if not embedding:
            return []

        try:
            # Build filter
            where_clauses = []

            if memory_type:
                where_clauses.append({"type": memory_type})

            if temporal_filter and temporal_filter.get("chroma_filter"):
                chroma_filter = temporal_filter["chroma_filter"]
                if "$and" in chroma_filter:
                    where_clauses.extend(chroma_filter["$and"])

            where_filter = None
            if len(where_clauses) == 1:
                where_filter = where_clauses[0]
            elif len(where_clauses) > 1:
                where_filter = {"$and": where_clauses}

            # Query with extra results for filtering
            fetch_count = max(n_results + 5, int(n_results * 1.5))
            results = self._repository.query_by_embedding(
                embedding=embedding,
                n_results=fetch_count,
                where=where_filter,
                include=["documents", "metadatas", "distances"],
            )

            from backend.memory.temporal import boost_temporal_score

            memories = []
            for item in results:
                doc_id = item["id"]
                metadata = item.get("metadata", {})
                base_relevance = item.get("similarity", 0.5)

                event_time = (
                    metadata.get("event_timestamp")
                    or metadata.get("created_at")
                    or metadata.get("timestamp", "")
                )
                access_count = metadata.get("access_count", 0)

                # Apply decay
                decay_factor = self._decay_calculator.calculate(
                    1.0, event_time, access_count=access_count
                )
                semantic_score = base_relevance * decay_factor

                # Apply temporal boost
                if temporal_filter:
                    effective_score = boost_temporal_score(
                        base_score=semantic_score,
                        memory_date=event_time,
                        temporal_filter=temporal_filter,
                        boost_factor=0.4,
                    )
                else:
                    effective_score = semantic_score

                # Track access
                self._pending_access_updates.add(doc_id)

                memories.append(
                    {
                        "id": doc_id,
                        "content": item.get("content", ""),
                        "metadata": metadata,
                        "relevance": base_relevance,
                        "effective_score": effective_score,
                        "decay_factor": decay_factor,
                        "temporal_boosted": temporal_filter is not None,
                    }
                )

            # Sort by effective score
            memories.sort(key=lambda x: x["effective_score"], reverse=True)

            _log.debug(
                "MEM qry",
                qry_len=len(query_text),
                res=len(memories),
                temporal=temporal_filter is not None,
            )

            self._maybe_flush_access_updates()

            return memories[:n_results]

        except Exception as e:
            _log.error("Query error", error=str(e))
            return []

    def _maybe_flush_access_updates(self) -> None:
        """Check if access updates should be flushed."""
        should_flush = False

        if len(self._pending_access_updates) >= MemoryConfig.FLUSH_THRESHOLD:
            should_flush = True
            _log.debug(
                "Auto-flush triggered (threshold)",
                pending=len(self._pending_access_updates),
                threshold=MemoryConfig.FLUSH_THRESHOLD,
            )

        elapsed = time.time() - self._last_flush_time
        if elapsed >= MemoryConfig.FLUSH_INTERVAL_SECONDS and self._pending_access_updates:
            should_flush = True
            _log.debug(
                "Auto-flush triggered (interval)",
                elapsed_sec=round(elapsed, 1),
                interval=MemoryConfig.FLUSH_INTERVAL_SECONDS,
            )

        if should_flush:
            self.flush_access_updates()

    def flush_access_updates(self) -> int:
        """Flush pending access updates to storage.

        Returns:
            Number of successfully updated memories
        """
        if not self._pending_access_updates:
            return 0

        ids_to_update = list(self._pending_access_updates)
        self._pending_access_updates.clear()
        self._last_flush_time = time.time()

        now = now_vancouver().isoformat()
        updated = 0
        failed_ids = []

        for doc_id in ids_to_update:
            try:
                self._repository.update_metadata(doc_id, {"last_accessed": now})
                updated += 1
            except Exception as e:
                failed_ids.append(doc_id)
                _log.debug("Access update failed", doc_id=doc_id[:8], error=str(e))

        if failed_ids:
            _log.warning(
                "Some access updates failed",
                failed_count=len(failed_ids),
                total=len(ids_to_update),
            )
            self._pending_access_updates.update(failed_ids)

        if updated > 0:
            _log.debug("MEM flush", count=updated)

        return updated

    def get_formatted_context(self, query: str, max_items: int = 5) -> str:
        """Get formatted context string for LLM.

        Args:
            query: Query text
            max_items: Maximum memories to include

        Returns:
            Formatted context string
        """
        memories = self.query(query, n_results=max_items)

        if not memories:
            return ""

        lines = []
        for m in memories:
            metadata = m["metadata"]
            relevance = f"{m['relevance']:.0%}"

            if "user_query" in metadata and "ai_response" in metadata:
                content = f"Mark: {metadata['user_query']}\nAxel: {metadata['ai_response']}"
                ts = metadata.get("timestamp", "")[:10]
                lines.append(f"[기억/대화 {ts} | {relevance}]\n{content}")
            else:
                mem_type = metadata.get("type", "unknown")
                content = m["content"]
                lines.append(f"[{mem_type}|{relevance}] {content}")

        return "\n".join(lines)

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
            results = self._repository.get_all(include=["metadatas"])

            type_counts = {}
            for m in results.get("metadatas", []):
                if m:
                    t = m.get("type", "unknown")
                    type_counts[t] = type_counts.get(t, 0) + 1

            return {
                "total_memories": count,
                "by_type": type_counts,
                "cached_repetitions": len(self._repetition_cache),
                "pending_access_updates": len(self._pending_access_updates),
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
