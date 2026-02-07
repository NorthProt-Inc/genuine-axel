"""Text utilities for context building."""


def truncate_text(text: str | None, max_chars: int) -> str:
    """Truncate text to max_chars with suffix indicator.

    Args:
        text: Text to truncate, or None.
        max_chars: Maximum character count for the result.

    Returns:
        Original text if within limit, truncated text with suffix otherwise,
        or empty string for None/empty input or non-positive max_chars.
    """
    if not text or max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    suffix = "\n... (truncated)"
    keep = max_chars - len(suffix)
    if keep <= 0:
        return text[:max_chars]
    return text[:keep].rstrip() + suffix
