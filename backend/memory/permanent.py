import chromadb
from backend.core.utils.gemini_wrapper import GenerativeModelWrapper
from backend.core.logging import get_logger
import os
import re
import time
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Set
import json
import uuid
import math
from backend.config import CHROMADB_PATH
from backend.core.utils.timezone import VANCOUVER_TZ, now_vancouver

_log = get_logger("memory.permanent")

class MemoryConfig:

    FLUSH_THRESHOLD = 50
    FLUSH_INTERVAL_SECONDS = 300

    BASE_DECAY_RATE = 0.005

    ACCESS_STABILITY_K = 0.3

    RELATION_RESISTANCE_K = 0.1

    MIN_RETENTION = 0.1

    REASSESS_AGE_HOURS = 168
    REASSESS_BATCH_SIZE = 50

    DECAY_RATE = 0.01

    MIN_REPETITIONS = 1
    MIN_IMPORTANCE = 0.25

    DUPLICATE_THRESHOLD = 0.90
    SIMILAR_THRESHOLD = 0.75

    DECAY_DELETE_THRESHOLD = 0.1
    PRESERVE_REPETITIONS = 3

    EMBEDDING_MODEL = "models/gemini-embedding-001"

def get_memory_age_hours(created_at: str) -> float:

    if not created_at:
        return 0
    try:
        created = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
        now = now_vancouver()
        if created.tzinfo is None:
            created = created.replace(tzinfo=VANCOUVER_TZ)
        return (now - created).total_seconds() / 3600
    except Exception:
        return 0

def apply_adaptive_decay(
    importance: float,
    created_at: str,
    access_count: int = 0,
    connection_count: int = 0,
    last_accessed: str = None
) -> float:

    if not created_at:
        return importance

    try:
        hours_passed = get_memory_age_hours(created_at)

        stability = 1 + MemoryConfig.ACCESS_STABILITY_K * math.log(1 + access_count)

        resistance = min(1.0, connection_count * MemoryConfig.RELATION_RESISTANCE_K)

        effective_rate = MemoryConfig.BASE_DECAY_RATE / stability * (1 - resistance)

        decayed = importance * math.exp(-effective_rate * hours_passed)

        if last_accessed:
            last_access_hours = get_memory_age_hours(last_accessed)

            if hours_passed > 168 and last_access_hours < 24:
                recency_boost = 1.3
                decayed = decayed * recency_boost
                _log.debug(
                    "Recency paradox boost applied",
                    memory_age_days=hours_passed / 24,
                    last_access_hours=last_access_hours
                )

        return max(decayed, importance * MemoryConfig.MIN_RETENTION)

    except Exception as e:
        _log.warning("Adaptive decay error", error=str(e), created_at=created_at)
        return importance

def get_connection_count(memory_id: str) -> int:

    try:
        from backend.memory.graph_rag import GraphRAG
        graph = GraphRAG()

        return graph.get_connection_count(memory_id)
    except Exception:

        return 0

IMPORTANCE_TIMEOUT_SECONDS = 120

async def calculate_importance_async(
    user_msg: str,
    ai_msg: str,
    persona_context: str = ""
) -> float:

    import asyncio
    from backend.core.utils.gemini_wrapper import get_gemini_wrapper

    try:
        model = get_gemini_wrapper()

        prompt = f"""다음 대화의 장기 기억 저장 중요도를 평가하세요.

대화:
User: {user_msg[:500]}
AI: {ai_msg[:500]}

페르소나 컨텍스트: {persona_context[:200] if persona_context else "없음"}

중요도 기준:
- 0.9+: 사용자 개인정보, 중요한 사실 (이름, 직업, 건강)
- 0.7-0.8: 선호도, 습관, 프로젝트 관련
- 0.5-0.6: 일반적인 대화, 정보 요청
- 0.3 이하: 인사, 잡담, 일시적 질문

숫자만 응답하세요 (예: 0.75):"""

        def _call_sync():
            response = model.generate_content_sync(
                contents=prompt,
                stream=False,
                timeout_seconds=IMPORTANCE_TIMEOUT_SECONDS
            )
            text = response.text.strip()

            import re
            match = re.search(r'(0\.\d+|1\.0|1)', text)
            if match:
                return float(match.group(1))
            return 0.7

        importance = await asyncio.to_thread(_call_sync)
        _log.debug("MEM importance", score=importance, input_len=len(user_msg))
        return importance

    except TimeoutError:
        _log.warning("MEM importance timeout", timeout=IMPORTANCE_TIMEOUT_SECONDS)
        return 0.7
    except Exception as e:
        _log.warning("MEM importance fail", error=str(e)[:100])
        return 0.7

