from typing import Optional, Any
from dataclasses import dataclass, field
from fastapi import Request, HTTPException, status
from backend.core.logging import get_logger
from backend.config import AXNMIHN_API_KEY

_logger = get_logger("api.deps")

def _mask_key(key: Optional[str]) -> str:

    if not key:
        return "<empty>"
    if len(key) <= 8:
        return f"{key[:2]}...{key[-2:]}" if len(key) >= 4 else "***"
    return f"{key[:4]}...{key[-4:]}"

@dataclass
class AppState:

    memory_manager: Any = None
    long_term_memory: Any = None
    identity_manager: Any = None
    gemini_model: Any = None
    graph_rag: Any = None
    mcp_server: Any = None
    current_session_id: str = ""
    last_activity: Any = None
    turn_count: int = 0

    background_tasks: list = field(default_factory=list)
    shutdown_event: Any = None

    active_streams: list = field(default_factory=list)

state = AppState()

def get_state() -> AppState:

    return state

def init_state(**kwargs):

    global state
    for key, value in kwargs.items():
        if hasattr(state, key):
            setattr(state, key, value)

def _extract_bearer_token(auth_header: str) -> Optional[str]:

    if not auth_header:
        return None

    if auth_header.lower().startswith("bearer "):
        return auth_header.split(" ", 1)[1].strip()
    return None

def get_request_api_key(request: Request) -> Optional[str]:

    auth_header = request.headers.get("Authorization", "")

    token = _extract_bearer_token(auth_header)
    if token:
        _logger.debug(
            "API key extracted from Bearer token",
            key_masked=_mask_key(token),
            auth_header_prefix=auth_header[:20] + "..." if len(auth_header) > 20 else auth_header
        )
        return token

    x_api_key = request.headers.get("X-API-Key") or request.headers.get("X-Api-Key")
    if x_api_key:
        _logger.debug(
            "API key extracted from X-API-Key header",
            key_masked=_mask_key(x_api_key)
        )
        return x_api_key

    _logger.debug(
        "No API key found in request",
        has_auth_header=bool(auth_header),
        auth_header_value=auth_header[:30] + "..." if auth_header and len(auth_header) > 30 else auth_header
    )
    return None

def is_api_key_configured() -> bool:

    configured = bool(AXNMIHN_API_KEY)
    _logger.debug(
        "API key configuration check",
        is_configured=configured,
        expected_key_masked=_mask_key(AXNMIHN_API_KEY)
    )
    return configured

def is_request_authorized(request: Request) -> bool:

    if not AXNMIHN_API_KEY:
        _logger.debug("Auth bypassed: no AXNMIHN_API_KEY configured")
        return True

    request_key = get_request_api_key(request)
    is_match = request_key == AXNMIHN_API_KEY

    _logger.debug(
        "API key comparison",
        received_key_masked=_mask_key(request_key),
        expected_key_masked=_mask_key(AXNMIHN_API_KEY),
        is_match=is_match,
        received_len=len(request_key) if request_key else 0,
        expected_len=len(AXNMIHN_API_KEY)
    )

    return is_match

def require_api_key(request: Request) -> None:

    if not is_request_authorized(request):
        request_key = get_request_api_key(request)
        _logger.warning(
            "Unauthorized request",
            path=str(request.url.path),
            received_key_masked=_mask_key(request_key),
            expected_key_masked=_mask_key(AXNMIHN_API_KEY),
            hint="Check that client API key matches AXNMIHN_API_KEY in .env"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
        )
