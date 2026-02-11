"""Zero-cost keyword-based intent classifier with fallback chain support."""

from dataclasses import dataclass
from enum import Enum

from backend.core.logging import get_logger

_log = get_logger("core.intent")


class IntentType(str, Enum):
    CHAT = "chat"
    SEARCH = "search"
    TOOL_USE = "tool_use"
    MEMORY_QUERY = "memory_query"
    COMMAND = "command"
    CREATIVE = "creative"


@dataclass
class IntentResult:
    """Classification result."""

    intent: str
    confidence: float
    source: str  # "keyword" or "llm"


KEYWORD_MAP: dict[str, dict] = {
    "command": {
        "prefix": "/",
        "keywords": [
            "해줘", "만들어", "삭제", "수정", "추가", "변경",
            "create", "update", "add", "change",
            "remove", "run", "execute",
        ],
        "confidence": 0.7,
    },
    "memory_query": {
        "keywords": [
            "기억", "remember", "recall", "지난번", "예전에",
            "last time", "before", "이전에", "알고 있",
        ],
        "confidence": 0.65,
    },
    "creative": {
        "keywords": [
            "써줘", "작성", "글", "시를", "이야기", "소설",
            "write", "compose", "poem", "story", "draft", "essay",
        ],
        "confidence": 0.6,
    },
    "tool_use": {
        "keywords": [
            "파일", "검색", "조회", "실행", "열어", "delete",
            "file", "search", "lookup", "open", "browse",
        ],
        "confidence": 0.55,
    },
    "search": {
        "keywords": [
            "?", "뭐", "어떻게", "왜", "언제", "어디", "누가",
            "what", "how", "why", "when", "where", "who",
        ],
        "confidence": 0.6,
    },
}


def classify_keyword(text: str) -> IntentResult:
    """Classify intent using keyword matching.

    Args:
        text: User input text

    Returns:
        IntentResult with intent, confidence, source
    """
    text_lower = text[:2000].strip()

    if not text_lower:
        return IntentResult("chat", 0.3, "keyword")

    if text_lower.startswith("/"):
        return IntentResult("command", 0.85, "keyword")

    for intent, config in KEYWORD_MAP.items():
        for kw in config.get("keywords", []):
            if kw in text_lower:
                return IntentResult(intent, config["confidence"], "keyword")

    return IntentResult("chat", 0.3, "keyword")
