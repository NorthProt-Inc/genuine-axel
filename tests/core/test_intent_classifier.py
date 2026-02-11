"""Tests for intent classifier."""

import pytest
from backend.core.intent.classifier import classify_keyword, IntentResult


class TestIntentClassifier:

    def test_slash_command_detected(self):
        result = classify_keyword("/help")
        assert result.intent == "command"
        assert result.confidence == 0.85
        assert result.source == "keyword"

    def test_question_detected(self):
        result = classify_keyword("어떻게 해?")
        assert result.intent == "search"
        assert result.confidence == 0.6

    def test_command_detected(self):
        result = classify_keyword("이거 삭제해줘")
        assert result.intent == "command"

    def test_greeting_detected(self):
        result = classify_keyword("안녕하세요")
        assert result.intent == "chat"

    def test_default_is_chat(self):
        result = classify_keyword("오늘 날씨가 좋네")
        assert result.intent == "chat"
        assert result.confidence == 0.3
        assert result.source == "keyword"

    def test_english_question(self):
        result = classify_keyword("how does this work?")
        assert result.intent == "search"
