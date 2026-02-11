import asyncio
from typing import Optional

from backend.core.logging import get_logger

_log = get_logger("memory.unified.facade")


class FacadeMixin:
    """Facade methods for ChatHandler and other high-level components."""

    def get_session_id(self) -> str:
        """Get current session ID."""
        return self.working.session_id if self.working else "unknown"

    def get_turn_count(self) -> int:
        """Get current turn count."""
        return self.working.get_turn_count() if self.working else 0

    def is_working_available(self) -> bool:
        """Check if working memory is available."""
        return self.working is not None

    def is_session_archive_available(self) -> bool:
        """Check if session archive is available."""
        return self.session_archive is not None

    def is_graph_rag_available(self) -> bool:
        """Check if GraphRAG is available."""
        return self.graph_rag is not None

    def get_time_elapsed_context(self) -> Optional[str]:
        """Get time elapsed context from working memory."""
        if self.working:
            return self.working.get_time_elapsed_context()
        return None

    def get_progressive_context(self, full_turns: int = 40) -> str:
        """Get progressive context from working memory."""
        if self.working:
            return self.working.get_progressive_context(full_turns=full_turns)
        return ""

    async def save_working_to_disk(self) -> bool:
        """Save working memory to disk (async wrapper)."""
        if not self.working:
            return False
        try:
            return await asyncio.to_thread(self.working.save_to_disk)
        except Exception:
            return False
