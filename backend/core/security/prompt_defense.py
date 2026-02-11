"""4-Layer Prompt Injection Defense."""

import re
from backend.core.logging import get_logger

_log = get_logger("core.security")

# Layer 1: Input sanitization patterns (pre-compiled for performance)
_CONTROL_CHAR_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f]')

_INJECTION_RES = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"you\s+are\s+now", re.IGNORECASE),
    re.compile(r"system\s*:", re.IGNORECASE),
    re.compile(r"<<<\s*system", re.IGNORECASE),
    re.compile(r"\x00", re.IGNORECASE),  # null bytes
    re.compile(r"forget\s+(all\s+)?previous", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?previous", re.IGNORECASE),
    re.compile(r"new\s+instructions?\s*:", re.IGNORECASE),
]

# Keep raw patterns for external consumers (backward compatibility)
INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"you\s+are\s+now",
    r"system\s*:",
    r"<<<\s*system",
    r"\x00",  # null bytes
    r"forget\s+(all\s+)?previous",
    r"disregard\s+(all\s+)?previous",
    r"new\s+instructions?\s*:",
]


def sanitize_input(text: str) -> str:
    """Remove control chars and known injection patterns."""
    cleaned = _CONTROL_CHAR_RE.sub('', text)
    for compiled_re in _INJECTION_RES:
        cleaned = compiled_re.sub('[FILTERED]', cleaned)
    return cleaned


def isolate_system_prompt(system: str) -> str:
    """Wrap system prompt with boundary markers."""
    return f"<<<SYSTEM_PROMPT_START>>>\n{system}\n<<<SYSTEM_PROMPT_END>>>"


def wrap_user_input(user_input: str) -> str:
    """Wrap user input with boundary markers."""
    return f"<<<USER_INPUT_START>>>\n{user_input}\n<<<USER_INPUT_END>>>"


# Layer 4: Output filtering patterns (pre-compiled)
_OUTPUT_FILTER_RES = [
    re.compile(r'sk-[a-zA-Z0-9-]{20,}'),
    re.compile(r'AIza[a-zA-Z0-9_-]{35}'),
    re.compile(r'ghp_[a-zA-Z0-9]{36}'),
    re.compile(r'xoxb-[a-zA-Z0-9-]+'),
]


def filter_output(text: str) -> str:
    """Redact sensitive patterns from output."""
    for compiled_re in _OUTPUT_FILTER_RES:
        text = compiled_re.sub('[REDACTED_KEY]', text)
    return text
