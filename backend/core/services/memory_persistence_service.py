"""
Memory persistence service for ChatHandler.

Handles async memory storage to working memory, long-term memory, and GraphRAG.
"""

import asyncio
from typing import TYPE_CHECKING, Optional, Dict, Any

from backend.core.logging import get_logger
from backend.core.services.emotion_service import classify_emotion_sync
from backend.memory import calculate_importance_sync

if TYPE_CHECKING:
    from backend.memory.unified import MemoryManager
    from backend.memory.permanent import LongTermMemory
    from backend.core.identity.ai_brain import IdentityManager

_log = get_logger("services.persistence")


class MemoryPersistenceService:
    """Service for persisting conversation data to memory systems."""

    def __init__(
        self,
        memory_manager: Optional['MemoryManager'] = None,
        long_term_memory: Optional['LongTermMemory'] = None,
        identity_manager: Optional['IdentityManager'] = None
    ):
        """Initialize persistence service.

        Args:
            memory_manager: Unified memory manager
            long_term_memory: Long-term memory storage
            identity_manager: Identity/persona manager
        """
        self.memory_manager = memory_manager
        self.long_term = long_term_memory
        self.identity_manager = identity_manager

    async def persist_all(
        self,
        user_input: str,
        response: str
    ) -> Dict[str, Any]:
        """
        Persist conversation to all available memory systems.

        Args:
            user_input: User's message
            response: Assistant's response

        Returns:
            Dict with results from each persistence operation
        """
        results = {
            "working_saved": False,
            "longterm_id": None,
            "graph_result": None,
            "errors": []
        }

        # Save working memory
        if self.memory_manager and self.memory_manager.is_working_available():
            try:
                saved = await self.memory_manager.save_working_to_disk()
                results["working_saved"] = saved
                if saved:
                    _log.debug(
                        "BG working saved",
                        turns=self.memory_manager.get_turn_count()
                    )
            except Exception as e:
                _log.warning("BG working save fail", error=str(e))
                results["errors"].append(f"working: {str(e)}")

        # Run long-term and graph tasks in parallel
        tasks = []

        if self.long_term:
            tasks.append(("longterm", self._store_longterm(user_input, response)))

        if self.memory_manager and self.memory_manager.is_graph_rag_available():
            tasks.append(("graph", self._extract_graph(user_input, response)))

        if tasks:
            task_results = await asyncio.gather(
                *[t[1] for t in tasks],
                return_exceptions=True
            )

            for i, (name, _) in enumerate(tasks):
                result = task_results[i]
                if isinstance(result, Exception):
                    _log.warning("BG task fail", task=name, error=str(result)[:100])
                    results["errors"].append(f"{name}: {str(result)}")
                elif name == "longterm":
                    results["longterm_id"] = result
                elif name == "graph":
                    results["graph_result"] = result

        return results

    async def _store_longterm(
        self,
        user_input: str,
        response: str
    ) -> Optional[str]:
        """Store conversation to long-term memory."""
        try:
            persona_summary = ""
            if self.identity_manager:
                persona_summary = self.identity_manager.persona.get("core_identity", "")

            def store_to_longterm():
                importance = calculate_importance_sync(
                    user_input, response, persona_context=persona_summary
                )
                memory_id = self.long_term.add(
                    content=f"User: {user_input}\nAI: {response}",
                    memory_type="conversation",
                    importance=importance,
                    source_session=None
                )
                return memory_id

            memory_id = await asyncio.to_thread(store_to_longterm)
            if memory_id:
                _log.debug(
                    "BG longterm stored",
                    memory_id=memory_id[:8] if memory_id else None
                )
            return memory_id

        except Exception as e:
            _log.warning("BG longterm fail", error=str(e)[:100])
            return None

    async def _extract_graph(
        self,
        user_input: str,
        response: str
    ) -> Dict[str, Any]:
        """Extract and store graph relationships."""
        try:
            combined = f"User: {user_input}\nAssistant: {response}"
            result = await self.memory_manager.graph_rag.extract_and_store(
                combined,
                source="conversation",
                timeout_seconds=120
            )
            entities_added = result.get("entities_added", 0)
            if entities_added > 0:
                _log.debug(
                    "BG graph done",
                    entities=entities_added,
                    rels=result.get("relations_added", 0)
                )

                # W4-2: Feed back to M3 — increment connection_count for related memories
                if self.long_term:
                    await self._update_m3_connection_counts(user_input, entities_added)

            return result

        except Exception as e:
            _log.debug("BG graph skip", error=str(e)[:100])
            return {"error": str(e), "entities_added": 0, "relations_added": 0}

    async def _update_m3_connection_counts(
        self, query: str, new_entities: int
    ) -> None:
        """Update connection_count metadata on related M3 memories.

        Args:
            query: Original user input to find related memories
            new_entities: Number of newly extracted entities
        """
        try:
            related = await asyncio.to_thread(
                self.long_term.query, query, n_results=5
            )
            if not related:
                return

            for mem in related:
                doc_id = mem.get("id")
                metadata = mem.get("metadata", {})
                if not doc_id:
                    continue
                current_count = metadata.get("connection_count", 0)
                new_count = current_count + new_entities
                self.long_term._repository.update_metadata(
                    doc_id, {"connection_count": new_count}
                )

            _log.debug(
                "M3 connection_count updated",
                memories=len(related),
                increment=new_entities,
            )
        except Exception as e:
            _log.debug("M3 connection_count update fail", error=str(e)[:100])

    async def add_assistant_message(self, response: str) -> None:
        """Add assistant message to working memory."""
        if response and self.memory_manager:
            emotion = await asyncio.to_thread(classify_emotion_sync, response)
            self.memory_manager.add_message("assistant", response, emotional_context=emotion)
