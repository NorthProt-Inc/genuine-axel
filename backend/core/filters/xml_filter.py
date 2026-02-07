"""
XML tag filtering for LLM stream output.

Filters internal control tags and MCP tool call artifacts from streaming responses.
"""

import re
from typing import FrozenSet

# === Tag Constants (분리하여 동적 로드 가능하도록) ===

INTERNAL_TAGS: FrozenSet[str] = frozenset({
    "attempt_completion",
    "result",
    "thought",
    "thinking",
    "reflection",
    "function_call",
    "tool_call",
    "tool_result",
    "tool_use",
    "antthinking",
    "search_quality_reflection",
    "search_quality_score",
})

MCP_TOOL_TAGS: FrozenSet[str] = frozenset({
    # File/System tools
    "list_directory",
    "run_command",
    "read_file",
    "get_source_code",
    "search_codebase",
    # Memory tools
    "retrieve_context",
    "store_memory",
    "add_memory",
    "query_axel_memory",
    # Research tools
    "web_search",
    "visit_webpage",
    "deep_research",
    "tavily_search",
    "google_deep_research",
    # Home Assistant tools
    "hass_control_light",
    "hass_control_device",
    "hass_read_sensor",
    "hass_get_state",
    "hass_list_entities",
    # Other tools
    "delegate_to_opus",
    "read_system_logs",
    "analyze_log_errors",
})

MCP_PARAM_TAGS: FrozenSet[str] = frozenset({
    # Home Assistant params
    "entity_id",
    "brightness",
    "color",
    # File params
    "file_pattern",
    "file_paths",
    # Memory params
    "category",
    "importance",
    # Generic invoke params
    "invoke",
    "parameters",
    "arguments",
})

# === Compiled Patterns ===

def _build_tag_pattern() -> re.Pattern:
    """Build the XML tag stripping pattern from tag sets."""
    all_tags = INTERNAL_TAGS | MCP_TOOL_TAGS | MCP_PARAM_TAGS
    # Add call: prefix pattern
    tag_pattern = "|".join(re.escape(tag) for tag in sorted(all_tags))
    pattern = (
        r'</?(?:'
        + tag_pattern
        + r'|call:[^>]+'  # call:* prefix tags
        + r')[^>]*>'
    )
    return re.compile(pattern, re.IGNORECASE | re.DOTALL)


_XML_TAG_PATTERN = _build_tag_pattern()

# Pattern to detect complete tool call blocks that should be intercepted
_TOOL_BLOCK_PATTERN = re.compile(
    r'<(?:function_call|tool_call|tool_use|invoke)[^>]*>.*?</(?:function_call|tool_call|tool_use|invoke)>',
    re.IGNORECASE | re.DOTALL
)

# Pattern to detect partial/incomplete tool call opening tags (buffering needed)
_PARTIAL_TOOL_PATTERN = re.compile(
    r'<(?:function_call|tool_call|tool_use|invoke|call:)[^>]*$',
    re.IGNORECASE
)


# === Public Functions ===

def strip_xml_tags(text: str) -> str:
    """
    Strip XML-style control tags from LLM output, preserving content.

    Args:
        text: Raw LLM output text

    Returns:
        Cleaned text with XML tags removed
    """
    if not text:
        return text

    # First, remove complete tool call blocks entirely (these are leaked tool calls)
    cleaned = _TOOL_BLOCK_PATTERN.sub('', text)

    # Then remove individual XML tags, keeping the content between them
    cleaned = _XML_TAG_PATTERN.sub('', cleaned)

    # Clean up excessive blank lines left behind
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)

    return cleaned.strip('\n')


def has_partial_tool_tag(text: str) -> bool:
    """
    Check if text ends with a partial tool call tag that needs buffering.

    Args:
        text: Text to check

    Returns:
        True if text ends with incomplete tool tag
    """
    if not text:
        return False
    # Check last 100 chars for partial opening tag
    tail = text[-100:] if len(text) > 100 else text
    return bool(_PARTIAL_TOOL_PATTERN.search(tail))


def get_all_filter_tags() -> FrozenSet[str]:
    """Get all tags that will be filtered (for debugging/testing)."""
    return INTERNAL_TAGS | MCP_TOOL_TAGS | MCP_PARAM_TAGS
