import json
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from backend.core.logging import get_logger

_log = get_logger("memory.memgpt")

from backend.config import (
    MAX_CONTEXT_TOKENS as CONFIG_MAX_CONTEXT_TOKENS,
    MEMORY_WORKING_BUDGET,
    MEMORY_LONG_TERM_BUDGET,
    MEMORY_SESSION_ARCHIVE_BUDGET,
)

@dataclass
class MemGPTConfig:

    max_context_tokens: int = CONFIG_MAX_CONTEXT_TOKENS
    working_budget: int = MEMORY_WORKING_BUDGET
    long_term_budget: int = MEMORY_LONG_TERM_BUDGET
    session_archive_budget: int = MEMORY_SESSION_ARCHIVE_BUDGET

    eviction_score_threshold: float = 0.3
    min_memories_keep: int = 3

    triage_enabled: bool = True
    triage_batch_size: int = 5

    max_similar_memories: int = 2

    semantic_threshold_days: int = 5
    min_episodic_repetitions: int = 1

DEFAULT_CONFIG = MemGPTConfig()

@dataclass
class ScoredMemory:

    id: str
    content: str
    score: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    token_estimate: int = 0

@dataclass
class SemanticKnowledge:

    knowledge: str
    confidence: float
    source_count: int
    topics: List[str] = field(default_factory=list)

