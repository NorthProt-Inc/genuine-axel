"""Backward compatibility shim for LongTermMemory facade.

DEPRECATED: This module exists only for backward compatibility.
New code should import directly from core, retrieval, access_tracker, or promotion modules.

All classes and functions are re-exported from their new locations.
"""

# Re-export everything from new modules for backward compatibility
from .core import LongTermMemory
from .promotion import PromotionCriteria, _text_similarity

__all__ = [
    "LongTermMemory",
    "PromotionCriteria",
    "_text_similarity",
]
