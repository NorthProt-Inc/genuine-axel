import re
import threading
from datetime import datetime
from typing import Any, Optional

from backend.config import (
    MAX_CONTEXT_TOKENS,
    MEMORY_LONG_TERM_BUDGET,
    MEMORY_SESSION_ARCHIVE_BUDGET,
    MEMORY_TIME_CONTEXT_BUDGET,
)
from backend.core.logging import get_logger

from ..current import WorkingMemory
from ..recent import SessionArchive
from ..permanent import LongTermMemory
from ..memgpt import MemGPTManager, MemGPTConfig
from ..graph_rag import GraphRAG, KnowledgeGraph
from ..event_buffer import EventBuffer, EventType, StreamEvent
from ..meta_memory import MetaMemory
from backend.core.security.prompt_defense import sanitize_input

_log = get_logger("memory.unified.core")


class MemoryManagerCore:
    """Core initialization and basic operations for MemoryManager."""

    MAX_CONTEXT_TOKENS = MAX_CONTEXT_TOKENS
    LONG_TERM_BUDGET = MEMORY_LONG_TERM_BUDGET
    SESSION_ARCHIVE_BUDGET = MEMORY_SESSION_ARCHIVE_BUDGET
    TIME_CONTEXT_BUDGET = MEMORY_TIME_CONTEXT_BUDGET

    def __init__(
        self,
        client: Optional[Any] = None,
        model_name: str | None = None,
        working_memory: Optional[WorkingMemory] = None,
        session_archive: Optional[SessionArchive] = None,
        long_term_memory: Optional[LongTermMemory] = None,
        pg_conn_mgr=None,
        # Backward compat: accept model= kwarg and ignore it
        model: Optional[Any] = None,
    ):
        from google import genai

        if client is None and model is None:
            from backend.core.utils.gemini_client import get_gemini_client
            client = get_gemini_client()
        elif client is None and isinstance(model, genai.Client):
            # Accept genai.Client passed as model= for backward compat
            client = model
        elif client is None and model is not None:
            # Legacy GenerativeModelWrapper — extract .client
            client = getattr(model, "client", None)

        self.client = client
        self.model_name = model_name
        if not self.model_name:
            from backend.core.utils.gemini_client import get_model_name
            self.model_name = get_model_name()

        self._pg_conn_mgr = pg_conn_mgr

        # ── Build components with PG or legacy backends ──────────
        if pg_conn_mgr is not None:
            from backend.memory.pg.memory_repository import PgMemoryRepository
            from backend.memory.pg.graph_repository import PgGraphRepository
            from backend.memory.pg.meta_repository import PgMetaMemoryRepository

            pg_mem_repo = PgMemoryRepository(pg_conn_mgr)
            pg_graph_repo = PgGraphRepository(pg_conn_mgr)
            pg_meta_repo = PgMetaMemoryRepository(pg_conn_mgr)

            self.working = working_memory or WorkingMemory()
            self.session_archive = session_archive or SessionArchive(pg_conn_mgr=pg_conn_mgr)
            self.long_term = long_term_memory or LongTermMemory(repository=pg_mem_repo)
            self.knowledge_graph = KnowledgeGraph(pg_repository=pg_graph_repo)
            self.meta_memory = MetaMemory(pg_repository=pg_meta_repo)

            _log.info("MemoryManager using PostgreSQL backend")
        else:
            self.working = working_memory or WorkingMemory()
            self.session_archive = session_archive or SessionArchive()
            self.long_term = long_term_memory or LongTermMemory()
            self.knowledge_graph = KnowledgeGraph()
            self.meta_memory = MetaMemory()

        self._last_session_end: Optional[datetime] = None

        self.memgpt = MemGPTManager(
            long_term_memory=self.long_term,
            client=client,
            model_name=self.model_name,
            config=MemGPTConfig()
        )

        self.graph_rag = GraphRAG(client=client, model_name=self.model_name, graph=self.knowledge_graph)

        # M0: Event Buffer (session-scoped, in-memory)
        self.event_buffer = EventBuffer()

        self._write_lock = threading.Lock()
        self._read_semaphore = threading.Semaphore(5)

        # PERF-028: Compile LOG_PATTERNS as single regex
        log_patterns = [
            "[Tavily]", "[TTS Error]", "[Memory]", "[System]",
            "[Router]", "[LLM]", "[Error]", "[Warning]",
            "[Keywords]", "[Long-term Memory", "[Current]",
            "FutureWarning:", "DeprecationWarning:",
            "Permission denied", "Traceback",
        ]
        self._log_pattern = re.compile("|".join(re.escape(p) for p in log_patterns))

    def add_message(self, role: str, content: str, emotional_context: str = "neutral"):
        """Add a message to working memory with immediate SQL persistence.

        Args:
            role: Message role (user/assistant)
            content: Message content
            emotional_context: Emotional tone

        Returns:
            TimestampedMessage or None if filtered
        """
        # PERF-028: Use single regex check instead of 14 substring scans
        if self._log_pattern.search(content):
            _log.debug("Filtered log pattern from memory")
            return None

        # Prompt defense: sanitize user input
        if role == "user":
            content = sanitize_input(content)

        with self._write_lock:
            msg = self.working.add(role, content, emotional_context)

            # M0: Push message event to event buffer
            if msg:
                self.event_buffer.push(StreamEvent(
                    type=EventType.MESSAGE_RECEIVED,
                    metadata={"role": role, "content_preview": content[:50]},
                ))

            # Save each turn to SQL
            if msg and self.session_archive:
                try:
                    self.session_archive.save_message_immediate(
                        session_id=self.working.session_id,
                        role=msg.role,
                        content=msg.content,
                        timestamp=msg.timestamp.isoformat(),
                        emotional_context=msg.emotional_context
                    )
                except Exception as e:
                    _log.warning("Immediate message save failed", error=str(e))

            return msg

    def get_working_context(self) -> str:
        """Get current working memory context as formatted string."""
        return self.working.get_context()