class MemGPTManager:

    def __init__(self, long_term_memory, model=None, config: MemGPTConfig = None):
        self.long_term = long_term_memory
        self.model = model
        self.config = config or DEFAULT_CONFIG

    def context_budget_select(
        self,
        query: str,
        token_budget: int = None,
        candidate_memories: List[Dict] = None,
        temporal_filter: dict = None
    ) -> Tuple[List[ScoredMemory], int]:

        budget = token_budget or self.config.long_term_budget

        if candidate_memories is None:
            candidate_memories = self.long_term.query(
                query,
                n_results=20,
                temporal_filter=temporal_filter
            )

        if not candidate_memories:
            return [], 0

        scored = []
        for mem in candidate_memories:
            if not mem:
                continue

            content = mem.get('content') or ''
            token_est = len(content) // 4

            score = mem.get('effective_score', mem.get('relevance', 0.5))

            scored.append(ScoredMemory(
                id=mem.get('id', ''),
                content=mem.get('content', ''),
                score=score,
                metadata=mem.get('metadata', {}),
                token_estimate=token_est
            ))

        scored.sort(key=lambda x: x.score, reverse=True)

        selected = []
        used_tokens = 0
        topic_counts = {}

        for mem in scored:

            if used_tokens + mem.token_estimate > budget:
                continue

            topics = mem.metadata.get('key_topics', [])
            skip = False
            for topic in topics:
                if topic_counts.get(topic, 0) >= self.config.max_similar_memories:
                    skip = True
                    break

            if skip:
                continue

            selected.append(mem)
            used_tokens += mem.token_estimate

            for topic in topics:
                topic_counts[topic] = topic_counts.get(topic, 0) + 1

        _log.debug("MEM budget_select", candidates=len(scored), selected=len(selected), tokens=used_tokens)

        return selected, used_tokens

    def smart_eviction(self, dry_run: bool = True) -> Dict[str, Any]:

        from .permanent import (
            apply_adaptive_decay,
            get_memory_age_hours,
            get_connection_count
        )

        try:

            all_memories = self.long_term.collection.get(
                include=["documents", "metadatas"]
            )

            if not all_memories or not all_memories.get('ids'):
                return {"candidates": [], "total": 0, "evicted": 0}

            eviction_candidates = []

            for i, doc_id in enumerate(all_memories['ids']):
                metadata = all_memories['metadatas'][i] if all_memories['metadatas'] else {}
                content = all_memories['documents'][i] if all_memories['documents'] else ""

                importance = metadata.get('importance', 0.5)
                created_at = metadata.get('created_at', metadata.get('timestamp', ''))
                repetitions = metadata.get('repetitions', 1)
                access_count = metadata.get('access_count', 0)

                connection_count = get_connection_count(doc_id)

                decayed_score = apply_adaptive_decay(
                    importance,
                    created_at,
                    access_count=access_count,
                    connection_count=connection_count
                )
                age_hours = get_memory_age_hours(created_at)

                should_evict = (
                    decayed_score < self.config.eviction_score_threshold and
                    repetitions < 3 and
                    access_count < 3 and
                    age_hours > 24 * 7
                )

                if should_evict:
                    eviction_candidates.append({
                        "id": doc_id,
                        "content_preview": content[:100],
                        "decayed_score": decayed_score,
                        "original_importance": importance,
                        "age_days": age_hours / 24,
                        "repetitions": repetitions,
                        "access_count": access_count,
                        "connections": connection_count
                    })

            evicted_count = 0
            if not dry_run and eviction_candidates:

                total_memories = len(all_memories['ids'])
                max_evict = max(0, total_memories - self.config.min_memories_keep)
                to_evict = eviction_candidates[:max_evict]

                for candidate in to_evict:
                    try:
                        self.long_term.collection.delete(ids=[candidate['id']])
                        evicted_count += 1
                    except Exception as e:
                        _log.warning("Eviction failed", id=candidate['id'], error=str(e))

            result = {
                "total_memories": len(all_memories['ids']),
                "candidates": len(eviction_candidates),
                "evicted": evicted_count,
                "dry_run": dry_run,
                "eviction_list": eviction_candidates[:10]
            }

            _log.info("MEM eviction", candidates=len(eviction_candidates), evicted=evicted_count, dry=dry_run)

            return result

        except Exception as e:
            _log.error("Smart eviction error", error=str(e))
            return {"error": str(e)}

    async def episodic_to_semantic(
        self,
        min_age_days: int = None,
        min_repetitions: int = None,
        dry_run: bool = True
    ) -> Dict[str, Any]:

        min_age = min_age_days or self.config.semantic_threshold_days
        min_reps = min_repetitions or self.config.min_episodic_repetitions

        if not self.model:
            return {"error": "Model not available for semantic transformation"}

        from .permanent import get_memory_age_hours

        try:

            all_memories = self.long_term.collection.get(
                include=["documents", "metadatas"]
            )

            if not all_memories or not all_memories.get('ids'):
                return {"candidates": 0, "transformed": 0}

            topic_groups: Dict[str, List[Dict]] = {}

            for i, doc_id in enumerate(all_memories['ids']):
                metadata = all_memories['metadatas'][i] if all_memories['metadatas'] else {}
                content = all_memories['documents'][i] if all_memories['documents'] else ""

                created_at = metadata.get('created_at', metadata.get('timestamp', ''))
                age_hours = get_memory_age_hours(created_at)
                repetitions = metadata.get('repetitions', 1)
                memory_type = metadata.get('type', 'conversation')

                if memory_type == 'semantic':
                    continue

                if age_hours < min_age * 24:
                    continue
                if repetitions < min_reps:
                    continue

                topics = metadata.get('key_topics', ['general'])
                for topic in topics[:1]:
                    if topic not in topic_groups:
                        topic_groups[topic] = []
                    topic_groups[topic].append({
                        "id": doc_id,
                        "content": content,
                        "metadata": metadata
                    })

            transformations = []

            for topic, memories in topic_groups.items():
                if len(memories) < 2:
                    continue

                semantic = await self._extract_semantic_knowledge(topic, memories)

                if semantic and semantic.confidence > 0.5:
                    transformations.append({
                        "topic": topic,
                        "source_count": len(memories),
                        "knowledge": semantic.knowledge,
                        "confidence": semantic.confidence
                    })

                    if not dry_run:
                        self.long_term.add(
                            content=f"[Semantic Knowledge] {semantic.knowledge}",
                            memory_type="semantic",
                            importance=0.8,
                            force=True
                        )

            result = {
                "total_groups": len(topic_groups),
                "transformations": len(transformations),
                "dry_run": dry_run,
                "semantic_knowledge": transformations[:5]
            }

            _log.info("MEM episodic_to_semantic", groups=len(topic_groups), transformed=len(transformations), dry=dry_run)

            return result

        except Exception as e:
            _log.error("Semantic transformation error", error=str(e))
            return {"error": str(e)}

    async def _extract_semantic_knowledge(
        self,
        topic: str,
        memories: List[Dict]
    ) -> Optional[SemanticKnowledge]:

        memory_texts = "\n".join([
            f"- {m['content'][:200]}" for m in memories[:5]
        ])

        prompt = f"""다음은 '{topic}' 주제에 대한 여러 대화 기록입니다.
이 경험들에서 일반적인 지식이나 패턴을 추출해주세요.

## 대화 기록:
{memory_texts}

## 응답 형식 (JSON):
{{
    "knowledge": "일반화된 지식 (1-2문장)",
    "confidence": 0.0-1.0,
    "key_insight": "핵심 인사이트"
}}
"""

        try:
            response = self.model.generate_content_sync(
                contents=prompt,
                stream=False
            )

            text = response.text.replace("```json", "").replace("```", "").strip()
            data = json.loads(text)

            return SemanticKnowledge(
                knowledge=data.get("knowledge", ""),
                confidence=float(data.get("confidence", 0.5)),
                source_count=len(memories),
                topics=[topic]
            )

        except Exception as e:
            _log.warning("Semantic extraction failed", topic=topic, error=str(e))
            return None

__all__ = [
    "MemGPTManager",
    "MemGPTConfig",
    "ScoredMemory",
    "SemanticKnowledge",
    "DEFAULT_CONFIG",
]
