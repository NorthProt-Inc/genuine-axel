from dataclasses import dataclass
from typing import List
from backend.core.logging import get_logger
from backend.config import ANTHROPIC_CHAT_MODEL

_log = get_logger("llm.router")

@dataclass
class ModelConfig:

    id: str
    name: str
    provider: str
    model: str
    icon: str = ""
    description: str = ""

    def to_dict(self) -> dict:
        """Convert model config to dictionary for API response.

        Returns:
            Dict with id, name, icon, and description
        """
        return {
            "id": self.id,
            "name": self.name,
            "icon": self.icon,
            "description": self.description,
        }

DEFAULT_MODEL = ModelConfig(
    id="anthropic",
    name="Claude Sonnet 4.5",
    provider="anthropic",
    model=ANTHROPIC_CHAT_MODEL,
)

def get_model() -> ModelConfig:
    """Get the default model configuration.

    Returns:
        ModelConfig for the primary LLM model
    """
    _log.debug("model selected", model=DEFAULT_MODEL.id, provider=DEFAULT_MODEL.provider)
    return DEFAULT_MODEL

def get_all_models() -> List[dict]:
    """Get all available model configurations.

    Returns:
        List of model dicts for API response
    """
    _log.debug("models list requested", count=1)
    return [DEFAULT_MODEL.to_dict()]

__all__ = [
    "ModelConfig",
    "DEFAULT_MODEL",
    "get_model",
    "get_all_models",
]