def calculate_importance_sync(user_msg: str, ai_msg: str, persona_context: str = "") -> float:

    from backend.core.utils.gemini_wrapper import get_gemini_wrapper

    try:
        model = get_gemini_wrapper()

        prompt = f"""다음 대화의 장기 기억 저장 중요도를 평가하세요.

대화:
User: {user_msg[:500]}
AI: {ai_msg[:500]}

페르소나 컨텍스트: {persona_context[:200] if persona_context else "없음"}

중요도 기준:
- 0.9+: 사용자 개인정보, 중요한 사실 (이름, 직업, 건강)
- 0.7-0.8: 선호도, 습관, 프로젝트 관련
- 0.5-0.6: 일반적인 대화, 정보 요청
- 0.3 이하: 인사, 잡담, 일시적 질문

숫자만 응답하세요 (예: 0.75):"""

        response = model.generate_content_sync(
            contents=prompt,
            stream=False,
            timeout_seconds=IMPORTANCE_TIMEOUT_SECONDS
        )
        text = response.text.strip()

        match = re.search(r'(0\.\d+|1\.0|1)', text)
        if match:
            importance = float(match.group(1))
            _log.debug("MEM importance", score=importance, input_len=len(user_msg))
            return importance

        return 0.7

    except TimeoutError:
        _log.warning("MEM importance timeout", timeout=IMPORTANCE_TIMEOUT_SECONDS)
        return 0.7
    except Exception as e:
        _log.warning("MEM importance fail", error=str(e)[:100])
        return 0.7

class PromotionCriteria:

    @classmethod
    def should_promote(
        cls,
        content: str,
        repetitions: int = 1,
        importance: float = 0.5,
        force: bool = False
    ) -> tuple[bool, str]:

        if force:
            return True, "forced_promotion"

        if repetitions >= MemoryConfig.MIN_REPETITIONS:
            return True, f"repetitions:{repetitions}"

        if importance >= MemoryConfig.MIN_IMPORTANCE:
            return True, f"importance:{importance:.2f}"

        return False, f"low_importance:{importance:.2f}"

