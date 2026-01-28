from dataclasses import dataclass
from typing import List
from backend.core.logging import get_logger
from backend.config import MODEL_NAME

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
        return {
            "id": self.id,
            "name": self.name,
            "icon": self.icon,
            "description": self.description,
        }

DEFAULT_MODEL = ModelConfig(
    id="gemini",
    name="Gemini 3 Pro",
    provider="google",
    model=MODEL_NAME,
)

def get_model() -> ModelConfig:

    _log.debug("model selected", model=DEFAULT_MODEL.id, provider=DEFAULT_MODEL.provider)
    return DEFAULT_MODEL

def get_all_models() -> List[dict]:

    _log.debug("models list requested", count=1)
    return [DEFAULT_MODEL.to_dict()]

__all__ = [
    "ModelConfig",
    "DEFAULT_MODEL",
    "get_model",
    "get_all_models",
]
