import asyncio
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, AsyncGenerator, Dict, List, Optional

from backend.core.utils.timezone import VANCOUVER_TZ
from backend.config import (
    MAX_CODE_CONTEXT_CHARS,
    MAX_CODE_FILE_CHARS,
    MAX_SEARCH_CONTEXT_CHARS,
)
from backend.core.context_optimizer import ContextOptimizer, get_dynamic_system_prompt
from backend.core.logging import get_logger, request_tracker as rt
from backend.llm import get_llm_client
from backend.llm.router import DEFAULT_MODEL
from backend.memory import calculate_importance_sync

_log = get_logger("core.chat")

class EventType(str, Enum):

    STATUS = "status"
    TEXT = "text"
    THINKING = "thinking"
    AUDIO = "audio"
    ERROR = "error"
    DONE = "done"
    CONTROL = "control"
    THINKING_START = "thinking start"
    THINKING_END = "thinking end"
    TOOL_START = "tool start"
    TOOL_END = "tool end"

@dataclass
class ChatEvent:

    type: EventType
    content: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class ChatRequest:

    user_input: str
    model_choice: str = "gemini"
    tier: str = "axel"
    enable_audio: bool = False
    enable_search: bool = False
    attachments: List[Dict] = field(default_factory=list)

    enable_request_tracking: bool = True

    multimodal_images: List[Dict] = field(default_factory=list)
    temperature: float = 0.7
    max_tokens: int = 16384

    enable_thinking: bool = False

DEFAULT_CONFIG = {
    "working_turns": 200,
    "full_turns": 80,
    "use_sqlite": True,
    "chromadb_limit": 100,
    "use_graphrag": True,
    "max_context_chars": 2_000_000,
    "session_count": 30,
    "session_budget": 60_000,
}

@dataclass
class ClassificationResult:

    needs_search: bool = False
    needs_tools: bool = False
    needs_code: bool = False

@dataclass
class QueryMode:
    name: str = "chat"
    icon: str = "💬"

DEFAULT_MODE = QueryMode()

def _format_memory_age(timestamp_str: str, now: datetime = None) -> str:

    if not timestamp_str:
        return ""

    try:

        if 'T' in timestamp_str:
            mem_time = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        else:
            mem_time = datetime.fromisoformat(timestamp_str)

        if mem_time.tzinfo is None:
            mem_time = mem_time.replace(tzinfo=timezone.utc)

        now_time = now or datetime.now(timezone.utc)
        delta = now_time - mem_time

        hours = delta.total_seconds() / 3600
        days = delta.days

        if hours < 1:
            return "방금"
        elif hours < 24:
            return f"{int(hours)}시간 전"
        elif days == 1:
            return "어제"
        elif days < 7:
            return f"{days}일 전"
        elif days < 30:
            weeks = days // 7
            return f"{weeks}주 전"
        elif days < 365:
            months = days // 30
            return f"{months}개월 전"
        else:

            return mem_time.strftime("%Y-%m-%d")
    except Exception:
        return ""

def _truncate_text(text: str, max_chars: int, label: str = "") -> str:

    if not text:
        return ""
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    suffix = "\n... (truncated)"
    keep = max_chars - len(suffix)
    if keep <= 0:
        return text[:max_chars]
    if label:
        _log.debug("CTX truncate", section=label, chars=len(text), limit=max_chars)
    return text[:keep].rstrip() + suffix

