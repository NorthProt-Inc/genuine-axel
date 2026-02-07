from typing import Optional, Any, Protocol, TYPE_CHECKING, List
from dataclasses import dataclass, field
from fastapi import Request, HTTPException, status
from backend.core.logging import get_logger
from backend.config import AXNMIHN_API_KEY

if TYPE_CHECKING:
    from backend.memory.unified import MemoryManager
    from backend.core.identity.ai_brain import IdentityManager
    from backend.memory.permanent import LongTermMemory
    from backend.memory.graph_rag import GraphRAG

_logger = get_logger("api.deps")


class ChatStateProtocol(Protocol):
    """Protocol defining the state interface required by ChatHandler.

    This allows ChatHandler to work with any object that satisfies this interface,
    enabling better testing and decoupling.
    """

    @property
    def memory_manager(self) -> Optional['MemoryManager']:
        """Access to the unified memory manager."""
        ...

    @property
    def long_term_memory(self) -> Optional['LongTermMemory']:
        """Access to long-term memory storage."""
        ...

    @property
    def identity_manager(self) -> Optional['IdentityManager']:
        """Access to identity/persona manager."""
        ...

    @property
    def background_tasks(self) -> List:
        """List of background asyncio tasks."""
        ...

def _mask_key(key: Optional[str]) -> str:
    """Mask an API key for safe logging.

    Args:
        key: API key to mask

    Returns:
        Masked string showing only first/last characters
    """
    if not key:
        return "<empty>"
    if len(key) <= 8:
        return f"{key[:2]}...{key[-2:]}" if len(key) >= 4 else "***"
    return f"{key[:4]}...{key[-4:]}"

@dataclass
class AppState:
    """Application state container implementing ChatStateProtocol.

    This class holds all shared application state including memory managers,
    identity configuration, and background task tracking.
    """

    # Core memory components (satisfy ChatStateProtocol)
    memory_manager: Optional['MemoryManager'] = None
    long_term_memory: Optional['LongTermMemory'] = None
    identity_manager: Optional['IdentityManager'] = None

    # Additional services
    gemini_client: Any = None
    graph_rag: Optional['GraphRAG'] = None
    mcp_server: Any = None

    # Session tracking
    current_session_id: str = ""
    last_activity: Any = None
    turn_count: int = 0

    # Async management (satisfy ChatStateProtocol)
    background_tasks: List = field(default_factory=list)
    shutdown_event: Any = None

    # Stream tracking
    active_streams: List = field(default_factory=list)

    def reset(self) -> None:
        """Reset all fields to their defaults (in-place, preserves identity)."""
        self.memory_manager = None
        self.long_term_memory = None
        self.identity_manager = None
        self.gemini_client = None
        self.graph_rag = None
        self.mcp_server = None
        self.current_session_id = ""
        self.last_activity = None
        self.turn_count = 0
        self.background_tasks = []
        self.shutdown_event = None
        self.active_streams = []

state = AppState()

def get_state() -> AppState:
    """Get the global application state.

    Returns:
        Shared AppState instance
    """
    return state

def init_state(**kwargs):
    """Initialize application state with provided values.

    Args:
        **kwargs: State attributes to set (e.g., memory_manager, gemini_client)
    """
    global state
    for key, value in kwargs.items():
        if hasattr(state, key):
            setattr(state, key, value)

def _extract_bearer_token(auth_header: str) -> Optional[str]:
    """Extract token from Bearer authorization header.

    Args:
        auth_header: Full Authorization header value

    Returns:
        Token string if valid Bearer format, None otherwise
    """
    if not auth_header:
        return None

    if auth_header.lower().startswith("bearer "):
        return auth_header.split(" ", 1)[1].strip()
    return None

def get_request_api_key(request: Request) -> Optional[str]:
    """Extract API key from request headers.

    Checks Authorization Bearer token first, then X-API-Key header.

    Args:
        request: FastAPI request object

    Returns:
        API key if found, None otherwise
    """
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
    """Check if an API key is configured for authentication.

    Returns:
        True if AXNMIHN_API_KEY is set
    """
    configured = bool(AXNMIHN_API_KEY)
    _logger.debug(
        "API key configuration check",
        is_configured=configured,
        expected_key_masked=_mask_key(AXNMIHN_API_KEY)
    )
    return configured

def is_request_authorized(request: Request) -> bool:
    """Check if request has valid API key authorization.

    Bypasses check if no API key is configured.

    Args:
        request: FastAPI request object

    Returns:
        True if authorized or no auth required
    """
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
    """FastAPI dependency that enforces API key authentication.

    Args:
        request: FastAPI request object

    Raises:
        HTTPException: 401 if request is not authorized
    """
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
