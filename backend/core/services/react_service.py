"""
ReAct loop service for ChatHandler.

Implements the Reasoning + Acting pattern for tool-augmented LLM interactions.
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, AsyncGenerator, Dict, Any, List, Optional

from backend.config import REACT_DEFAULT_MAX_TOKENS, REACT_DEFAULT_TEMPERATURE, REACT_MAX_LOOPS
from backend.core.filters import strip_xml_tags, has_partial_tool_tag
from backend.core.logging import get_logger
from backend.llm import get_llm_client
from .tool_service import ToolExecutionService

if TYPE_CHECKING:
    pass

_log = get_logger("services.react")


class EventType(str, Enum):
    """Event types for streaming responses."""
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
    """Event emitted during chat processing."""
    type: EventType
    content: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ReActConfig:
    """Configuration for ReAct loop."""
    max_loops: int = REACT_MAX_LOOPS
    temperature: float = REACT_DEFAULT_TEMPERATURE
    max_tokens: int = REACT_DEFAULT_MAX_TOKENS
    enable_thinking: bool = False
    thinking_level: str = "high"


@dataclass
class ReActResult:
    """Final result from ReAct loop execution."""
    full_response: str
    loops_completed: int
    llm_elapsed_ms: float


class ReActLoopService:
    """Service for executing ReAct (Reasoning + Acting) loops."""

    def __init__(
        self,
        tool_service: Optional[ToolExecutionService] = None
    ):
        """Initialize ReAct service.

        Args:
            tool_service: Service for executing tools
        """
        self.tool_service = tool_service

    async def run(
        self,
        prompt: str,
        system_prompt: str,
        model_config: Any,
        available_tools: List[Any],
        config: ReActConfig,
        images: Optional[List[Dict]] = None,
        force_tool_call: bool = False,
        background_tasks: Optional[List] = None
    ) -> AsyncGenerator[ChatEvent, None]:
        """
        Execute ReAct loop with streaming events.

        Args:
            prompt: User prompt
            system_prompt: System prompt with context
            model_config: LLM model configuration
            available_tools: List of available tools
            config: ReAct configuration
            images: Optional images for multimodal
            force_tool_call: Force tool call on first iteration
            background_tasks: List to track background tasks

        Yields:
            ChatEvent objects for streaming response
        """
        current_prompt = prompt
        current_system_prompt = system_prompt
        loop_count = 0
        full_response = ""

        llm_start_time = time.perf_counter()

        # Thinking indicator
        yield ChatEvent(EventType.THINKING_START, "", metadata={
            "label": "Thinking...",
            "collapsed": True
        })

        while loop_count < config.max_loops:
            loop_count += 1
            pending_function_calls = []
            text_buffer = ""

            try:
                _log.debug("LLM client init", provider=model_config.provider, model=model_config.model)
                llm = get_llm_client(model_config.provider, model_config.model)

                async for text, is_thought, function_call in llm.generate_stream(
                    prompt=current_prompt,
                    system_prompt=current_system_prompt,
                    temperature=config.temperature,
                    max_tokens=config.max_tokens,
                    images=images,
                    enable_thinking=config.enable_thinking,
                    thinking_level=config.thinking_level,
                    tools=available_tools,
                    force_tool_call=force_tool_call
                ):
                    if function_call:
                        # Flush buffered text before tool call
                        if text_buffer:
                            filtered_buffer = strip_xml_tags(text_buffer)
                            if filtered_buffer:
                                full_response += filtered_buffer
                                yield ChatEvent(EventType.TEXT, filtered_buffer)
                            text_buffer = ""
                        pending_function_calls.append(function_call)
                        _log.debug("TOOL detect", name=function_call["name"])
                    elif text:
                        if is_thought:
                            yield ChatEvent(EventType.THINKING, text)
                        else:
                            # Buffer text to detect partial tool tags
                            text_buffer += text

                            if has_partial_tool_tag(text_buffer):
                                continue

                            # Filter and emit
                            filtered_text = strip_xml_tags(text_buffer)
                            text_buffer = ""

                            if filtered_text:
                                full_response += filtered_text
                                yield ChatEvent(EventType.TEXT, filtered_text)

                # Flush remaining buffer
                if text_buffer:
                    filtered_buffer = strip_xml_tags(text_buffer)
                    if filtered_buffer:
                        full_response += filtered_buffer
                        yield ChatEvent(EventType.TEXT, filtered_buffer)

            except Exception as e:
                error_str = str(e).lower()
                _log.error("LLM stream error", error=str(e)[:200], partial_len=len(full_response))

                if full_response.strip():
                    _log.warning("LLM partial used", chars=len(full_response))
                    break

                # Generate fallback response based on error type
                fallback = self._get_fallback_response(error_str)
                _log.info("LLM fallback", error_type=error_str[:30])

                full_response = fallback
                yield ChatEvent(EventType.TEXT, fallback)
                break

            # If no tools pending, we're done
            if not pending_function_calls:
                break

            # Execute tools
            yield ChatEvent(EventType.STATUS, " 도구 실행 중...")

            if self.tool_service:
                execution_result = await self.tool_service.execute_tools(pending_function_calls)

                # Emit tool events
                for result in execution_result.results:
                    yield ChatEvent(EventType.TOOL_START, "", metadata={
                        "tool_name": result.name,
                        "tool_args": {}
                    })
                    yield ChatEvent(EventType.TOOL_END, "", metadata={
                        "tool_name": result.name,
                        "success": result.success,
                        "result_preview": result.output[:200] if result.output else "",
                        "error": result.error
                    })

                # Spawn deferred tools
                if execution_result.deferred_tools and background_tasks is not None:
                    self.tool_service.spawn_deferred_task(
                        execution_result.deferred_tools,
                        background_tasks
                    )

                # Build next prompt by accumulating tool results
                if execution_result.observation:
                    current_prompt += (
                        f"\n\n[도구 실행 결과]:\n{execution_result.observation}\n\n"
                        f"이전에 이미 전달한 내용은 반복하지 말고, 위 결과만 바탕으로 이어서 자연스럽게 보고해."
                    )
                    force_tool_call = False
                    _log.debug("REACT loop", iteration=loop_count)
                else:
                    break
            else:
                _log.warning("No tool service available")
                break

        # Handle max loops reached
        if loop_count >= config.max_loops and pending_function_calls:
            async for event in self._generate_final_response(
                current_prompt,
                current_system_prompt,
                model_config,
                config,
            ):
                if event.type == EventType.TEXT:
                    full_response += event.content
                yield event

        llm_elapsed = (time.perf_counter() - llm_start_time) * 1000

        yield ChatEvent(EventType.THINKING_END, "", metadata={
            "loops_completed": loop_count
        })

        # Store final response in metadata
        yield ChatEvent(EventType.CONTROL, "", metadata={
            "react_result": ReActResult(
                full_response=full_response,
                loops_completed=loop_count,
                llm_elapsed_ms=llm_elapsed
            )
        })

    async def _generate_final_response(
        self,
        current_prompt: str,
        system_prompt: str,
        model_config: Any,
        config: ReActConfig,
    ) -> AsyncGenerator[ChatEvent, None]:
        """Generate final response when max loops reached."""
        _log.info("MAX_LOOPS reached, generating final response")

        try:
            llm = get_llm_client(model_config.provider, model_config.model)
            final_prompt = current_prompt + "\n\n[시스템: 도구 사용 한도에 도달했습니다. 지금까지의 결과를 종합해서 사용자에게 최종 응답을 해주세요.]"
            final_buffer = ""

            async for text, is_thought, function_call in llm.generate_stream(
                prompt=final_prompt,
                system_prompt=system_prompt,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                enable_thinking=False,
                tools=None  # Disable tools for final response
            ):
                if text and not is_thought:
                    final_buffer += text

                    if has_partial_tool_tag(final_buffer):
                        continue

                    filtered_text = strip_xml_tags(final_buffer)
                    final_buffer = ""
                    if filtered_text:
                        yield ChatEvent(EventType.TEXT, filtered_text)

            # Flush remaining
            if final_buffer:
                filtered_text = strip_xml_tags(final_buffer)
                if filtered_text:
                    yield ChatEvent(EventType.TEXT, filtered_text)

        except Exception as e:
            _log.error("Final response generation failed", error=str(e))
            fallback = "도구 실행은 완료했는데, 최종 정리하다가 문제가 생겼어. 위 결과를 참고해줘!"
            yield ChatEvent(EventType.TEXT, fallback)

    def _get_fallback_response(self, error_str: str) -> str:
        """Get appropriate fallback response based on error type."""
        if '503' in error_str or 'overloaded' in error_str:
            return "지금 서버가 좀 바빠. 잠시 후에 다시 물어봐줄래?"
        elif 'timeout' in error_str:
            return "응답이 좀 늦어지고 있어. 조금만 기다려주거나 다시 시도해봐!"
        elif 'circuit breaker' in error_str:
            return "잠시 쉬어가는 중이야. 30초 정도 후에 다시 해볼래?"
        elif '429' in error_str or 'rate' in error_str:
            return "요청이 좀 많았나봐. 잠깐 쉬었다가 다시 해보자!"
        else:
            return "뭔가 문제가 생겼어. 다시 시도해볼래?"
