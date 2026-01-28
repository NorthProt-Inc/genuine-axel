from dataclasses import dataclass
from typing import Dict

@dataclass(frozen=True)
class Timeouts:

    API_CALL: int = 180
    STREAM_CHUNK: int = 60
    FIRST_CHUNK_BASE: int = 100

    DEEP_RESEARCH: int = 600

    HTTP_DEFAULT: float = 30.0
    HTTP_CONNECT: float = 5.0

    HTTP_HASS: float = 10.0
    HTTP_DEEPGRAM: float = 30.0

    CIRCUIT_BREAKER_DEFAULT: int = 30
    CIRCUIT_BREAKER_RATE_LIMIT: int = 300
    CIRCUIT_BREAKER_SERVER_ERROR: int = 60

TIMEOUTS = Timeouts()

SERVICE_TIMEOUTS: Dict[str, float] = {
    "hass": TIMEOUTS.HTTP_HASS,
    "deepgram": TIMEOUTS.HTTP_DEEPGRAM,
    "default": TIMEOUTS.HTTP_DEFAULT,
}
