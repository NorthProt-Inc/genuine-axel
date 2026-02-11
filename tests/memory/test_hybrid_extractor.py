"""Tests for HybridEntityExtractor — decision gate pattern (Wave 4.2)."""

import pytest

from backend.memory.hybrid_extractor import (
    ExtractedEntity,
    ExtractionResult,
    HybridEntityExtractor,
    HybridConfig,
    merge_results,
)


class StubNER:
    """Stub NER extractor returning fixed entities."""

    def __init__(self, entities: list[ExtractedEntity]) -> None:
        self._entities = entities

    def extract(self, text: str) -> list[ExtractedEntity]:
        return self._entities


class StubLLM:
    """Stub LLM refiner returning fixed result."""

    def __init__(
        self,
        result: ExtractionResult | None = None,
        *,
        fail: bool = False,
    ) -> None:
        self._result = result or ExtractionResult(entities=[], relations=[])
        self._fail = fail
        self.called = False

    async def refine(
        self, text: str, candidates: list[ExtractedEntity]
    ) -> ExtractionResult:
        self.called = True
        if self._fail:
            raise RuntimeError("LLM failed")
        return self._result


class TestMergeResults:

    def test_llm_overrides_ner_on_name_match(self):
        ner = [ExtractedEntity(name="Alice", entity_type="CONCEPT", confidence=0.4, source="ner")]
        llm = ExtractionResult(
            entities=[ExtractedEntity(name="Alice", entity_type="PERSON", confidence=0.9, source="llm")],
            relations=[],
        )
        result = merge_results(ner, llm)
        assert len(result.entities) == 1
        assert result.entities[0].entity_type == "PERSON"
        assert result.entities[0].source == "merged"

    def test_non_overlapping_ner_preserved(self):
        ner = [ExtractedEntity(name="Bob", entity_type="PERSON", confidence=0.8, source="ner")]
        llm = ExtractionResult(
            entities=[ExtractedEntity(name="Python", entity_type="TOOL", confidence=0.9, source="llm")],
            relations=[],
        )
        result = merge_results(ner, llm)
        names = {e.name for e in result.entities}
        assert "Bob" in names
        assert "Python" in names

    def test_llm_only_entities_added(self):
        ner: list[ExtractedEntity] = []
        llm = ExtractionResult(
            entities=[ExtractedEntity(name="Rust", entity_type="TOOL", confidence=0.85, source="llm")],
            relations=[],
        )
        result = merge_results(ner, llm)
        assert len(result.entities) == 1
        assert result.entities[0].name == "Rust"

    def test_relations_from_llm(self):
        ner: list[ExtractedEntity] = []
        llm = ExtractionResult(
            entities=[], relations=[{"source": "A", "target": "B", "type": "uses"}]
        )
        result = merge_results(ner, llm)
        assert len(result.relations) == 1


class TestHybridEntityExtractor:

    @pytest.mark.asyncio
    async def test_ner_only_mode(self):
        ner = StubNER([ExtractedEntity(name="Alice", entity_type="PERSON", confidence=0.9, source="ner")])
        llm = StubLLM()
        extractor = HybridEntityExtractor(ner=ner, llm=llm, config=HybridConfig())

        result = await extractor.extract("short text", mode="ner-only")
        assert len(result.entities) == 1
        assert not llm.called

    @pytest.mark.asyncio
    async def test_llm_only_mode(self):
        ner = StubNER([])
        llm_result = ExtractionResult(
            entities=[ExtractedEntity(name="X", entity_type="CONCEPT", confidence=0.8, source="llm")],
            relations=[],
        )
        llm = StubLLM(result=llm_result)
        extractor = HybridEntityExtractor(ner=ner, llm=llm, config=HybridConfig())

        result = await extractor.extract("some text", mode="llm-only")
        assert llm.called
        assert len(result.entities) == 1

    @pytest.mark.asyncio
    async def test_auto_skips_llm_for_short_high_confidence(self):
        ner = StubNER([ExtractedEntity(name="Bob", entity_type="PERSON", confidence=0.95, source="ner")])
        llm = StubLLM()
        config = HybridConfig(min_text_length_for_llm=200)
        extractor = HybridEntityExtractor(ner=ner, llm=llm, config=config)

        result = await extractor.extract("short", mode="auto")
        assert not llm.called
        assert len(result.entities) == 1

    @pytest.mark.asyncio
    async def test_auto_calls_llm_for_long_text(self):
        ner = StubNER([ExtractedEntity(name="Bob", entity_type="PERSON", confidence=0.95, source="ner")])
        llm_result = ExtractionResult(
            entities=[ExtractedEntity(name="Bob", entity_type="PERSON", confidence=0.98, source="llm")],
            relations=[],
        )
        llm = StubLLM(result=llm_result)
        config = HybridConfig(min_text_length_for_llm=5)
        extractor = HybridEntityExtractor(ner=ner, llm=llm, config=config)

        result = await extractor.extract("this is long enough text", mode="auto")
        assert llm.called

    @pytest.mark.asyncio
    async def test_auto_calls_llm_for_low_confidence(self):
        ner = StubNER([ExtractedEntity(name="X", entity_type="CONCEPT", confidence=0.3, source="ner")])
        llm_result = ExtractionResult(
            entities=[ExtractedEntity(name="X", entity_type="TOOL", confidence=0.9, source="llm")],
            relations=[],
        )
        llm = StubLLM(result=llm_result)
        config = HybridConfig(min_text_length_for_llm=9999)
        extractor = HybridEntityExtractor(ner=ner, llm=llm, config=config)

        result = await extractor.extract("X", mode="auto")
        assert llm.called

    @pytest.mark.asyncio
    async def test_llm_failure_falls_back_to_ner(self):
        ner = StubNER([ExtractedEntity(name="Y", entity_type="PERSON", confidence=0.7, source="ner")])
        llm = StubLLM(fail=True)
        config = HybridConfig(min_text_length_for_llm=1)
        extractor = HybridEntityExtractor(ner=ner, llm=llm, config=config)

        result = await extractor.extract("text that triggers LLM", mode="auto")
        assert len(result.entities) == 1
        assert result.entities[0].name == "Y"
