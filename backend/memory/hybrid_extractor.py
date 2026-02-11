"""Protocol-based Hybrid Entity Extractor — NER → Decision Gate → LLM Refiner.

Ported from Axel's hybrid-entity-extractor (ADR-024 Part 1).
Provides a clean, DI-friendly alternative to the inline extraction in GraphRAG.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class ExtractedEntity:
    """An entity extracted from text."""

    name: str
    entity_type: str
    confidence: float
    source: str  # "ner" | "llm" | "merged"


@dataclass
class ExtractionResult:
    """Result of entity extraction."""

    entities: list[ExtractedEntity]
    relations: list[dict[str, str]] = field(default_factory=list)


@runtime_checkable
class NerExtractor(Protocol):
    """NER extractor interface — allows DI injection for testing."""

    def extract(self, text: str) -> list[ExtractedEntity]: ...


@runtime_checkable
class LlmRefiner(Protocol):
    """LLM refiner interface — allows DI injection for testing."""

    async def refine(
        self, text: str, candidates: list[ExtractedEntity]
    ) -> ExtractionResult: ...


@dataclass
class HybridConfig:
    """Configuration for hybrid extraction decision gate."""

    min_text_length_for_llm: int = 200
    min_confidence_threshold: float = 0.8


def merge_results(
    ner_entities: list[ExtractedEntity],
    llm_result: ExtractionResult,
) -> ExtractionResult:
    """Merge NER and LLM results.

    - LLM entities override NER on name match (case-insensitive)
    - Non-overlapping NER entities are preserved
    - LLM-only entities are added
    - Relations come from LLM result
    """
    llm_by_name: dict[str, ExtractedEntity] = {}
    for entity in llm_result.entities:
        llm_by_name[entity.name.lower()] = entity

    merged: list[ExtractedEntity] = []
    used_llm_keys: set[str] = set()

    for ner_entity in ner_entities:
        key = ner_entity.name.lower()
        llm_entity = llm_by_name.get(key)
        if llm_entity:
            merged.append(
                ExtractedEntity(
                    name=llm_entity.name,
                    entity_type=llm_entity.entity_type,
                    confidence=llm_entity.confidence,
                    source="merged",
                )
            )
            used_llm_keys.add(key)
        else:
            merged.append(ner_entity)

    for key, llm_entity in llm_by_name.items():
        if key not in used_llm_keys:
            merged.append(llm_entity)

    return ExtractionResult(entities=merged, relations=llm_result.relations)


class HybridEntityExtractor:
    """Hybrid entity extractor: NER baseline → decision gate → LLM refinement.

    Pipeline:
    - Mode 'ner-only': NER only, no LLM
    - Mode 'llm-only': LLM only, no NER
    - Mode 'auto' (default): NER first, LLM called if text is long or confidence low
    Falls back to NER results on LLM failure.
    """

    def __init__(
        self,
        ner: NerExtractor,
        llm: LlmRefiner,
        config: HybridConfig | None = None,
    ) -> None:
        self._ner = ner
        self._llm = llm
        self._config = config or HybridConfig()

    async def extract(
        self,
        text: str,
        mode: str = "auto",
    ) -> ExtractionResult:
        ner_entities = [] if mode == "llm-only" else self._ner.extract(text)

        if mode == "ner-only":
            return ExtractionResult(entities=ner_entities, relations=[])

        needs_llm = (
            mode == "llm-only"
            or len(text) >= self._config.min_text_length_for_llm
            or any(e.confidence < self._config.min_confidence_threshold for e in ner_entities)
        )

        if not needs_llm:
            return ExtractionResult(entities=ner_entities, relations=[])

        try:
            llm_result = await self._llm.refine(text, ner_entities)
            if mode == "llm-only":
                return llm_result
            return merge_results(ner_entities, llm_result)
        except Exception:
            return ExtractionResult(entities=ner_entities, relations=[])
