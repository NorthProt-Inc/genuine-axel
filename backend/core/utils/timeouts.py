"""Timeout configuration — backward-compatible wrapper.

All canonical timeout values now live in backend.config (TIMEOUT_* constants).
This module reads the same environment variables to avoid circular imports,
while providing the frozen Timeouts dataclass for existing callers.

Prefer importing TIMEOUT_* directly from backend.config for new code.
"""

import os
from dataclasses import dataclass


def _env_int(name: str, default: int) -> int:
    """Read int from env var (mirrors config._get_int_env without import)."""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    """Read float from env var (mirrors config._get_float_env without import)."""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Timeouts:
    """Backward-compatible timeout container backed by env vars.

    Same env vars as backend.config TIMEOUT_* constants.
    """

    API_CALL: int = _env_int("TIMEOUT_API_CALL", 180)
    STREAM_CHUNK: int = _env_int("TIMEOUT_STREAM_CHUNK", 60)
    FIRST_CHUNK_BASE: int = _env_int("TIMEOUT_FIRST_CHUNK_BASE", 100)

    DEEP_RESEARCH: int = _env_int("TIMEOUT_DEEP_RESEARCH", 600)

    HTTP_DEFAULT: float = _env_float("TIMEOUT_HTTP_DEFAULT", 30.0)
    HTTP_CONNECT: float = _env_float("TIMEOUT_HTTP_CONNECT", 5.0)

    HTTP_HASS: float = _env_float("HASS_TIMEOUT", 10.0)
    HTTP_DEEPGRAM: float = 30.0

    CIRCUIT_BREAKER_DEFAULT: int = 30
    CIRCUIT_BREAKER_RATE_LIMIT: int = 300
    CIRCUIT_BREAKER_SERVER_ERROR: int = 60


TIMEOUTS = Timeouts()

SERVICE_TIMEOUTS: dict[str, float] = {
    "hass": TIMEOUTS.HTTP_HASS,
    "deepgram": TIMEOUTS.HTTP_DEEPGRAM,
    "tts": _env_float("TTS_SYNTHESIS_TIMEOUT", 30.0) + 5.0,
    "default": TIMEOUTS.HTTP_DEFAULT,
}
