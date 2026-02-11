"""Entity and relationship extraction using hybrid NER and LLM."""

import asyncio
import json
from typing import Dict, List, Optional, Tuple, Any

from backend.config import MEMORY_EXTRACTION_TIMEOUT

from .utils import _log, _HAS_SPACY, _nlp
from .knowledge_graph import Entity, Relation


# Extraction constants
MIN_TEXT_LENGTH_FOR_LLM = 200
EXTRACTION_TIMEOUT_SECONDS = MEMORY_EXTRACTION_TIMEOUT

# T-06: NER type mapping (spaCy label → our entity_type)
_NER_TYPE_MAP = {
    "PERSON": "person",
    "ORG": "project",
    "GPE": "concept",
    "LOC": "concept",
    "PRODUCT": "tool",
    "WORK_OF_ART": "concept",
    "EVENT": "concept",
    "LANGUAGE": "tool",
}


class RelationshipExtractor:
    """Handles entity and relationship extraction from text."""

    def __init__(self, client, model_name: str, graph, config):
        """Initialize the relationship extractor.
        
        Args:
            client: Gemini client for LLM calls
            model_name: Model name to use for extraction
            graph: KnowledgeGraph instance
            config: GraphRAGConfig instance
        """
        self.client = client
        self.model_name = model_name
        self.graph = graph
        self.config = config

    def _map_ner_type(self, label: str) -> str:
        """Map spaCy NER label to our entity type."""
        return _NER_TYPE_MAP.get(label, "concept")

    def _extract_ner(self, text: str) -> Tuple[List[dict], float]:
        """NER baseline extraction using spaCy.

        Returns:
            Tuple of (entities list, average confidence)
        """
        if not _HAS_SPACY or _nlp is None:
            return [], 0.0

        doc = _nlp(text[:1000])
        entities = []
        total_conf = 0.0
        seen_names = set()
        for ent in doc.ents:
            name = ent.text.strip()
            if not name or name.lower() in seen_names:
                continue
            seen_names.add(name.lower())
            entity = {
                "name": name,
                "type": self._map_ner_type(ent.label_),
                "importance": 0.7,
                "confidence": 0.85,
            }
            entities.append(entity)
            total_conf += entity["confidence"]
        avg_conf = total_conf / len(entities) if entities else 0.0
        return entities, avg_conf

    def _merge_ner_llm(
        self, ner_entities: List[dict], llm_entities: List[dict]
    ) -> List[dict]:
        """Merge NER and LLM entities. LLM overrides NER on name match."""
        llm_name_map = {e["name"].lower(): e for e in llm_entities}
        merged = list(llm_entities)  # LLM entities take priority
        for ner_e in ner_entities:
            if ner_e["name"].lower() not in llm_name_map:
                merged.append(ner_e)
        return merged

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
        if not self.client:
            return {"error": "Client not available", "entities_added": 0, "relations_added": 0}

        if importance_threshold is None:
            importance_threshold = self.config.importance_threshold
        timeout = timeout_seconds or EXTRACTION_TIMEOUT_SECONDS

        # T-06: Hybrid NER — Step 1: NER baseline
        ner_entities, ner_confidence = self._extract_ner(text)

        # T-06: Decision gate — skip LLM for short text with high NER confidence
        needs_llm = (
            len(text) >= MIN_TEXT_LENGTH_FOR_LLM
            or ner_confidence < 0.8
            or not ner_entities
        )

        if not needs_llm and ner_entities:
            # NER-only fast path
            _log.info(
                "Entity extraction",
                mode="ner_only",
                entities_found=len(ner_entities),
                llm_skipped=True,
            )
            added_entities = []
            for e in ner_entities:
                if float(e.get("importance", 0.5)) < importance_threshold:
                    continue
                entity_id = e["name"].lower().replace(" ", "_")
                entity = Entity(
                    id=entity_id,
                    name=e["name"],
                    entity_type=e.get("type", "concept"),
                    properties={"importance": float(e.get("importance", 0.7))},
                )
                self.graph.add_entity(entity)
                added_entities.append(entity_id)
            if added_entities:
                self.graph.save()
            return {
                "entities_added": len(added_entities),
                "entities_filtered": len(ner_entities) - len(added_entities),
                "relations_added": 0,
                "entities": added_entities,
                "relations": [],
                "extraction_mode": "ner_only",
            }

        # Hybrid / LLM path
        _log.info(
            "Entity extraction",
            mode="hybrid" if ner_entities else "llm_only",
            ner_entities=len(ner_entities),
            llm_skipped=False,
        )

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
            response = await asyncio.wait_for(
                self.client.aio.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                ),
                timeout=timeout,
            )

            raw_text = response.text if response.text else ""
            response_text = raw_text.replace("```json", "").replace("```", "").strip()
            data = json.loads(response_text)

            added_entities = []
            filtered_entities = []
            added_relations = []

            # T-06: Merge NER results with LLM results
            llm_entities = data.get("entities", [])
            if ner_entities:
                llm_entities = self._merge_ner_llm(ner_entities, llm_entities)

            entity_map = {}
            for e in llm_entities:
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
