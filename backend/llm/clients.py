"""Backward compatibility shim for backend.llm.clients.

This module re-exports all public names from the new modular structure
to maintain backward compatibility with existing code that imports from
`backend.llm.clients`.

New code should import from the specific modules:
- backend.llm.circuit_breaker: CircuitBreakerState, AdaptiveTimeout
- backend.llm.providers: LLMProvider, get_provider, get_all_providers
- backend.llm.base: BaseLLMClient, get_llm_client
- backend.llm.gemini_client: GeminiClient
- backend.llm.anthropic_client: AnthropicClient
"""

# For test compatibility - import error_monitor from core
from backend.core.logging.error_monitor import error_monitor

# Circuit breaker and timeout
from .circuit_breaker import (
    AdaptiveTimeout,
    CircuitBreakerState,
    _adaptive_timeout,
    _calculate_dynamic_timeout,
    API_CALL_TIMEOUT,
    STREAM_CHUNK_TIMEOUT,
    CIRCUIT_BREAKER_DURATION,
    FIRST_CHUNK_BASE_TIMEOUT,
)

# Provider configuration
from .providers import (
    LLMProvider,
    LLM_PROVIDERS,
    DEFAULT_PROVIDER,
    get_provider,
    get_all_providers,
    _gemini_schema_to_anthropic,
)

# Base client and factory
from .base import (
    BaseLLMClient,
    get_llm_client,
)

# Client implementations
from .gemini_client import GeminiClient
from .anthropic_client import AnthropicClient

# For backward compatibility, expose all public names
__all__ = [
    # Test compatibility
    "error_monitor",
    # Circuit breaker
    "AdaptiveTimeout",
    "CircuitBreakerState",
    "_adaptive_timeout",
    "_calculate_dynamic_timeout",
    "API_CALL_TIMEOUT",
    "STREAM_CHUNK_TIMEOUT",
    "CIRCUIT_BREAKER_DURATION",
    "FIRST_CHUNK_BASE_TIMEOUT",
    # Providers
    "LLMProvider",
    "LLM_PROVIDERS",
    "DEFAULT_PROVIDER",
    "get_provider",
    "get_all_providers",
    "_gemini_schema_to_anthropic",
    # Base
    "BaseLLMClient",
    "get_llm_client",
    # Clients
    "GeminiClient",
    "AnthropicClient",
]