class ChatHandler:

    def __init__(self, state):

        self.state = state
        self.vancouver_tz = VANCOUVER_TZ

    async def process(
        self,
        request: ChatRequest
    ) -> AsyncGenerator[ChatEvent, None]:

        user_input = request.user_input
        start_time = time.perf_counter()

        session_id = self.state.memory_manager.working.session_id if self.state.memory_manager and self.state.memory_manager.working else "unknown"
        _log.info(
            "CHAT start",
            session=session_id[:8],
            input_len=len(user_input),
            model=request.model_choice,
            tier=request.tier,
            working_turns=self.state.memory_manager.working.get_turn_count() if self.state.memory_manager else 0,
            longterm=self.state.long_term_memory.get_stats().get("total_memories", 0) if self.state.long_term_memory else 0,
        )

        classification = ClassificationResult(
            needs_search=False,
            needs_tools=False,
        )

        classify_elapsed = (time.perf_counter() - start_time) * 1000
        rt.log_gateway(
            intent="chat",
            model="default",
            elapsed_ms=classify_elapsed,
        )

        model_config = self._select_model(request)
        tier = self._determine_tier(request, model_config)

        _log.debug("MODEL select", model=model_config.name, tier=tier, provider=model_config.provider)
        yield ChatEvent(EventType.STATUS, f"{model_config.icon} {model_config.name} 연결 중...")

        if self.state.memory_manager:
            self.state.memory_manager.add_message("user", user_input)

        full_prompt = await self._build_context_and_prompt(
            user_input=user_input,
            tier=tier,
            model_config=model_config,
            classification=classification
        )

        search_context, search_failed = await self._handle_web_search(
            user_input,
            request.enable_search or classification.needs_search
        )
        if search_context:
            yield ChatEvent(EventType.STATUS, " 검색 완료")

        final_prompt = self._build_final_prompt(
            user_input=user_input,
            mode=DEFAULT_MODE,
            search_context=search_context,
            search_failed=search_failed
        )

        yield ChatEvent(EventType.STATUS, f"{DEFAULT_MODE.icon} 응답 생성 중...")

        current_prompt = final_prompt
        current_system_prompt = full_prompt
        loop_count = 0
        MAX_LOOPS = 5

        yield ChatEvent(EventType.STATUS, "🔧 도구 준비 중...")
        from backend.core.mcp_client import get_mcp_client
        mcp_client = get_mcp_client()

        available_tools = await mcp_client.get_gemini_tools()

        force_tool_call = "라자냐" in request.user_input

        llm_start_time = time.perf_counter()

        yield ChatEvent(EventType.THINKING_START, "", metadata={
            "label": "Thinking...",
            "collapsed": True
        })

        while loop_count < MAX_LOOPS:
            loop_count += 1
            full_response = ""
            pending_function_calls = []

            try:
                _log.debug("LLM client init", provider=model_config.provider, model=model_config.model)
                llm = get_llm_client(model_config.provider, model_config.model)

                async for text, is_thought, function_call in llm.generate_stream(
                    prompt=current_prompt,
                    system_prompt=current_system_prompt,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                    images=request.multimodal_images if request.multimodal_images else None,
                    enable_thinking=request.enable_thinking,
                    thinking_level="high",
                    tools=available_tools,
                    force_tool_call=force_tool_call
                ):
                    if function_call:
                        pending_function_calls.append(function_call)
                        _log.debug("TOOL detect", name=function_call["name"])
                    elif text:
                        if is_thought:
                            yield ChatEvent(EventType.THINKING, text)
                        else:
                            full_response += text
                            yield ChatEvent(EventType.TEXT, text)

            except Exception as e:
                error_str = str(e).lower()
                _log.error("LLM stream error", error=str(e)[:200], partial_len=len(full_response))

                if full_response.strip():
                    _log.warning("LLM partial used", chars=len(full_response))
                    break

                if '503' in error_str or 'overloaded' in error_str:
                    fallback = "지금 서버가 좀 바빠. 잠시 후에 다시 물어봐줄래?"
                elif 'timeout' in error_str:
                    fallback = "응답이 좀 늦어지고 있어. 조금만 기다려주거나 다시 시도해봐!"
                elif 'circuit breaker' in error_str:
                    fallback = "잠시 쉬어가는 중이야. 30초 정도 후에 다시 해볼래?"
                elif '429' in error_str or 'rate' in error_str:
                    fallback = "요청이 좀 많았나봐. 잠깐 쉬었다가 다시 해보자!"
                else:
                    fallback = "뭔가 문제가 생겼어. 다시 시도해볼래?"

                _log.info("LLM fallback", error_type=error_str[:30])

                full_response = fallback
                yield ChatEvent(EventType.TEXT, fallback)
                break

            if not pending_function_calls:
                break

            yield ChatEvent(EventType.STATUS, " 도구 실행 중...")
            tool_outputs = []
            deferred_tools = []

            for fc in pending_function_calls:
                tool_name = fc["name"]
                tool_args = fc.get("args", {})

                if self._is_fire_and_forget_tool(tool_name):

                    deferred_tools.append((tool_name, tool_args))
                    tool_outputs.append(f"✓ {tool_name}: (queued for background execution)")
                    _log.debug("TOOL deferred", name=tool_name)
                    continue

                yield ChatEvent(EventType.TOOL_START, "", metadata={
                    "tool_name": tool_name,
                    "tool_args": tool_args
                })

                try:
                    result = await mcp_client.call_tool(tool_name, tool_args)
                    success = result.get("success", False)
                    output_text = result.get("result", "")

                    log_msg = f" {tool_name}: {output_text}"
                    tool_outputs.append(log_msg)
                    _log.info("TOOL exec", name=tool_name, success=success)

                    yield ChatEvent(EventType.TOOL_END, "", metadata={
                        "tool_name": tool_name,
                        "success": success,
                        "result_preview": output_text[:200] if output_text else ""
                    })

                except Exception as e:
                    error_msg = f" {tool_name} Error: {str(e)}"
                    tool_outputs.append(error_msg)
                    _log.error("TOOL fail", name=tool_name, error=str(e))

                    yield ChatEvent(EventType.TOOL_END, "", metadata={
                        "tool_name": tool_name,
                        "success": False,
                        "error": str(e)
                    })

            if deferred_tools:
                self._spawn_task(
                    self._execute_deferred_tools(mcp_client, deferred_tools),
                    "deferred_tools"
                )

            if tool_outputs:
                observation = "\n".join(tool_outputs)
                current_prompt += f"\n\n[Tool Execution Results]\n{observation}\n\n[Instruction]\n위 결과를 바탕으로 사용자에게 자연스럽게 보고해."

                force_tool_call = False
                _log.debug("REACT loop", iteration=loop_count)
            else:
                break

        llm_elapsed = (time.perf_counter() - llm_start_time) * 1000

        yield ChatEvent(EventType.THINKING_END, "", metadata={
            "loops_completed": loop_count
        })

        await self._post_process(
            user_input=user_input,
            response=full_response,
            model_config=model_config,
        )

        total_elapsed = (time.perf_counter() - start_time) * 1000

        _log.info(
            "CHAT done",
            session=session_id[:8],
            model=model_config.name,
            tier=tier,
            llm_ms=round(llm_elapsed, 1),
            dur_ms=round(total_elapsed, 1),
            resp_len=len(full_response),
            turns=self.state.memory_manager.working.get_turn_count() if self.state.memory_manager else 0,
        )

        if self.state.memory_manager and self.state.memory_manager.session_archive:
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
                    conversation_id=self.state.memory_manager.working.session_id if self.state.memory_manager.working else None,
                    turn_id=self.state.memory_manager.working.get_turn_count() if self.state.memory_manager.working else None,
                    latency_ms=int(total_elapsed),
                    tokens_in=len(user_input) // 4,
                    tokens_out=len(full_response) // 4,
                    response_text=full_response
                )
            except Exception as e:
                _log.debug("LOG interaction fail", error=str(e))

        yield ChatEvent(EventType.STATUS, "Idle")
        yield ChatEvent(
            EventType.DONE,
            "",
            metadata={
                "model": model_config.id,
                "model_name": model_config.name,
                "tier": tier,
                "turn_count": self.state.memory_manager.working.get_turn_count() if self.state.memory_manager else 0,
                "llm_ms": round(llm_elapsed, 1),
                "total_ms": round(total_elapsed, 1),
                "full_response": full_response,
            }
        )

    def _spawn_task(self, coro, label: str) -> asyncio.Task:

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

    FIRE_AND_FORGET_TOOLS = frozenset({
        "store_memory",
        "add_memory",
    })

    def _is_fire_and_forget_tool(self, tool_name: str) -> bool:

        return tool_name in self.FIRE_AND_FORGET_TOOLS

    async def _execute_deferred_tools(
        self,
        mcp_client,
        tools: list[tuple[str, dict]]
    ) -> None:

        for tool_name, tool_args in tools:
            try:
                result = await mcp_client.call_tool(tool_name, tool_args)
                success = result.get("success", False)
                if success:
                    _log.info("BG TOOL ok", name=tool_name)
                else:
                    _log.warning(
                        "BG TOOL fail",
                        name=tool_name,
                        error=result.get("error", "unknown")[:100]
                    )
            except Exception as e:
                _log.warning("BG TOOL error", name=tool_name, error=str(e)[:100])

    def _select_model(self, request: ChatRequest):

        return DEFAULT_MODEL

    def _determine_tier(self, request: ChatRequest, model_config) -> str:
        return "axel"

    async def _build_context_and_prompt(
        self,
        user_input: str,
        tier: str,
        model_config,
        classification: Optional[ClassificationResult] = None
    ) -> str:

        config = DEFAULT_CONFIG
        context_start = time.perf_counter()

        optimizer = ContextOptimizer(tier)

        current_time = datetime.now(self.vancouver_tz).strftime("%Y년 %m월 %d일 (%A) %H:%M PST")
        model_awareness = f" 현재 모드: {model_config.name} ({tier.upper()} 티어)"

        full_system_prompt = self.state.identity_manager.get_system_prompt() if self.state.identity_manager else ""
        dynamic_prompt = get_dynamic_system_prompt(tier, full_system_prompt)
        optimizer.add_section("system_prompt", dynamic_prompt)

        temporal_content = f"현재 시각: {current_time}\n{model_awareness}"
        if self.state.memory_manager and self.state.memory_manager.working:
            time_context = self.state.memory_manager.working.get_time_elapsed_context()
            if time_context:
                temporal_content += f"\n{time_context}"
                _log.debug("CTX temporal", context=time_context)
        optimizer.add_section("temporal", temporal_content)

        turn_count = 0
        if self.state.memory_manager and self.state.memory_manager.working:
            turn_count = self.state.memory_manager.working.get_turn_count()
            full_turns = config.get("full_turns", config["working_turns"] // 2)
            working_context = self.state.memory_manager.working.get_progressive_context(full_turns=full_turns)
            if working_context:
                optimizer.add_section("working_memory", working_context)
                _log.debug("MEM working", turns=turn_count, chars=len(working_context))
            else:
                _log.debug("MEM working empty", turns=turn_count)
        else:
            _log.warning("MEM working unavailable")

        if config["use_sqlite"] and self.state.memory_manager and self.state.memory_manager.session_archive:
            try:
                session_count = config.get("session_count", 10)
                session_budget = config.get("session_budget", 3000)
                session_context = self.state.memory_manager.session_archive.get_recent_summaries(session_count, session_budget)
                if session_context and "최근 대화 기록이 없습니다" not in session_context:

                    session_lines = [line.strip() for line in session_context.split('\n') if line.strip()]
                    session_formatted = optimizer.format_as_bullets(session_lines)
                    optimizer.add_section("session_archive", session_formatted)
                    _log.debug("MEM session", chars=len(session_formatted))
                else:
                    _log.debug("MEM session empty")
            except Exception as e:
                _log.warning("MEM session fail", error=str(e))

        if self.state.long_term_memory:
            try:
                memgpt = getattr(self.state.memory_manager, 'memgpt', None) if self.state.memory_manager else None
                if memgpt:

                    tier_budgets = {"axel": 125_000}
                    token_budget = tier_budgets.get(tier, 125_000)

                    selected_memories, used_tokens = memgpt.context_budget_select(
                        query=user_input,
                        token_budget=token_budget
                    )
                    if selected_memories:
                        memory_items = []
                        for m in selected_memories[:config["chromadb_limit"]]:
                            if not m.content:
                                continue
                            ts = m.metadata.get('event_timestamp') or m.metadata.get('created_at') or m.metadata.get('timestamp', '')
                            age_label = _format_memory_age(ts)
                            if age_label:
                                memory_items.append(f"[{age_label}] {m.content}")
                            else:
                                memory_items.append(m.content)

                        temporal_hint = " 각 기억의 [시간] 라벨을 참고해."
                        memory_formatted = temporal_hint + "\n" + optimizer.format_as_bullets(memory_items)
                        optimizer.add_section("long_term", memory_formatted)
                        _log.debug("MEM longterm", count=len(memory_items), tokens=used_tokens)
                else:
                    formatted = self.state.long_term_memory.get_formatted_context(user_input, max_items=config["chromadb_limit"])
                    if formatted:
                        optimizer.add_section("long_term", formatted)
                        _log.debug("MEM longterm fallback", chars=len(formatted))
            except Exception as e:
                _log.warning("MEM longterm fail", error=str(e))

        if config["use_graphrag"] and self.state.memory_manager and self.state.memory_manager.graph_rag:
            try:
                graph_result = self.state.memory_manager.graph_rag.query_sync(user_input)
                if graph_result and graph_result.context:
                    optimizer.add_section("graphrag", graph_result.context)
                    _log.debug("MEM graphrag", entities=len(graph_result.entities), rels=len(graph_result.relations), chars=len(graph_result.context))
                else:
                    _log.debug("MEM graphrag empty")
            except Exception as e:
                _log.warning("MEM graphrag fail", error=str(e))

        should_inject_code = classification and classification.needs_code
        if should_inject_code:
            try:
                from backend.core.tools.system_observer import get_code_summary, get_source_code

                code_summary = get_code_summary()
                if code_summary:
                    code_summary = _truncate_text(code_summary, MAX_CODE_CONTEXT_CHARS, label="code_summary")

                    _log.debug("CTX code", chars=len(code_summary))

                file_patterns = re.findall(r'([a-zA-Z_][a-zA-Z0-9_/]*\.py|[a-zA-Z_][a-zA-Z0-9_/]+/[a-zA-Z_][a-zA-Z0-9_]*\.[a-z]+)', user_input)
                injected_files = []
                code_files_content = ""
                for file_path in file_patterns[:3]:
                    content = get_source_code(file_path)
                    if content:
                        if len(content) > MAX_CODE_FILE_CHARS:
                            content = content[:MAX_CODE_FILE_CHARS] + f"\n... (truncated)"
                        code_files_content += f"\n##  {file_path}\n```python\n{content}\n```"
                        injected_files.append(file_path)

                if injected_files:
                    _log.debug("CTX code files", files=injected_files)
            except Exception as e:
                _log.warning("CTX code fail", error=str(e))
                code_summary = ""
                code_files_content = ""
        else:
            code_summary = ""
            code_files_content = ""

        optimized_context = optimizer.build()
        stats = optimizer.get_stats()

        full_prompt = f"##  현재 시간\n{current_time}\n\n"

        if optimized_context:
            full_prompt += f"##  기억 ({tier.upper()} Context)\n{optimized_context}"

        if code_summary:
            full_prompt += f"\n\n##  내 코드베이스\n{code_summary}"
        if code_files_content:
            full_prompt += code_files_content

        context_ms = (time.perf_counter() - context_start) * 1000

        _log.debug(
            "CTX build",
            tier=tier,
            working_turns=turn_count,
            sections=stats["sections_added"],
            truncated=stats["sections_truncated"],
            dropped=stats["sections_dropped"],
            raw_chars=stats["total_chars_raw"],
            final_chars=stats["total_chars_final"],
            tokens_approx=len(full_prompt) // 4,
            dur_ms=round(context_ms, 1),
        )

        rt.log_memory(
            longterm=config["chromadb_limit"],
            working=turn_count,
            tokens=len(full_prompt) // 4
        )

        return full_prompt

    async def _handle_web_search(self, user_input: str, should_search: bool) -> tuple[str, bool]:

        if not should_search:
            return "", False

        _log.debug("SEARCH start", query=user_input[:50])
        search_start = time.perf_counter()
        try:
            from backend.protocols.mcp.research_server import _tavily_search
            search_context = await _tavily_search(user_input, max_results=5, search_depth="basic")
            search_elapsed = (time.perf_counter() - search_start) * 1000

            if search_context and "검색 불가" not in search_context:
                search_context = _truncate_text(
                    search_context,
                    MAX_SEARCH_CONTEXT_CHARS,
                    label="search_context"
                )
                _log.debug("SEARCH done", chars=len(search_context), dur_ms=round(search_elapsed, 1))
                rt.log_search(query=user_input[:50], results=1, elapsed_ms=search_elapsed)
                return search_context, False
            return "", True
        except Exception as e:
            _log.warning("SEARCH fail", error=str(e))
            return "", True

    def _build_final_prompt(
        self,
        user_input: str,
        mode,
        search_context: str,
        search_failed: bool
    ) -> str:

        parts = [f"## {mode.icon} {mode.name.upper()}"]

        if search_context:
            parts.append(f"## 검색 결과\n{search_context}")
        elif search_failed:
            parts.append(" 검색 실패")

        parts.append(f"[User]: {user_input}")
        return "\n".join(parts)

    async def _post_process(
        self,
        user_input: str,
        response: str,
        model_config,
    ) -> None:

        if not response:
            return

        if self.state.memory_manager:
            self.state.memory_manager.add_message("assistant", response)

        self._spawn_task(
            self._persist_memory_async(user_input, response),
            "memory_persist"
        )

    async def _persist_memory_async(
        self,
        user_input: str,
        response: str
    ) -> None:

        if self.state.memory_manager and self.state.memory_manager.working:
            try:
                saved = await asyncio.to_thread(
                    self.state.memory_manager.working.save_to_disk
                )
                if saved:
                    _log.debug(
                        "BG working saved",
                        turns=self.state.memory_manager.working.get_turn_count()
                    )
            except Exception as e:
                _log.warning("BG working save fail", error=str(e))

        tasks = []

        if self.state.long_term_memory:
            tasks.append(self._store_longterm_async(user_input, response))

        if self.state.memory_manager and self.state.memory_manager.graph_rag:
            tasks.append(self._extract_graph_async(user_input, response))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    _log.warning("BG task fail", idx=i, error=str(result)[:100])

    async def _store_longterm_async(self, user_input: str, response: str) -> Optional[str]:

        try:
            persona_summary = (
                self.state.identity_manager.persona.get("core_identity", "")
                if self.state.identity_manager
                else ""
            )

            def store_to_longterm():
                importance = calculate_importance_sync(
                    user_input, response, persona_context=persona_summary
                )
                memory_id = self.state.long_term_memory.add(
                    content=f"User: {user_input}\nAI: {response}",
                    memory_type="conversation",
                    importance=importance,
                    source_session="unified"
                )
                return memory_id

            memory_id = await asyncio.to_thread(store_to_longterm)
            if memory_id:
                _log.debug(
                    "BG longterm stored",
                    memory_id=memory_id[:8] if memory_id else None
                )
            return memory_id
        except Exception as e:
            _log.warning("BG longterm fail", error=str(e)[:100])
            return None

    async def _extract_graph_async(self, user_input: str, response: str) -> dict:

        try:
            combined = f"User: {user_input}\nAssistant: {response}"
            result = await self.state.memory_manager.graph_rag.extract_and_store(
                combined,
                source="conversation",
                timeout_seconds=120
            )
            if result.get("entities_added", 0) > 0:
                _log.debug(
                    "BG graph done",
                    entities=result.get("entities_added", 0),
                    rels=result.get("relations_added", 0)
                )
            return result
        except Exception as e:
            _log.debug("BG graph skip", error=str(e)[:100])
            return {"error": str(e), "entities_added": 0, "relations_added": 0}