class LongTermMemory:

    def __init__(
        self,
        db_path: str = None,
        embedding_model: str = None
    ):
        self.db_path = db_path if db_path else str(CHROMADB_PATH)
        self.embedding_model = embedding_model or MemoryConfig.EMBEDDING_MODEL
        self.genai_client = None

        self.client = chromadb.PersistentClient(path=self.db_path)

        try:

            self.genai_wrapper = GenerativeModelWrapper(client_or_model=self.embedding_model)
            _log.debug("GenAI wrapper initialized for embeddings (with Fallback)")
        except Exception as e:
            _log.warning("GenAI wrapper init failed", error=str(e))
            self.genai_wrapper = None

        self.collection = self.client.get_or_create_collection(
            name="axnmihn_memory",
            metadata={"hnsw:space": "cosine"}
        )

        self._repetition_cache: Dict[str, int] = {}
        self._load_repetition_cache()

        self._pending_access_updates: Set[str] = set()
        self._last_flush_time: float = time.time()

    def _maybe_flush_access_updates(self) -> None:

        should_flush = False

        if len(self._pending_access_updates) >= MemoryConfig.FLUSH_THRESHOLD:
            should_flush = True
            _log.debug(
                "Auto-flush triggered (threshold)",
                pending=len(self._pending_access_updates),
                threshold=MemoryConfig.FLUSH_THRESHOLD
            )

        elapsed = time.time() - self._last_flush_time
        if elapsed >= MemoryConfig.FLUSH_INTERVAL_SECONDS and self._pending_access_updates:
            should_flush = True
            _log.debug(
                "Auto-flush triggered (interval)",
                elapsed_sec=round(elapsed, 1),
                interval=MemoryConfig.FLUSH_INTERVAL_SECONDS
            )

        if should_flush:
            self.flush_access_updates()

    _embedding_cache: Dict[str, List[float]] = {}
    _EMBEDDING_CACHE_SIZE = 256

    def _get_embedding(self, text: str, task_type: str = "retrieval_document") -> Optional[List[float]]:

        if not self.genai_wrapper:
            _log.warning("GenAI wrapper not available for embedding")
            return None

        cache_key = f"{hash(text[:500])}:{task_type}"

        if cache_key in self._embedding_cache:
            _log.debug("MEM embed cache_hit")
            return self._embedding_cache[cache_key]

        try:
            from backend.core.utils.rate_limiter import get_embedding_limiter
            limiter = get_embedding_limiter()

            max_retries = 3
            for attempt in range(max_retries):
                if limiter.try_acquire():
                    break

                if attempt < max_retries - 1:
                    _log.debug("Rate limit: waiting for token", attempt=attempt + 1)
                    time.sleep(0.5)
                else:
                    _log.warning("Rate limit: proceeding without token after retries")
        except ImportError:
            pass

        try:

            result = self.genai_wrapper.embed_content_sync(
                model=self.embedding_model,
                contents=text,
                task_type=task_type
            )
            embedding = result.embeddings[0].values

            if len(self._embedding_cache) >= self._EMBEDDING_CACHE_SIZE:

                oldest_key = next(iter(self._embedding_cache))
                del self._embedding_cache[oldest_key]

            self._embedding_cache[cache_key] = embedding
            return embedding
        except Exception as e:
            _log.error("Embedding generation failed", error=str(e),
                        model=self.embedding_model, text_len=len(text),
                        error_type=type(e).__name__)
            return None

    def _load_repetition_cache(self):

        try:
            results = self.collection.get(include=["metadatas"])
            for metadata in results.get('metadatas', []):
                if metadata:
                    key = self._get_content_key(metadata.get('content_hash', ''))
                    self._repetition_cache[key] = metadata.get('repetitions', 1)
            _log.debug("Repetition cache loaded", count=len(self._repetition_cache))
        except Exception as e:
            _log.error("Cache load error", error=str(e))

    def _get_content_key(self, content: str) -> str:

        import re

        text = content.lower().strip()

        particles = [
            '은', '는', '이', '가', '을', '를', '의', '에', '와', '과',
            '로', '으로', '에서', '까지', '부터', '도', '만', '뿐',
            '이다', '입니다', '이에요', '예요', '임', '임.',
            "'s", "is", "the", "a", "an"
        ]
        for p in particles:
            text = text.replace(p, '')

        text = re.sub(r'[^\w\s가-힣]', '', text)
        text = re.sub(r'\s+', ' ', text).strip()

        return text[:100]

    def add(
        self,
        content: str,
        memory_type: str,
        importance: float = 0.5,
        source_session: str = None,
        event_timestamp: str = None,
        force: bool = False
    ) -> Optional[str]:

        content_key = self._get_content_key(content)

        self._repetition_cache[content_key] = self._repetition_cache.get(content_key, 0) + 1
        repetitions = self._repetition_cache[content_key]

        should_store, reason = PromotionCriteria.should_promote(
            content=content,
            repetitions=repetitions,
            importance=importance,
            force=force
        )

        if not should_store:
            _log.debug("Memory rejected", reason=reason, preview=content[:50])
            return None

        existing = self._find_similar(content, threshold=MemoryConfig.DUPLICATE_THRESHOLD)
        if existing:

            self._update_repetitions(existing['id'], repetitions)
            _log.debug("Updated existing memory", id=existing['id'])
            return existing['id']

        embedding = self._get_embedding(content)
        if not embedding:
            _log.error("Memory storage failed: embedding generation failed",
                        preview=content[:80], importance=importance)
            return None

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
            self.collection.add(
                documents=[content],
                embeddings=[embedding],
                metadatas=[metadata],
                ids=[doc_id]
            )
            _log.info("MEM store", type=memory_type, content_len=len(content), id=doc_id[:8])
            return doc_id
        except Exception as e:
            _log.error("ChromaDB add failed", error=str(e), error_type=type(e).__name__, doc_id=doc_id)
            return None

    def _find_similar(self, content: str, threshold: float = 0.8) -> Optional[Dict]:

        embedding = self._get_embedding(content, task_type="retrieval_query")
        if not embedding:
            return None

        try:
            results = self.collection.query(
                query_embeddings=[embedding],
                n_results=1,
                include=["documents", "metadatas", "distances"]
            )

            if results['documents'] and results['distances']:
                distance = results['distances'][0][0]
                similarity = 1 - distance

                if similarity >= threshold:
                    return {
                        "id": results['ids'][0][0],
                        "content": results['documents'][0][0],
                        "metadata": results['metadatas'][0][0],
                        "similarity": similarity
                    }
        except Exception as e:
            _log.error("Similar search error", error=str(e))

        return None

    def _update_repetitions(self, doc_id: str, repetitions: int):

        try:
            self.collection.update(
                ids=[doc_id],
                metadatas=[{
                    "repetitions": repetitions,
                    "last_accessed": now_vancouver().isoformat()
                }]
            )
        except Exception as e:
            _log.error("Repetition update error", error=str(e), id=doc_id)

    def query(
        self,
        query_text: str,
        n_results: int = 5,
        memory_type: str = None,
        temporal_filter: dict = None
    ) -> List[Dict[str, Any]]:

        embedding = self._get_embedding(query_text, task_type="retrieval_query")
        if not embedding:
            return []

        try:

            where_clauses = []

            if memory_type:
                where_clauses.append({"type": memory_type})

            if temporal_filter and temporal_filter.get("chroma_filter"):
                chroma_filter = temporal_filter["chroma_filter"]

                if "$and" in chroma_filter:
                    where_clauses.extend(chroma_filter["$and"])

            if len(where_clauses) == 0:
                where_filter = None
            elif len(where_clauses) == 1:
                where_filter = where_clauses[0]
            else:
                where_filter = {"$and": where_clauses}

            fetch_count = max(n_results + 5, int(n_results * 1.5))
            results = self.collection.query(
                query_embeddings=[embedding],
                n_results=fetch_count,
                where=where_filter,
                include=["documents", "metadatas", "distances"]
            )

            from .temporal import boost_temporal_score

            memories = []
            documents = results.get('documents')
            if documents and documents[0]:
                for i, doc in enumerate(results['documents'][0]):
                    doc_id = results['ids'][0][i]

                    metadata = results['metadatas'][0][i] if results.get('metadatas') and results['metadatas'][0] else {}
                    if not metadata:
                        metadata = {}

                    base_relevance = 1 - results['distances'][0][i]

                    event_time = metadata.get('event_timestamp') or metadata.get('created_at') or metadata.get('timestamp', '')
                    access_count = metadata.get('access_count', 0)

                    decay_factor = apply_adaptive_decay(1.0, event_time, access_count=access_count)

                    semantic_score = base_relevance * decay_factor

                    if temporal_filter:
                        effective_score = boost_temporal_score(
                            base_score=semantic_score,
                            memory_date=event_time,
                            temporal_filter=temporal_filter,
                            boost_factor=0.4
                        )
                    else:
                        effective_score = semantic_score

                    self._pending_access_updates.add(doc_id)

                    memories.append({
                        "id": doc_id,
                        "content": doc,
                        "metadata": metadata,
                        "relevance": base_relevance,
                        "effective_score": effective_score,
                        "decay_factor": decay_factor,
                        "temporal_boosted": temporal_filter is not None
                    })

            memories.sort(key=lambda x: x['effective_score'], reverse=True)

            _log.debug("MEM qry", qry_len=len(query_text), res=len(memories), temporal=temporal_filter is not None)

            self._maybe_flush_access_updates()

            return memories[:n_results]

        except Exception as e:
            _log.error("Query error", error=str(e))
            return []

    def flush_access_updates(self) -> int:

        if not self._pending_access_updates:
            return 0

        ids_to_update = list(self._pending_access_updates)
        self._pending_access_updates.clear()
        self._last_flush_time = time.time()

        now = now_vancouver().isoformat()
        updated = 0

        try:

            for doc_id in ids_to_update:
                try:
                    self.collection.update(
                        ids=[doc_id],
                        metadatas=[{"last_accessed": now}]
                    )
                    updated += 1
                except Exception:
                    pass

            self._last_flush_time = time.time()

            if updated > 0:
                _log.debug("MEM flush", count=updated)

        except Exception as e:
            _log.error("Flush access updates failed", error=str(e))

        return updated

    def get_formatted_context(self, query: str, max_items: int = 5) -> str:

        memories = self.query(query, n_results=max_items)

        if not memories:
            return ""

        lines = []
        for m in memories:
            metadata = m['metadata']
            relevance = f"{m['relevance']:.0%}"

            if 'user_query' in metadata and 'ai_response' in metadata:
                content = f"User: {metadata['user_query']}\nAI: {metadata['ai_response']}"
                ts = metadata.get('timestamp', '')[:10]
                lines.append(f"[기억/대화 {ts} | {relevance}]\n{content}")

            else:
                mem_type = metadata.get('type', 'unknown')
                content = m['content']
                lines.append(f"[{mem_type}|{relevance}] {content}")

        return "\n".join(lines)

    def get_stats(self) -> Dict[str, Any]:

        try:
            count = self.collection.count()

            results = self.collection.get(include=["metadatas"])
            type_counts = {}
            for m in results.get('metadatas', []):
                if m:
                    t = m.get('type', 'unknown')
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

        self.flush_access_updates()

        report = {"deleted": 0, "preserved": 0, "checked": 0}

        try:
            all_memories = self.collection.get(include=["metadatas"])
            ids = all_memories.get('ids', [])
            metadatas = all_memories.get('metadatas', [])

            to_delete = []

            for doc_id, metadata in zip(ids, metadatas):
                if not metadata:
                    continue

                report["checked"] += 1

                created_at = metadata.get('created_at') or metadata.get('timestamp', '')
                importance = metadata.get('importance', 0.5)
                repetitions = metadata.get('repetitions', 1)
                access_count = metadata.get('access_count', 0)
                is_preserved = metadata.get('preserved', False)

                if is_preserved:
                    continue

                connection_count = get_connection_count(doc_id)
                decayed_importance = apply_adaptive_decay(
                    importance,
                    created_at,
                    access_count=access_count,
                    connection_count=connection_count
                )

                if (decayed_importance < MemoryConfig.DECAY_DELETE_THRESHOLD
                    and repetitions < 2
                    and access_count < 3):
                    to_delete.append(doc_id)
                    report["deleted"] += 1
                    continue

                if repetitions >= MemoryConfig.PRESERVE_REPETITIONS:
                    try:
                        self.collection.update(
                            ids=[doc_id],
                            metadatas=[{**metadata, "preserved": True}]
                        )
                        report["preserved"] += 1
                    except Exception as e:
                        _log.warning("Preserve update failed", error=str(e), id=doc_id)

            if to_delete:
                self.collection.delete(ids=to_delete)
                _log.info("Deleted faded memories", count=len(to_delete))

            _log.info("MEM consolidate", deleted=report["deleted"], preserved=report["preserved"])
            return report

        except Exception as e:
            _log.error("Consolidation error", error=str(e))
            return report

