import asyncio
import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple, Any
from datetime import datetime
from collections import defaultdict
from backend.core.logging import get_logger
from backend.config import KNOWLEDGE_GRAPH_PATH
from backend.core.utils.timezone import VANCOUVER_TZ, now_vancouver

_log = get_logger("memory.graph")

@dataclass
class Entity:

    id: str
    name: str
    entity_type: str
    properties: Dict[str, Any] = field(default_factory=dict)
    mentions: int = 1
    created_at: str = ""
    last_accessed: str = ""

    def __hash__(self):
        return hash(self.id)

@dataclass
class Relation:

    source_id: str
    target_id: str
    relation_type: str
    weight: float = 1.0
    context: str = ""
    created_at: str = ""

    @property
    def id(self) -> str:
        return f"{self.source_id}--{self.relation_type}-->{self.target_id}"

@dataclass
class GraphQueryResult:

    entities: List[Entity]
    relations: List[Relation]
    paths: List[List[str]]
    context: str
    relevance_score: float

class KnowledgeGraph:

    def __init__(self, persist_path: str = None):
        self.entities: Dict[str, Entity] = {}
        self.relations: Dict[str, Relation] = {}
        self.adjacency: Dict[str, Set[str]] = defaultdict(set)
        self.persist_path = persist_path if persist_path else str(KNOWLEDGE_GRAPH_PATH)

        self._load()

    def add_entity(self, entity: Entity) -> str:

        if entity.id in self.entities:

            existing = self.entities[entity.id]
            existing.mentions += 1
            existing.last_accessed = now_vancouver().isoformat()
            existing.properties.update(entity.properties)
        else:
            entity.created_at = now_vancouver().isoformat()
            entity.last_accessed = entity.created_at
            self.entities[entity.id] = entity

        return entity.id

    def add_relation(self, relation: Relation) -> str:

        if relation.source_id not in self.entities:
            _log.warning("Source entity not found", id=relation.source_id)
            return ""
        if relation.target_id not in self.entities:
            _log.warning("Target entity not found", id=relation.target_id)
            return ""

        if relation.id in self.relations:
            existing = self.relations[relation.id]
            existing.weight += 0.1
            return existing.id

        relation.created_at = now_vancouver().isoformat()
        self.relations[relation.id] = relation

        self.adjacency[relation.source_id].add(relation.target_id)
        self.adjacency[relation.target_id].add(relation.source_id)

        return relation.id

    def get_entity(self, entity_id: str) -> Optional[Entity]:

        return self.entities.get(entity_id)

    def find_entities_by_name(self, name: str) -> List[Entity]:

        name_lower = name.lower()
        return [
            e for e in self.entities.values()
            if name_lower in e.name.lower()
        ]

    def find_entities_by_type(self, entity_type: str) -> List[Entity]:

        return [
            e for e in self.entities.values()
            if e.entity_type == entity_type
        ]

    def get_neighbors(self, entity_id: str, depth: int = 1) -> Set[str]:

        if entity_id not in self.entities:
            return set()

        visited = {entity_id}
        frontier = {entity_id}

        for _ in range(depth):
            new_frontier = set()
            for node in frontier:
                for neighbor in self.adjacency[node]:
                    if neighbor not in visited:
                        visited.add(neighbor)
                        new_frontier.add(neighbor)
            frontier = new_frontier

        visited.discard(entity_id)
        return visited

    def get_relations_for_entity(self, entity_id: str) -> List[Relation]:

        return [
            r for r in self.relations.values()
            if r.source_id == entity_id or r.target_id == entity_id
        ]

    def find_path(self, source_id: str, target_id: str, max_depth: int = 3) -> List[str]:

        if source_id not in self.entities or target_id not in self.entities:
            return []

        if source_id == target_id:
            return [source_id]

        visited = {source_id}
        queue = [(source_id, [source_id])]

        while queue:
            current, path = queue.pop(0)

            if len(path) > max_depth:
                break

            for neighbor in self.adjacency[current]:
                if neighbor == target_id:
                    return path + [neighbor]

                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor]))

        return []

    def get_stats(self) -> Dict[str, Any]:

        type_counts = defaultdict(int)
        for e in self.entities.values():
            type_counts[e.entity_type] += 1

        return {
            "total_entities": len(self.entities),
            "total_relations": len(self.relations),
            "entity_types": dict(type_counts),
            "avg_connections": sum(len(v) for v in self.adjacency.values()) / max(len(self.adjacency), 1)
        }

    def save(self):

        import os
        os.makedirs(os.path.dirname(self.persist_path), exist_ok=True)

        data = {
            "entities": {
                k: {
                    "id": v.id,
                    "name": v.name,
                    "entity_type": v.entity_type,
                    "properties": v.properties,
                    "mentions": v.mentions,
                    "created_at": v.created_at,
                    "last_accessed": v.last_accessed
                }
                for k, v in self.entities.items()
            },
            "relations": {
                k: {
                    "source_id": v.source_id,
                    "target_id": v.target_id,
                    "relation_type": v.relation_type,
                    "weight": v.weight,
                    "context": v.context,
                    "created_at": v.created_at
                }
                for k, v in self.relations.items()
            }
        }

        with open(self.persist_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        _log.debug("MEM graph_save", entities=len(self.entities), rels=len(self.relations))

    def _load(self):

        import os
        if not os.path.exists(self.persist_path):
            return

        try:
            with open(self.persist_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            for k, v in data.get("entities", {}).items():
                self.entities[k] = Entity(**v)

            for k, v in data.get("relations", {}).items():
                rel = Relation(**v)
                self.relations[k] = rel
                self.adjacency[rel.source_id].add(rel.target_id)
                self.adjacency[rel.target_id].add(rel.source_id)

            _log.debug("MEM graph_load", entities=len(self.entities), rels=len(self.relations))

        except Exception as e:
            _log.warning("Failed to load graph", error=str(e))

class GraphRAG:

    def __init__(self, model=None, graph: KnowledgeGraph = None):
        self.model = model
        self.graph = graph or KnowledgeGraph()

    EXTRACTION_TIMEOUT_SECONDS = 120

    async def extract_and_store(
        self,
        text: str,
        source: str = "conversation",
        importance_threshold: float = 0.6,
        timeout_seconds: float = None
    ) -> Dict[str, Any]:

        if not self.model:
            return {"error": "Model not available", "entities_added": 0, "relations_added": 0}

        timeout = timeout_seconds or self.EXTRACTION_TIMEOUT_SECONDS

        prompt = f"""당신은 Axel, Mark(종민)의 AI 시스템 관리자입니다.
Mark는 Vancouver에 거주하는 UBC 편입 준비 중인 개발자이며, Northprot이라는
스타트업을 함께 준비하고 있습니다.

다음 대화에서 Mark와의 관계에서 **장기적으로 중요한** 엔티티만 추출하세요.

텍스트: "{text[:800]}"

추출 기준 (importance 점수):
- Mark의 개인정보, 습관, 건강 상태: 0.9+
- Northprot 프로젝트 관련: 0.85+
- 자주 사용하는 도구/기술 (VS Code, axnmihn, HASS 등): 0.8+
- 중요한 사람 (가족, Lyra 등): 0.8+
- 반복되는 선호도/취향: 0.7+
- 일시적인 개념, HTTP 헤더, 코드 스니펫:  무시 (importance: 0)

JSON 응답만 (설명 없이):
{{
    "entities": [
        {{"name": "엔티티명", "type": "person/concept/tool/preference/project", "importance": 0.0-1.0}}
    ],
    "relations": [
        {{"source": "엔티티1", "target": "엔티티2", "relation": "uses/likes/knows/manages"}}
    ]
}}

 importance < 0.6 인 엔티티는 자동 필터링됩니다.
 Mark의 삶에 직접적으로 관련된 것만 추출하세요.
"""

        try:

            response = await asyncio.to_thread(
                self.model.generate_content_sync,
                contents=prompt,
                stream=False,
                timeout_seconds=timeout
            )

            response_text = response.text.replace("```json", "").replace("```", "").strip()
            data = json.loads(response_text)

            added_entities = []
            filtered_entities = []
            added_relations = []

            entity_map = {}
            for e in data.get("entities", []):
                importance = float(e.get("importance", 0.5))

                if importance < importance_threshold:
                    filtered_entities.append(e.get("name", "unknown"))
                    continue

                entity_id = e["name"].lower().replace(" ", "_")
                entity = Entity(
                    id=entity_id,
                    name=e["name"],
                    entity_type=e.get("type", "concept"),
                    properties={"importance": importance}
                )
                self.graph.add_entity(entity)
                entity_map[e["name"]] = entity_id
                added_entities.append(entity_id)

            for r in data.get("relations", []):
                source_id = entity_map.get(r["source"])
                target_id = entity_map.get(r["target"])

                if source_id and target_id:
                    relation = Relation(
                        source_id=source_id,
                        target_id=target_id,
                        relation_type=r.get("relation", "related_to"),
                        context=r.get("context", "")
                    )
                    self.graph.add_relation(relation)
                    added_relations.append(relation.id)

            self.graph.save()

            result = {
                "entities_added": len(added_entities),
                "entities_filtered": len(filtered_entities),
                "relations_added": len(added_relations),
                "entities": added_entities,
                "relations": added_relations
            }

            _log.info("MEM graph_extract", entities=result["entities_added"], rels=result["relations_added"])
            return result

        except TimeoutError:
            _log.warning("MEM graph timeout", timeout=timeout)
            return {"error": "timeout", "entities_added": 0, "relations_added": 0}
        except json.JSONDecodeError as e:
            _log.warning("MEM graph json fail", error=str(e)[:100])
            return {"error": "json_parse", "entities_added": 0, "relations_added": 0}
        except Exception as e:
            _log.warning("MEM graph extract fail", error=str(e)[:100])
            return {"error": str(e), "entities_added": 0, "relations_added": 0}

    async def query(
        self,
        query: str,
        max_entities: int = 5,
        max_depth: int = 2
    ) -> GraphQueryResult:

        if not self.model:
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

        paths = []
        entity_ids = [e.id for e in entities]
        for i, eid1 in enumerate(entity_ids[:3]):
            for eid2 in entity_ids[i+1:4]:
                path = self.graph.find_path(eid1, eid2)
                if path and len(path) > 1:
                    paths.append(path)

        context = self._format_graph_context(entities, relations, paths)

        relevance_score = min(len(entities) * 0.2, 1.0)

        return GraphQueryResult(
            entities=entities,
            relations=relations[:10],
            paths=paths[:5],
            context=context,
            relevance_score=relevance_score
        )

    async def _extract_query_entities(self, query: str) -> List[str]:

        prompt = f"""다음 질문에서 핵심 엔티티(이름, 개념, 도구 등)를 추출하세요.

질문: "{query}"

JSON 배열로 응답 (엔티티 이름만):
["엔티티1", "엔티티2"]
"""

        try:

            response = await asyncio.to_thread(
                self.model.generate_content_sync,
                contents=prompt,
                stream=False
            )

            text = response.text.replace("```json", "").replace("```", "").strip()
            entity_names = json.loads(text)

            entity_ids = []
            for name in entity_names:
                matches = self.graph.find_entities_by_name(name)
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

        parts = []

        if entities:
            parts.append("###  관련 엔티티:")
            for e in entities[:5]:
                props = ", ".join(f"{k}={v}" for k, v in e.properties.items()) if e.properties else ""
                parts.append(f"- **{e.name}** ({e.entity_type}){': ' + props if props else ''}")

        if relations:
            parts.append("\n###  관계:")
            for r in relations[:5]:
                source = self.graph.get_entity(r.source_id)
                target = self.graph.get_entity(r.target_id)
                if source and target:
                    parts.append(f"- {source.name} --[{r.relation_type}]--> {target.name}")

        if paths:
            parts.append("\n###  연결 경로:")
            for path in paths[:3]:
                path_names = [self.graph.get_entity(eid).name if self.graph.get_entity(eid) else eid for eid in path]
                parts.append(f"- {' → '.join(path_names)}")

        return "\n".join(parts) if parts else ""

    def query_sync(
        self,
        query: str,
        max_entities: int = 5,
        max_depth: int = 2
    ) -> GraphQueryResult:

        words = query.lower().split()
        query_entities = []

        for word in words:
            if len(word) > 2:
                matches = self.graph.find_entities_by_name(word)
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

        return self.graph.get_stats()

__all__ = [
    "GraphRAG",
    "KnowledgeGraph",
    "Entity",
    "Relation",
    "GraphQueryResult",
]
