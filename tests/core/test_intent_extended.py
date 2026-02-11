"""Tests for Intent Classification extension (Wave 1.3).

Tests expanded intent types (6 intents) and fallback chain architecture.
"""

import pytest

from backend.core.intent.classifier import (
    IntentResult,
    IntentType,
    classify_keyword,
)
from backend.core.intent.fallback_chain import (
    IntentClassifier,
    ClassifierChain,
)


class TestIntentType:
    """Tests for the IntentType enum."""

    def test_has_six_intents(self):
        assert len(IntentType) == 6

    def test_all_intent_values(self):
        expected = {"chat", "search", "tool_use", "memory_query", "command", "creative"}
        actual = {it.value for it in IntentType}
        assert actual == expected


class TestIntentResult:

    def test_basic_creation(self):
        r = IntentResult(intent="chat", confidence=0.5, source="keyword")
        assert r.intent == "chat"
        assert r.confidence == 0.5
        assert r.source == "keyword"


class TestClassifyKeywordExpanded:
    """Tests for expanded keyword classification."""

    def test_slash_command(self):
        r = classify_keyword("/help")
        assert r.intent == "command"
        assert r.confidence >= 0.8

    def test_question_korean(self):
        r = classify_keyword("이것은 뭐야?")
        assert r.intent == "search"
        assert r.confidence >= 0.5

    def test_question_english(self):
        r = classify_keyword("what is this?")
        assert r.intent == "search"
        assert r.confidence >= 0.5

    def test_tool_command_korean(self):
        r = classify_keyword("파일 열어봐")
        assert r.intent == "tool_use"
        assert r.confidence >= 0.5

    def test_tool_command_english(self):
        r = classify_keyword("delete that file")
        assert r.intent == "tool_use"
        assert r.confidence >= 0.5

    def test_memory_query_korean(self):
        r = classify_keyword("기억해?")
        assert r.intent == "memory_query"
        assert r.confidence >= 0.5

    def test_memory_query_english(self):
        r = classify_keyword("do you remember our last talk?")
        assert r.intent == "memory_query"
        assert r.confidence >= 0.5

    def test_creative_korean(self):
        r = classify_keyword("poem 형태로 알려줘")
        assert r.intent == "creative"
        assert r.confidence >= 0.5

    def test_creative_english(self):
        r = classify_keyword("write me a poem")
        assert r.intent == "creative"
        assert r.confidence >= 0.5

    def test_default_chat(self):
        r = classify_keyword("안녕")
        assert r.intent == "chat"

    def test_empty_string(self):
        r = classify_keyword("")
        assert r.intent == "chat"

    def test_source_is_keyword(self):
        r = classify_keyword("hello there")
        assert r.source == "keyword"


class TestIntentClassifierProtocol:
    """Tests for the IntentClassifier protocol."""

    def test_protocol_compliance(self):
        class MyClassifier:
            def classify(self, text: str) -> IntentResult:
                return IntentResult("chat", 0.5, "custom")

        classifier = MyClassifier()
        assert isinstance(classifier, IntentClassifier)


class TestClassifierChain:
    """Tests for the fallback chain architecture."""

    def test_single_classifier(self):
        class HighConfidence:
            def classify(self, text: str) -> IntentResult:
                return IntentResult("search", 0.9, "test")

        chain = ClassifierChain([HighConfidence()])
        result = chain.classify("what is this?")
        assert result.intent == "search"
        assert result.confidence == 0.9

    def test_fallback_on_low_confidence(self):
        class LowConfidence:
            def classify(self, text: str) -> IntentResult:
                return IntentResult("chat", 0.2, "weak")

        class HighConfidence:
            def classify(self, text: str) -> IntentResult:
                return IntentResult("command", 0.8, "strong")

        chain = ClassifierChain(
            [LowConfidence(), HighConfidence()],
            min_confidence=0.5,
        )
        result = chain.classify("test")
        assert result.intent == "command"
        assert result.source == "strong"

    def test_uses_first_above_threshold(self):
        class Med:
            def classify(self, text: str) -> IntentResult:
                return IntentResult("search", 0.6, "med")

        class High:
            def classify(self, text: str) -> IntentResult:
                return IntentResult("command", 0.9, "high")

        chain = ClassifierChain([Med(), High()], min_confidence=0.5)
        result = chain.classify("test")
        assert result.intent == "search"
        assert result.source == "med"

    def test_empty_chain_returns_chat(self):
        chain = ClassifierChain([])
        result = chain.classify("anything")
        assert result.intent == "chat"
        assert result.confidence <= 0.3

    def test_all_low_uses_best(self):
        class Low1:
            def classify(self, text: str) -> IntentResult:
                return IntentResult("search", 0.2, "a")

        class Low2:
            def classify(self, text: str) -> IntentResult:
                return IntentResult("command", 0.3, "b")

        chain = ClassifierChain([Low1(), Low2()], min_confidence=0.5)
        result = chain.classify("test")
        assert result.confidence == 0.3
        assert result.intent == "command"

    def test_classifier_error_skipped(self):
        class Broken:
            def classify(self, text: str) -> IntentResult:
                raise RuntimeError("broken")

        class Working:
            def classify(self, text: str) -> IntentResult:
                return IntentResult("search", 0.8, "ok")

        chain = ClassifierChain([Broken(), Working()], min_confidence=0.5)
        result = chain.classify("test")
        assert result.intent == "search"

    def test_default_min_confidence(self):
        chain = ClassifierChain([])
        assert chain.min_confidence == 0.5
