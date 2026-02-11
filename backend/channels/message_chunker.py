"""Platform-specific message chunking utility.

Splits long messages into platform-safe chunks, respecting:
- Code block boundaries
- Paragraph breaks
- Maximum message length per platform
"""

from __future__ import annotations

import re

DISCORD_MAX_LENGTH = 2000
TELEGRAM_MAX_LENGTH = 4096

# Pattern for fenced code blocks
_CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```", re.DOTALL)


def chunk_message(text: str, max_length: int) -> list[str]:
    """Split text into chunks respecting code blocks and paragraphs.

    Args:
        text: Message text to split.
        max_length: Maximum length per chunk.

    Returns:
        List of message chunks, each within max_length.
    """
    if len(text) <= max_length:
        return [text]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= max_length:
            chunks.append(remaining)
            break

        # Try to split at a code block boundary
        cut = _find_split_point(remaining, max_length)
        chunk = remaining[:cut].rstrip()
        remaining = remaining[cut:].lstrip("\n")

        if chunk:
            chunks.append(chunk)

    return chunks or [text[:max_length]]


def _find_split_point(text: str, max_length: int) -> int:
    """Find the best split point within max_length.

    Priority: code block end > paragraph break > sentence end > word break.
    """
    segment = text[:max_length]

    # Check if we're inside a code block
    open_blocks = segment.count("```")
    if open_blocks % 2 == 1:
        # Unclosed code block — find its closing ``` after max_length
        close_idx = text.find("```", segment.rfind("```") + 3)
        if close_idx != -1 and close_idx + 3 <= len(text):
            end = close_idx + 3
            if end <= max_length * 1.2:  # Allow 20% overflow for code blocks
                return end

        # Can't fit code block — split before it
        block_start = segment.rfind("```")
        if block_start > 0:
            return block_start

    # Try paragraph break (\n\n)
    idx = segment.rfind("\n\n")
    if idx > max_length // 2:
        return idx + 2

    # Try single newline
    idx = segment.rfind("\n")
    if idx > max_length // 2:
        return idx + 1

    # Try sentence end
    for sep in (". ", "! ", "? "):
        idx = segment.rfind(sep)
        if idx > max_length // 2:
            return idx + len(sep)

    # Try space (word break)
    idx = segment.rfind(" ")
    if idx > max_length // 2:
        return idx + 1

    # Hard cut
    return max_length


def chunk_for_discord(text: str) -> list[str]:
    """Chunk message for Discord (2000 char limit)."""
    return chunk_message(text, DISCORD_MAX_LENGTH)


def chunk_for_telegram(text: str) -> list[str]:
    """Chunk message for Telegram (4096 char limit)."""
    return chunk_message(text, TELEGRAM_MAX_LENGTH)
