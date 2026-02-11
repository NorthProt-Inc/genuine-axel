"""LLM provider configuration and schema conversion utilities.

This module defines:
- LLMProvider: Configuration for each LLM provider (Google Gemini, Anthropic Claude, etc.)
- Provider registry and lookup functions
- Schema conversion utilities (e.g., Gemini → Anthropic format)
"""

import os
from dataclasses import dataclass
from typing import Any, Dict, List

from dotenv import load_dotenv

from backend.config import MODEL_NAME, ANTHROPIC_CHAT_MODEL

load_dotenv()


@dataclass
class LLMProvider:
    """Configuration for an LLM provider."""

    name: str
    model: str
    provider: str
    api_key_env: str
    icon: str
    supports_vision: bool = True
    supports_streaming: bool = True


# Provider registry
LLM_PROVIDERS: Dict[str, LLMProvider] = {
    "google": LLMProvider(
        name="Gemini 3 Flash",
        model=MODEL_NAME,
        provider="google",
        api_key_env="GEMINI_API_KEY",
        icon="",
        supports_vision=True,
    ),
    "anthropic": LLMProvider(
        name="Claude Sonnet 4.5",
        model=ANTHROPIC_CHAT_MODEL,
        provider="anthropic",
        api_key_env="ANTHROPIC_API_KEY",
        icon="",
        supports_vision=True,
    ),
}

DEFAULT_PROVIDER = "anthropic"


def get_provider(name: str) -> LLMProvider:
    """Get provider configuration by name.

    Args:
        name: Provider key (e.g., "google", "anthropic")

    Returns:
        LLMProvider instance, falling back to DEFAULT_PROVIDER if not found
    """
    return LLM_PROVIDERS.get(name, LLM_PROVIDERS[DEFAULT_PROVIDER])


def get_all_providers() -> List[Dict[str, Any]]:
    """Get list of all providers with availability status.

    Returns:
        List of provider dicts with id, name, icon, and availability
    """
    return [
        {
            "id": key,
            "name": p.name,
            "icon": p.icon,
            "available": bool(os.getenv(p.api_key_env)),
        }
        for key, p in LLM_PROVIDERS.items()
    ]


def _gemini_schema_to_anthropic(schema: dict[str, Any]) -> dict[str, Any]:
    """Convert Gemini UPPERCASED schema types to Anthropic lowercase.

    Args:
        schema: Gemini-format schema dict with UPPERCASE type values

    Returns:
        Schema dict with lowercase type values for Anthropic API
    """
    if not isinstance(schema, dict):
        return schema
    result: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "type" and isinstance(value, str):
            result[key] = value.lower()
        elif isinstance(value, dict):
            result[key] = _gemini_schema_to_anthropic(value)
        elif isinstance(value, list):
            result[key] = [
                _gemini_schema_to_anthropic(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            result[key] = value
    return result


__all__ = [
    "LLMProvider",
    "LLM_PROVIDERS",
    "DEFAULT_PROVIDER",
    "get_provider",
    "get_all_providers",
    "_gemini_schema_to_anthropic",
]
