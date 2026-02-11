"""Importance calculation functions for memory storage."""

import re
from backend.core.logging import get_logger
from backend.core.utils.gemini_client import get_gemini_client, get_model_name, gemini_generate

_log = get_logger("memory.importance")

IMPORTANCE_TIMEOUT_SECONDS = 120


def _build_importance_prompt(user_msg: str, ai_msg: str, persona_context: str) -> str:
    """Build the importance scoring prompt.

    Args:
        user_msg: User's message
        ai_msg: AI's response
        persona_context: Optional persona context

    Returns:
        Formatted prompt string
    """
    return f"""다음 대화의 장기 기억 저장 중요도를 평가하세요.

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


def _parse_importance(text: str) -> float:
    """Parse importance score from LLM response.

    Args:
        text: Raw LLM response text

    Returns:
        Parsed importance score (default 0.7)
    """
    match = re.search(r"(0\.\d+|1\.0|1)", text.strip())
    if match:
        return float(match.group(1))
    return 0.5


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
    try:
        prompt = _build_importance_prompt(user_msg, ai_msg, persona_context)
        response = await gemini_generate(
            contents=prompt,
            timeout_seconds=IMPORTANCE_TIMEOUT_SECONDS,
        )
        importance = _parse_importance(response.text if response.text else "")
        _log.debug("MEM importance", score=importance, input_len=len(user_msg))
        return importance

    except TimeoutError:
        _log.warning("MEM importance timeout", timeout=IMPORTANCE_TIMEOUT_SECONDS)
        return 0.5

    except Exception as e:
        _log.warning("MEM importance fail", error=str(e)[:100])
        return 0.5


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
    try:
        client = get_gemini_client()
        prompt = _build_importance_prompt(user_msg, ai_msg, persona_context)
        response = client.models.generate_content(
            model=get_model_name(),
            contents=prompt,
        )
        text = response.text if response.text else ""
        importance = _parse_importance(text)
        _log.debug("MEM importance", score=importance, input_len=len(user_msg))
        return importance

    except TimeoutError:
        _log.warning("MEM importance timeout", timeout=IMPORTANCE_TIMEOUT_SECONDS)
        return 0.5

    except Exception as e:
        _log.warning("MEM importance fail", error=str(e)[:100])
        return 0.5