class LegacyMemoryMigrator:

    def __init__(
        self,
        old_db_path: str = None,
        new_long_term: LongTermMemory = None
    ):
        db_path = old_db_path if old_db_path else str(CHROMADB_PATH)
        self.old_client = chromadb.PersistentClient(path=db_path)
        self.new_long_term = new_long_term

    def analyze_existing(self) -> Dict[str, Any]:

        report = {
            "total": 0,
            "promotable": 0,
            "rejected": 0,
            "by_reason": {},
            "samples": {"promotable": [], "rejected": []}
        }

        try:

            collections = self.old_client.list_collections()

            for coll in collections:
                results = coll.get(include=["documents", "metadatas"])

                for i, doc in enumerate(results.get('documents', [])):
                    report["total"] += 1

                    metadata = results['metadatas'][i] if results.get('metadatas') else {}
                    importance = metadata.get('importance', 0.3)
                    repetitions = metadata.get('repetition_count', 1)

                    should_keep, reason = PromotionCriteria.should_promote(
                        content=doc,
                        repetitions=repetitions,
                        importance=importance
                    )

                    if should_keep:
                        report["promotable"] += 1
                        if len(report["samples"]["promotable"]) < 5:
                            report["samples"]["promotable"].append({
                                "content": doc[:100],
                                "reason": reason
                            })
                    else:
                        report["rejected"] += 1
                        if len(report["samples"]["rejected"]) < 5:
                            report["samples"]["rejected"].append({
                                "content": doc[:100],
                                "reason": reason
                            })

                    report["by_reason"][reason] = report["by_reason"].get(reason, 0) + 1

        except Exception as e:
            _log.error("Migration analysis error", error=str(e))

        return report

    def migrate(self, dry_run: bool = True) -> Dict[str, Any]:

        if not self.new_long_term and not dry_run:
            raise ValueError("new_long_term required for actual migration")

        report = self.analyze_existing()

        if dry_run:
            report["action"] = "dry_run"
            return report

        migrated = 0

        try:
            collections = self.old_client.list_collections()

            for coll in collections:
                results = coll.get(include=["documents", "metadatas"])

                for i, doc in enumerate(results.get('documents', [])):
                    metadata = results['metadatas'][i] if results.get('metadatas') else {}
                    importance = metadata.get('importance', 0.3)
                    repetitions = metadata.get('repetition_count', 1)

                    should_keep, reason = PromotionCriteria.should_promote(
                        content=doc,
                        repetitions=repetitions,
                        importance=importance
                    )

                    if should_keep:

                        mem_type = metadata.get('type', 'insight')
                        if mem_type == 'conversation':
                            mem_type = 'insight'

                        doc_id = self.new_long_term.add(
                            content=doc,
                            memory_type=mem_type,
                            importance=importance,
                            force=True
                        )

                        if doc_id:
                            migrated += 1

        except Exception as e:
            _log.error("Migration error", error=str(e))

        report["action"] = "migrated"
        report["migrated_count"] = migrated

        return report
