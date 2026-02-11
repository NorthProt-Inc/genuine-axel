"""GraphRAG main class for querying the knowledge graph."""

import asyncio
import json
from typing import Dict, List, Optional, Any

from .utils import _log, GraphRAGConfig
from .knowledge_graph import KnowledgeGraph, Entity, Relation, GraphQueryResult
from .relationship_extractor import RelationshipExtractor


class GraphRAG:

    def __init__(
        self,
        client=None,
        model_name: str | None = None,
        graph: Optional[KnowledgeGraph] = None,
        config: Optional[GraphRAGConfig] = None,
        # Backward compat: accept model= kwarg
        model=None,
    ):
        if client is None and model is not None:
            # Legacy: extract .client from GenerativeModelWrapper
            client = getattr(model, "client", model)
        self.client = client
        self.model_name = model_name
        if not self.model_name:
            from backend.core.utils.gemini_client import get_model_name
            self.model_name = get_model_name()
        self.graph = graph or KnowledgeGraph()
        self.config = config or GraphRAGConfig()
        
        # Initialize relationship extractor
        self._extractor = RelationshipExtractor(
            client=self.client,
            model_name=self.model_name,
            graph=self.graph,
            config=self.config,
        )

    # Backward compatibility: expose internal methods
    def _extract_ner(self, text: str):
        """NER baseline extraction (delegates to extractor)."""
        return self._extractor._extract_ner(text)
    
    def _merge_ner_llm(self, ner_entities, llm_entities):
        """Merge NER and LLM entities (delegates to extractor)."""
        return self._extractor._merge_ner_llm(ner_entities, llm_entities)

    async def extract_and_store(
        self,
        text: str,
        source: str = "conversation",
        importance_threshold: float | None = None,
        timeout_seconds: Optional[float] = None
    ) -> Dict[str, Any]:
        """Extract entities and relations from text using LLM.

        Args:
            text: Source text for extraction
            source: Source identifier
            importance_threshold: Minimum importance to include
            timeout_seconds: Extraction timeout

        Returns:
            Dict with added entity/relation counts
        """
        return await self._extractor.extract_and_store(
            text=text,
            source=source,
            importance_threshold=importance_threshold,
            timeout_seconds=timeout_seconds,
        )

    async def query(
        self,
        query: str,
        max_entities: int | None = None,
        max_depth: int | None = None,
    ) -> GraphQueryResult:
        """Query graph for relevant entities and relations.

        Args:
            query: Natural language query
            max_entities: Maximum entities to return
            max_depth: Graph traversal depth

        Returns:
            GraphQueryResult with entities, relations, and context
        """
        cfg = self.config
        if max_entities is None:
            max_entities = cfg.max_entities
        if max_depth is None:
            max_depth = cfg.max_depth

        if not self.client:
            return GraphQueryResult(
                entities=[],
                relations=[],
                paths=[],
                context="",
                relevance_score=0.0
            )

        query_entities = await self._extract_query_entities(query)

        if not query_entities:

            words = query.lower().split()
            for word in words:
                if len(word) > 2:
                    matches = self.graph.find_entities_by_name(word)
                    query_entities.extend([m.id for m in matches[:2]])

        if not query_entities:
            return GraphQueryResult(
                entities=[],
                relations=[],
                paths=[],
                context="관련 엔티티를 찾을 수 없습니다.",
                relevance_score=0.0
            )

        related_entity_ids = set()
        for entity_id in query_entities[:cfg.max_query_entities]:
            neighbors = self.graph.get_neighbors(entity_id, depth=max_depth)
            related_entity_ids.update(neighbors)
            related_entity_ids.add(entity_id)

        entities = []
        for eid in list(related_entity_ids)[:max_entities]:
            entity = self.graph.get_entity(eid)
            if entity:
                entities.append(entity)

        relations = []
        for entity in entities:
            rels = self.graph.get_relations_for_entity(entity.id)
            relations.extend(rels)

        relations = list({r.id: r for r in relations}.values())

        paths = []
        entity_ids = [e.id for e in entities]
        for i, eid1 in enumerate(entity_ids[:cfg.max_query_entities]):
            for eid2 in entity_ids[i+1:cfg.max_query_entities + 1]:
                path = self.graph.find_path(eid1, eid2)
                if path and len(path) > 1:
                    paths.append(path)

        context = self._format_graph_context(entities, relations, paths)

        relevance_score = min(len(entities) * 0.2, 1.0)

        return GraphQueryResult(
            entities=entities,
            relations=relations[:cfg.max_relations],
            paths=paths[:cfg.max_paths],
            context=context,
            relevance_score=relevance_score
        )

    async def _extract_query_entities(self, query: str) -> List[str]:
        """Extract entity names from query using LLM."""
        prompt = f"""다음 질문에서 핵심 엔티티(이름, 개념, 도구 등)를 추출하세요.

질문: "{query}"

JSON 배열로 응답 (엔티티 이름만):
["엔티티1", "엔티티2"]
"""

        try:
            response = await asyncio.wait_for(
                self.client.aio.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                ),
                timeout=30.0,
            )

            raw = response.text if response.text else "[]"
            text = raw.replace("```json", "").replace("```", "").strip()
            entity_names = json.loads(text)

            # PERF-042: Batch entity lookup instead of N queries
            batch_results = self.graph.find_entities_by_names_batch(entity_names)
            entity_ids = []
            for name in entity_names:
                matches = batch_results.get(name, [])
                if matches:
                    entity_ids.append(matches[0].id)

            return entity_ids

        except Exception as e:
            _log.warning("Query entity extraction failed", error=str(e))
            return []

    def _format_graph_context(
        self,
        entities: List[Entity],
        relations: List[Relation],
        paths: List[List[str]]
    ) -> str:
        """Format graph data as human-readable context string."""
        parts = []

        cfg = self.config
        if entities:
            parts.append("###  관련 엔티티:")
            for e in entities[:cfg.max_format_entities]:
                props = ", ".join(f"{k}={v}" for k, v in e.properties.items()) if e.properties else ""
                parts.append(f"- **{e.name}** ({e.entity_type}){': ' + props if props else ''}")

        if relations:
            parts.append("\n###  관계:")
            # PERF-042: Batch entity lookups instead of N+1 queries
            source_ids = [r.source_id for r in relations[:cfg.max_format_relations]]
            target_ids = [r.target_id for r in relations[:cfg.max_format_relations]]
            all_ids = list(set(source_ids + target_ids))

            # Batch fetch entities
            entity_map = {}
            for eid in all_ids:
                entity = self.graph.get_entity(eid)
                if entity:
                    entity_map[eid] = entity

            for r in relations[:cfg.max_format_relations]:
                source = entity_map.get(r.source_id)
                target = entity_map.get(r.target_id)
                if source and target:
                    parts.append(f"- {source.name} --[{r.relation_type}]--> {target.name}")

        if paths:
            parts.append("\n###  연결 경로:")
            for path in paths[:3]:
                path_names = [self.graph.get_entity(eid).name if self.graph.get_entity(eid) else eid for eid in path]  # type: ignore[union-attr]
                parts.append(f"- {' → '.join(path_names)}")

        return "\n".join(parts) if parts else ""

    def query_sync(
        self,
        query: str,
        max_entities: int = 5,
        max_depth: int = 2
    ) -> GraphQueryResult:
        """Synchronous graph query using keyword matching.

        Args:
            query: Natural language query
            max_entities: Maximum entities to return
            max_depth: Graph traversal depth

        Returns:
            GraphQueryResult with entities, relations, and context
        """
        words = query.lower().split()
        # PERF-042: Batch entity name search instead of N DB queries
        search_words = [w for w in words if len(w) > 2]

        if not search_words:
            return GraphQueryResult(
                entities=[],
                relations=[],
                paths=[],
                context="",
                relevance_score=0.0
            )

        batch_results = self.graph.find_entities_by_names_batch(search_words)
        query_entities = []
        for word in search_words:
            matches = batch_results.get(word, [])
            query_entities.extend([m.id for m in matches[:2]])

        if not query_entities:
            return GraphQueryResult(
                entities=[],
                relations=[],
                paths=[],
                context="",
                relevance_score=0.0
            )

        related_entity_ids = set()
        for entity_id in query_entities[:3]:
            neighbors = self.graph.get_neighbors(entity_id, depth=max_depth)
            related_entity_ids.update(neighbors)
            related_entity_ids.add(entity_id)

        entities = []
        for eid in list(related_entity_ids)[:max_entities]:
            entity = self.graph.get_entity(eid)
            if entity:
                entities.append(entity)

        relations = []
        for entity in entities:
            rels = self.graph.get_relations_for_entity(entity.id)
            relations.extend(rels)

        relations = list({r.id: r for r in relations}.values())

        context = self._format_graph_context(entities, relations, [])

        relevance_score = min(len(entities) * 0.2, 1.0)

        return GraphQueryResult(
            entities=entities,
            relations=relations[:10],
            paths=[],
            context=context,
            relevance_score=relevance_score
        )

    def get_stats(self) -> Dict[str, Any]:
        """Get underlying knowledge graph statistics."""
        return self.graph.get_stats()
