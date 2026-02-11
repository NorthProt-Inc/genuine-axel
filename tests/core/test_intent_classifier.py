"""Tests for intent classifier."""

import pytest
from backend.core.intent.classifier import classify_keyword, IntentResult


class TestIntentClassifier:

    def test_slash_command_detected(self):
        result = classify_keyword("/help")
        assert result.intent == "command"
        assert result.confidence == 0.85
        assert result.source == "keyword"

    def test_question_is_chat_not_search(self):
        """일반 질문은 search가 아닌 chat으로 분류 — 검색은 LLM이 MCP 도구로 판단."""
        result = classify_keyword("어떻게 해?")
        assert result.intent == "chat"
        assert result.confidence == 0.3

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

    def test_english_question_is_chat(self):
        """영어 질문도 search가 아닌 chat으로 분류."""
        result = classify_keyword("how does this work?")
        assert result.intent == "chat"

    def test_casual_korean_not_search(self):
        """일상 대화는 검색 트리거하지 않음."""
        casual_inputs = ["뭐 했어?", "왜 그래?", "언제 왔어?", "잘 잤어?"]
        for text in casual_inputs:
            result = classify_keyword(text)
            assert result.intent == "chat", f"'{text}' should be chat, got {result.intent}"

    def test_tool_use_with_search_keyword(self):
        """'검색' 키워드는 tool_use로 분류됨."""
        result = classify_keyword("파일 검색해줘")
        assert result.intent in ("command", "tool_use")
