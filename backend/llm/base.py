"""Base LLM client interface and factory function.

This module provides:
- BaseLLMClient: Abstract base class defining the LLM client interface
- get_llm_client: Factory function to instantiate provider-specific clients
"""

from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, List, Optional

from .providers import get_provider


class BaseLLMClient(ABC):
    """Abstract base class for LLM clients."""

    @abstractmethod
    async def generate_stream(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        images: Optional[List[Any]] = None,
        enable_thinking: bool = False,
        thinking_level: str = "high",
        tools: Optional[List[dict]] = None,
        force_tool_call: bool = False,
    ) -> AsyncGenerator[tuple, None]:
        """Generate a streaming response.

        Args:
            prompt: User prompt text
            system_prompt: System instructions
            temperature: Sampling temperature (0.0-1.0)
            max_tokens: Maximum tokens to generate
            images: Optional list of images to include
            enable_thinking: Whether to enable chain-of-thought reasoning
            thinking_level: Level of thinking ("low", "medium", "high")
            tools: Optional list of tool definitions
            force_tool_call: Whether to force a tool call

        Yields:
            Tuples of (text_chunk: str, is_thought: bool, function_call: dict | None)
        """
        yield  # type: ignore[misc]

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        images: Optional[List[Any]] = None,
    ) -> str:
        """Generate a non-streaming response.

        Args:
            prompt: User prompt text
            system_prompt: System instructions
            temperature: Sampling temperature (0.0-1.0)
            max_tokens: Maximum tokens to generate
            images: Optional list of images to include

        Returns:
            Generated text response
        """
        pass


def get_llm_client(provider_name: str, model: str | None = None) -> BaseLLMClient:
    """Get an LLM client for the given provider.

    Args:
        provider_name: Provider key (e.g. "google", "anthropic")
        model: Optional model override

    Returns:
        BaseLLMClient instance

    Raises:
        ValueError: If provider is unknown
    """
    # Import here to avoid circular dependencies
    from .gemini_client import GeminiClient
    from .anthropic_client import AnthropicClient

    provider = get_provider(provider_name)
    model_name = model or provider.model

    if provider.provider == "google":
        return GeminiClient(model=model_name)
    elif provider.provider == "anthropic":
        return AnthropicClient(model=model_name)
    else:
        raise ValueError(f"알 수 없는 프로바이더: {provider_name}")


__all__ = [
    "BaseLLMClient",
    "get_llm_client",
]
