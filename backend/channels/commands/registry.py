"""Inline command registry — parses user commands from message text.

Ported from OpenClaw's commands-registry pattern.
Supports inline directives like model selection and tool toggles.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class ParsedCommand:
    """Result of parsing a message for inline commands."""

    content: str
    model: str | None = None
    enable_search: bool = False
    tier: str | None = None
    raw_directives: dict[str, str] = field(default_factory=dict)


# Directive patterns: /model:claude, /search, /tier:pro
_DIRECTIVE_RE = re.compile(r"/(\w+)(?::(\S+))?")

# Known directive handlers
_MODEL_ALIASES: dict[str, str] = {
    "claude": "anthropic",
    "anthropic": "anthropic",
    "gemini": "gemini",
    "gpt": "openai",
    "openai": "openai",
}


def parse_message(text: str) -> ParsedCommand:
    """Parse inline directives from message text.

    Supported directives:
        /model:<name>  — Select LLM model (claude, gemini, gpt)
        /search        — Enable web search
        /tier:<name>   — Override tier (axel, pro)

    Args:
        text: Raw message text from user.

    Returns:
        ParsedCommand with extracted directives and cleaned content.
    """
    result = ParsedCommand(content=text)
    directives_found: list[str] = []

    for match in _DIRECTIVE_RE.finditer(text):
        key = match.group(1).lower()
        value = match.group(2)
        directives_found.append(match.group(0))

        if key == "model" and value:
            alias = value.lower()
            result.model = _MODEL_ALIASES.get(alias, alias)
            result.raw_directives["model"] = value

        elif key == "search":
            result.enable_search = True
            result.raw_directives["search"] = "true"

        elif key == "tier" and value:
            result.tier = value.lower()
            result.raw_directives["tier"] = value

    # Remove directives from content
    cleaned = text
    for d in directives_found:
        cleaned = cleaned.replace(d, "")
    result.content = cleaned.strip()

    return result
