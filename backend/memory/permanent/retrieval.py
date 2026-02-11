"""Memory retrieval operations - similarity search, embeddings, and formatting."""

from typing import Dict, List, Optional, Any

from backend.core.logging import get_logger

from .embedding_service import EmbeddingService
from .protocols import MemoryRepositoryProtocol, DecayCalculatorProtocol
from .promotion import _text_similarity

_log = get_logger("memory.permanent.retrieval")


class MemoryRetriever:
    """Handles memory retrieval operations.
    
    Provides similarity search, embedding generation, and result formatting.
    """

    def __init__(
        self,
        repository: MemoryRepositoryProtocol,
        embedding_service: EmbeddingService,
        decay_calculator: DecayCalculatorProtocol,
        meta_memory=None,
    ):
        """Initialize memory retriever.
        
        Args:
            repository: Repository for querying memories
            embedding_service: Service for generating embeddings
            decay_calculator: Calculator for memory decay
            meta_memory: Optional MetaMemory for hot memory boosting
        """
        self._repository = repository
        self._embedding_service = embedding_service
        self._decay_calculator = decay_calculator
        self._meta_memory = meta_memory

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
        embedding = self._embedding_service.get_embedding(
            content, task_type="retrieval_query"
        )
        if not embedding:
            return []

        results = self._repository.query_by_embedding(
            embedding=embedding,
            n_results=n_results * 2,  # Fetch extra for re-ranking
            include=["documents", "metadatas", "distances"],
        )

        # Hybrid scoring: 0.7 * vector + 0.3 * text
        for m in results:
            vector_score = m.get("similarity", 0)
            try:
                text_score = _text_similarity(content, m.get("content", ""))
            except Exception:
                text_score = 0.0
            m["similarity"] = 0.7 * vector_score + 0.3 * text_score

        # Re-sort by hybrid score
        results.sort(key=lambda x: x.get("similarity", 0), reverse=True)

        # Filter by threshold
        return [m for m in results if m.get("similarity", 0) >= threshold][:n_results]

    def find_similar_memory(
        self,
        content: str,
        threshold: float = 0.8,
        embedding: Optional[List[float]] = None,
    ) -> Optional[Dict]:
        """Find single most similar existing memory.

        Args:
            content: Content text to search for.
            threshold: Minimum similarity threshold (0-1).
            embedding: Pre-computed embedding to reuse. If None, a new
                embedding is generated with task_type ``retrieval_query``.
                
        Returns:
            Most similar memory or None
        """
        if embedding is None:
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

    def query(
        self,
        query_text: str,
        n_results: int = 5,
        memory_type: Optional[str] = None,
        temporal_filter: Optional[dict] = None,
        access_callback: Optional[callable] = None,
    ) -> List[Dict[str, Any]]:
        """Query memories by semantic similarity.

        Args:
            query_text: Query text
            n_results: Number of results
            memory_type: Filter by type
            temporal_filter: Temporal filter config
            access_callback: Callback to track access (receives doc_id)

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
            where_clauses: list[Dict[str, Any]] = []

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

            # W3-1: Get hot memory IDs for score boost
            hot_memory_ids: set[str] = set()
            if self._meta_memory:
                try:
                    hot_list = self._meta_memory.get_hot_memories(limit=20)
                    hot_memory_ids = {h["memory_id"] for h in hot_list}
                except Exception:
                    pass

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

                # W6-1: Apply importance weight (0.5-1.0 range)
                raw_importance = metadata.get("importance", 0.5)
                importance_weight = 0.5 + 0.5 * max(0.0, min(1.0, raw_importance))
                semantic_score *= importance_weight

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

                # W3-1: Hot memory boost
                is_hot = doc_id in hot_memory_ids
                if is_hot:
                    effective_score += 0.1

                # Track access
                if access_callback:
                    access_callback(doc_id)

                memories.append(
                    {
                        "id": doc_id,
                        "content": item.get("content", ""),
                        "metadata": metadata,
                        "relevance": base_relevance,
                        "effective_score": effective_score,
                        "decay_factor": decay_factor,
                        "importance_weight": importance_weight,
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

            return memories[:n_results]

        except Exception as e:
            _log.error("Query error", error=str(e))
            return []

    def get_formatted_context(
        self,
        query: str,
        max_items: int = 5,
        query_callback: Optional[callable] = None,
    ) -> str:
        """Get formatted context string for LLM.

        Args:
            query: Query text
            max_items: Maximum memories to include
            query_callback: Optional callback for querying (receives query, max_items)

        Returns:
            Formatted context string
        """
        if query_callback:
            memories = query_callback(query, max_items)
        else:
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

    def get_embedding(
        self,
        text: str,
        task_type: str = "retrieval_document",
    ) -> Optional[List[float]]:
        """Get embedding vector for text.

        Args:
            text: Text to embed
            task_type: Embedding task type

        Returns:
            Embedding vector or None
        """
        return self._embedding_service.get_embedding(text, task_type=task_type)
