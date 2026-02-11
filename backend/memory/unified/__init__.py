"""Unified Memory Manager - Refactored into modular package.

This package provides a unified memory management system with:
- Core: Initialization and basic message operations
- ContextBuilder: Intelligent context assembly (sync + async)
- Session: Session lifecycle and summarization
- Facade: High-level convenience methods

All components are composed via mixins into a single MemoryManager class.
"""

from .core import MemoryManagerCore
from .context_builder import ContextBuilderMixin
from .session import SessionMixin, SESSION_SUMMARY_PROMPT
from .facade import FacadeMixin


class MemoryManager(
    MemoryManagerCore,
    ContextBuilderMixin,
    SessionMixin,
    FacadeMixin,
):
    """Unified Memory Manager with all capabilities.
    
    This class combines:
    - MemoryManagerCore: Initialization, message handling
    - ContextBuilderMixin: Smart context building (sync/async)
    - SessionMixin: Session management, summarization, querying
    - FacadeMixin: Convenience methods for ChatHandler
    
    Example:
        >>> mgr = MemoryManager(client=gemini_client)
        >>> mgr.add_message("user", "Hello!")
        >>> context = await mgr.build_smart_context("What did we discuss?")
        >>> await mgr.end_session()
    """
    pass


__all__ = ["MemoryManager", "SESSION_SUMMARY_PROMPT"]
