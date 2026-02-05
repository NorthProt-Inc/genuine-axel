"""Importance calculation functions for memory storage."""

import re
import asyncio
from backend.core.logging import get_logger

_log = get_logger("memory.importance")

IMPORTANCE_TIMEOUT_SECONDS = 120


async def calculate_importance_async(
    user_msg: str,
    ai_msg: str,
    persona_context: str = "",
) -> float:
    """Calculate importance score asynchronously using LLM.

    Args:
        user_msg: User's message
        ai_msg: AI's response
        persona_context: Optional persona context

    Returns:
        Importance score 0.0-1.0
    """
    from backend.core.utils.gemini_wrapper import get_gemini_wrapper

    try:
        model = get_gemini_wrapper()

        prompt = f"""다음 대화의 장기 기억 저장 중요도를 평가하세요.

대화:
User: {user_msg[:500]}
AI: {ai_msg[:500]}

페르소나 컨텍스트: {persona_context[:200] if persona_context else "없음"}

중요도 기준:
- 0.9+: 사용자 개인정보, 중요한 사실 (이름, 직업, 건강)
- 0.7-0.8: 선호도, 습관, 프로젝트 관련
- 0.5-0.6: 일반적인 대화, 정보 요청
- 0.3 이하: 인사, 잡담, 일시적 질문

숫자만 응답하세요 (예: 0.75):"""

        def _call_sync():
            response = model.generate_content_sync(
                contents=prompt,
                stream=False,
                timeout_seconds=IMPORTANCE_TIMEOUT_SECONDS,
            )
            text = response.text.strip()

            match = re.search(r"(0\.\d+|1\.0|1)", text)
            if match:
                return float(match.group(1))
            return 0.7

        importance = await asyncio.to_thread(_call_sync)
        _log.debug("MEM importance", score=importance, input_len=len(user_msg))
        return importance

    except TimeoutError:
        _log.warning("MEM importance timeout", timeout=IMPORTANCE_TIMEOUT_SECONDS)
        return 0.7

    except Exception as e:
        _log.warning("MEM importance fail", error=str(e)[:100])
        return 0.7


def calculate_importance_sync(
    user_msg: str,
    ai_msg: str,
    persona_context: str = "",
) -> float:
    """Calculate importance score synchronously using LLM.

    Args:
        user_msg: User's message
        ai_msg: AI's response
        persona_context: Optional persona context

    Returns:
        Importance score 0.0-1.0
    """
    from backend.core.utils.gemini_wrapper import get_gemini_wrapper

    try:
        model = get_gemini_wrapper()

        prompt = f"""다음 대화의 장기 기억 저장 중요도를 평가하세요.

대화:
User: {user_msg[:500]}
AI: {ai_msg[:500]}

페르소나 컨텍스트: {persona_context[:200] if persona_context else "없음"}

중요도 기준:
- 0.9+: 사용자 개인정보, 중요한 사실 (이름, 직업, 건강)
- 0.7-0.8: 선호도, 습관, 프로젝트 관련
- 0.5-0.6: 일반적인 대화, 정보 요청
- 0.3 이하: 인사, 잡담, 일시적 질문

숫자만 응답하세요 (예: 0.75):"""

        response = model.generate_content_sync(
            contents=prompt,
            stream=False,
            timeout_seconds=IMPORTANCE_TIMEOUT_SECONDS,
        )
        text = response.text.strip()

        match = re.search(r"(0\.\d+|1\.0|1)", text)
        if match:
            importance = float(match.group(1))
            _log.debug("MEM importance", score=importance, input_len=len(user_msg))
            return importance

        return 0.7

    except TimeoutError:
        _log.warning("MEM importance timeout", timeout=IMPORTANCE_TIMEOUT_SECONDS)
        return 0.7

    except Exception as e:
        _log.warning("MEM importance fail", error=str(e)[:100])
        return 0.7
