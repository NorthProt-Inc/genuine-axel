"""
ChatHandler - Thin orchestrator for chat processing.

This module coordinates the chat flow using specialized services:
- ContextService: Builds context from 4-tier memory
- SearchService: Handles web search
- ToolExecutionService: Executes MCP tools
- ReActLoopService: Runs the ReAct reasoning loop
- MemoryPersistenceService: Persists conversation to memory

Refactored from 938 lines to ~200 lines using service layer pattern.
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Dict, List, Optional, TYPE_CHECKING
from backend.core.filters import strip_xml_tags
from backend.core.logging import get_logger, request_tracker as rt
from backend.core.services import (
    ContextService,
    SearchService,
    ToolExecutionService,
    MemoryPersistenceService,
    ClassificationResult,
)
from backend.core.services.react_service import (
    ReActLoopService,
    ReActConfig,
    ReActResult,
    ChatEvent,
    EventType,
)
from backend.core.services.emotion_service import classify_emotion
from backend.llm.router import DEFAULT_MODEL
from backend.config import CHAT_THINKING_LEVEL

if TYPE_CHECKING:
    from backend.api.deps import ChatStateProtocol

_log = get_logger("core.chat")

# Re-export for backward compatibility
__all__ = ["ChatHandler", "ChatRequest", "ChatEvent", "EventType"]


@dataclass
class ChatRequest:
    """Request object for chat processing."""

    user_input: str
    model_choice: str = "anthropic"
    tier: str = "axel"
    enable_audio: bool = False
    enable_search: bool = False
    attachments: List[Dict] = field(default_factory=list)
    enable_request_tracking: bool = True
    multimodal_images: List[Dict] = field(default_factory=list)
    temperature: float = 0.7
    max_tokens: int = 16384
    enable_thinking: bool = False


@dataclass


class ChatHandler:
    """
    Thin orchestrator for chat processing.

    Coordinates services to handle chat requests:
    1. Add user message to memory
    2. Build context from memory systems
    3. Optionally perform web search
    4. Execute ReAct loop with tools
    5. Persist conversation to memory
    """

    def __init__(
        self,
        state: 'ChatStateProtocol',
        context_service: Optional[ContextService] = None,
        search_service: Optional[SearchService] = None,
        tool_service: Optional[ToolExecutionService] = None,
        react_service: Optional[ReActLoopService] = None,
        persistence_service: Optional[MemoryPersistenceService] = None
    ):
        """Initialize ChatHandler with dependencies.

        Args:
            state: Application state implementing ChatStateProtocol
            context_service: Service for building context (optional, created if None)
            search_service: Service for web search (optional, created if None)
            tool_service: Service for tool execution (optional, created if None)
            react_service: Service for ReAct loop (optional, created if None)
            persistence_service: Service for memory persistence (optional, created if None)
        """
        self.state = state

        # Initialize services with lazy creation
        self._context_service = context_service
        self._search_service = search_service
        self._tool_service = tool_service
        self._react_service = react_service
        self._persistence_service = persistence_service

    @property
    def context_service(self) -> ContextService:
        """Lazy initialization of context service."""
        if self._context_service is None:
            self._context_service = ContextService(
                memory_manager=self.state.memory_manager,
                long_term_memory=self.state.long_term_memory,
                identity_manager=self.state.identity_manager
            )
        return self._context_service

    @property
    def search_service(self) -> SearchService:
        """Lazy initialization of search service."""
        if self._search_service is None:
            self._search_service = SearchService()
        return self._search_service

    @property
    def tool_service(self) -> ToolExecutionService:
        """Lazy initialization of tool service."""
        if self._tool_service is None:
            self._tool_service = ToolExecutionService()
        return self._tool_service

    @property
    def react_service(self) -> ReActLoopService:
        """Lazy initialization of ReAct service."""
        if self._react_service is None:
            self._react_service = ReActLoopService(tool_service=self.tool_service)
        return self._react_service

    @property
    def persistence_service(self) -> MemoryPersistenceService:
        """Lazy initialization of persistence service."""
        if self._persistence_service is None:
            self._persistence_service = MemoryPersistenceService(
                memory_manager=self.state.memory_manager,
                long_term_memory=self.state.long_term_memory,
                identity_manager=self.state.identity_manager
            )
        return self._persistence_service

    async def process(self, request: ChatRequest) -> AsyncGenerator[ChatEvent, None]:
        """
        Process a chat request and yield streaming events.

        Args:
            request: ChatRequest with user input and settings

        Yields:
            ChatEvent objects for streaming response
        """
        user_input = request.user_input
        start_time = time.perf_counter()

        # Log start
        session_id = self._get_session_id()
        _log.info(
            "CHAT start",
            session=session_id[:8],
            input_len=len(user_input),
            model=request.model_choice,
            tier=request.tier,
            working_turns=self._get_turn_count(),
            longterm=self._get_longterm_count(),
        )

        # Classification (simplified)
        classification = ClassificationResult(needs_search=False, needs_tools=False)
        rt.log_gateway(intent="chat", model="default", elapsed_ms=(time.perf_counter() - start_time) * 1000)

        # Model selection
        model_config = DEFAULT_MODEL
        tier = request.tier
        _log.debug("MODEL select", model=model_config.name, tier=tier, provider=model_config.provider)
        yield ChatEvent(EventType.STATUS, f"{model_config.icon} {model_config.name} 연결 중...")

        # Phase 1: Add user message immediately (neutral emotion placeholder)
        if self.state.memory_manager:
            self.state.memory_manager.add_message("user", user_input, emotional_context="neutral")

        # Phase 2: Run independent tasks in parallel
        gather_results = await asyncio.gather(
            classify_emotion(user_input),
            self.context_service.build(
                user_input=user_input,
                tier=tier,
                model_config=model_config,
                classification=classification,
            ),
            self.search_service.search_if_needed(
                user_input,
                request.enable_search or classification.needs_search,
            ),
            self._fetch_tools(),
            return_exceptions=True,
        )

        # Unpack with fallbacks for individual failures
        raw_emotion, raw_context, raw_search, raw_tools = gather_results

        from backend.core.services.context_service import ContextResult

        user_emotion: str = raw_emotion if isinstance(raw_emotion, str) else "neutral"
        if isinstance(raw_emotion, BaseException):
            _log.warning("PARALLEL emotion fail", error=str(raw_emotion))

        context_result: ContextResult = (
            raw_context if isinstance(raw_context, ContextResult)
            else ContextResult(system_prompt="", stats={}, turn_count=0, elapsed_ms=0.0)
        )
        if isinstance(raw_context, BaseException):
            _log.warning("PARALLEL context fail", error=str(raw_context))

        from backend.core.services.search_service import SearchResult
        search_result: SearchResult = (
            raw_search if isinstance(raw_search, SearchResult)
            else SearchResult()
        )
        if isinstance(raw_search, BaseException):
            _log.warning("PARALLEL search fail", error=str(raw_search))

        mcp_client, available_tools = (
            raw_tools if isinstance(raw_tools, tuple) else (None, [])
        )
        if isinstance(raw_tools, BaseException):
            _log.warning("PARALLEL tools fail", error=str(raw_tools))

        # Phase 3: Patch emotion on already-added message
        if user_emotion != "neutral" and self.state.memory_manager:
            working = getattr(self.state.memory_manager, 'working', None)
            if working and hasattr(working, '_messages') and working._messages:
                working._messages[-1].emotional_context = user_emotion

        if search_result.success:
            yield ChatEvent(EventType.STATUS, " 검색 완료")

        # Build final prompt
        final_prompt = self._build_final_prompt(
            user_input=user_input,
            search_context=search_result.context,
            search_failed=search_result.failed,
        )

        yield ChatEvent(EventType.STATUS, "응답 생성 중...")

        # Update tool service with MCP client
        if mcp_client:
            self.tool_service.mcp_client = mcp_client

        # 6. ReAct loop configuration
        react_config = ReActConfig(
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            enable_thinking=request.enable_thinking,
            thinking_level=CHAT_THINKING_LEVEL,
        )

        # Special case: force tool call for specific keywords
        force_tool_call = "라자냐" in request.user_input

        # 7. Run ReAct loop
        full_response = ""
        llm_elapsed = 0.0

        async for event in self.react_service.run(
            prompt=final_prompt,
            system_prompt=context_result.system_prompt,
            model_config=model_config,
            available_tools=available_tools,
            config=react_config,
            images=request.multimodal_images if request.multimodal_images else None,
            force_tool_call=force_tool_call,
            background_tasks=getattr(self.state, "background_tasks", None)
        ):
            # Capture result from control event
            if event.type == EventType.CONTROL and "react_result" in event.metadata:
                result: ReActResult = event.metadata["react_result"]
                full_response = result.full_response
                llm_elapsed = result.llm_elapsed_ms
            else:
                yield event

        # 8. Safety net: strip any leaked XML tags (react_service handles most filtering)
        full_response = strip_xml_tags(full_response)

        # Add assistant message to memory and spawn persistence task
        if full_response:
            self.persistence_service.add_assistant_message(full_response)
            self._spawn_task(
                self.persistence_service.persist_all(user_input, full_response),
                "memory_persist"
            )

        # 9. Log completion
        total_elapsed = (time.perf_counter() - start_time) * 1000
        _log.info(
            "CHAT done",
            session=session_id[:8],
            model=model_config.name,
            tier=tier,
            llm_ms=round(llm_elapsed, 1),
            dur_ms=round(total_elapsed, 1),
            resp_len=len(full_response),
            turns=self._get_turn_count(),
        )

        # 10. Log interaction to session archive
        self._log_interaction(model_config, tier, classification, request, total_elapsed, full_response)

        # 11. Yield final events
        yield ChatEvent(EventType.STATUS, "Idle")
        yield ChatEvent(
            EventType.DONE,
            "",
            metadata={
                "model": model_config.id,
                "model_name": model_config.name,
                "tier": tier,
                "turn_count": self._get_turn_count(),
                "llm_ms": round(llm_elapsed, 1),
                "total_ms": round(total_elapsed, 1),
                "full_response": full_response,
            }
        )

    async def _fetch_tools(self) -> tuple:
        """Fetch MCP client and available tools.

        Returns:
            Tuple of (mcp_client, available_tools).
        """
        from backend.core.mcp_client import get_mcp_client
        mcp_client = get_mcp_client()
        available_tools = await mcp_client.get_anthropic_tools()
        return mcp_client, available_tools

    def _build_final_prompt(
        self,
        user_input: str,
        search_context: str,
        search_failed: bool
    ) -> str:
        """Build the final user prompt with search results."""
        parts = []

        if search_context:
            parts.append(f"## 검색 결과\n{search_context}")
        elif search_failed:
            parts.append("검색 실패")

        parts.append(f"[User]: {user_input}")
        return "\n".join(parts)

    def _spawn_task(self, coro, label: str) -> asyncio.Task:
        """Spawn a background task with cleanup callback."""
        task = asyncio.create_task(coro)
        task_list = getattr(self.state, "background_tasks", None)
        if isinstance(task_list, list):
            task_list.append(task)

        def _done(t: asyncio.Task):
            if isinstance(task_list, list):
                try:
                    task_list.remove(t)
                except ValueError:
                    pass
            if t.cancelled():
                return
            exc = t.exception()
            if exc:
                _log.warning("BG task fail", task=label, error=str(exc))

        task.add_done_callback(_done)
        return task

    def _get_session_id(self) -> str:
        """Get current session ID safely."""
        if self.state.memory_manager:
            return self.state.memory_manager.get_session_id()
        return "unknown"

    def _get_turn_count(self) -> int:
        """Get current turn count safely."""
        if self.state.memory_manager:
            return self.state.memory_manager.get_turn_count()
        return 0

    def _get_longterm_count(self) -> int:
        """Get long-term memory count safely."""
        if self.state.long_term_memory:
            return self.state.long_term_memory.get_stats().get("total_memories", 0)
        return 0

    def _log_interaction(
        self,
        model_config: Any,
        tier: str,
        classification: ClassificationResult,
        request: ChatRequest,
        total_elapsed: float,
        full_response: str
    ) -> None:
        """Log interaction to session archive."""
        if not (self.state.memory_manager and self.state.memory_manager.is_session_archive_available()):
            return

        try:
            self.state.memory_manager.session_archive.log_interaction(
                routing_decision={
                    "effective_model": model_config.id,
                    "tier": tier,
                    "routing_features": {
                        "needs_search": classification.needs_search,
                        "needs_tools": classification.needs_tools,
                    },
                    "manual_override": request.model_choice != "auto",
                },
                conversation_id=self._get_session_id(),
                turn_id=self._get_turn_count(),
                latency_ms=int(total_elapsed),
                tokens_in=len(request.user_input) // 4,
                tokens_out=len(full_response) // 4,
                response_text=full_response
            )
        except Exception as e:
            _log.debug("LOG interaction fail", error=str(e))
