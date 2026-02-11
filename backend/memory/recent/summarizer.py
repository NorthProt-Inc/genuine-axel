"""Session summarization using LLM."""

from typing import Any, Dict, List, Optional

from backend.config import MESSAGE_SUMMARY_MODEL
from backend.core.logging import get_logger

_log = get_logger("memory.recent.summarizer")


class SessionSummarizer:
    """Generates LLM summaries for expired sessions and archives them.

    Args:
        repo: SessionRepository for data access.
    """

    def __init__(self, repo: Any):
        self._repo = repo

    async def generate_summary(
        self, messages: List[Any], llm_client=None
    ) -> Optional[str]:
        """Generate a summary from session messages.

        Args:
            messages: List of message records (dicts or Row objects).
            llm_client: Optional pre-configured LLM client.

        Returns:
            Summary string, or None on failure/empty input.
        """
        if not messages:
            return None

        conversation_text = []
        for msg in messages[:50]:
            role = msg["role"] if msg["role"] else "unknown"
            content = (msg["content"] or "")[:500]
            conversation_text.append(f"{role}: {content}")

        full_conversation = "\n".join(conversation_text)

        prompt = f"""다음 대화를 간결하게 요약해주세요.

대화 내용:
{full_conversation[:5000]}

요약 규칙:
- 핵심 주제와 결론만 포함
- 2-3문장으로 요약
- 사용자가 요청한 것과 AI가 제공한 것 중심
- 중요한 정보(이름, 날짜, 결정사항)는 보존

요약:"""

        try:
            if llm_client:
                response = await llm_client.generate(prompt, max_tokens=300)
            else:
                from backend.llm import get_llm_client

                llm = get_llm_client("gemini", MESSAGE_SUMMARY_MODEL)
                response = await llm.generate(prompt, max_tokens=300)

            if response:
                return response.strip()
            return None
        except Exception as e:
            _log.warning("Summary generation failed", error=str(e))
            return None

    async def summarize_expired(self, llm_client=None) -> Dict[str, int]:
        """Archive and summarize messages from expired sessions.

        Args:
            llm_client: Optional LLM client for summary generation.

        Returns:
            Dict with sessions_processed and messages_archived counts.
        """
        result = {"sessions_processed": 0, "messages_archived": 0}

        try:
            expired_sessions = self._repo.get_expired_sessions(limit=10)

            if not expired_sessions:
                _log.debug("No expired sessions to summarize")
                return result

            _log.info("Summarizing expired sessions", count=len(expired_sessions))

            for session_id in expired_sessions:
                try:
                    messages = self._repo.get_session_messages_for_archive(session_id)
                    if not messages:
                        continue

                    summary = await self.generate_summary(messages, llm_client)
                    if not summary:
                        _log.warning(
                            "Failed to generate summary", session_id=session_id[:8]
                        )
                        continue

                    self._repo.archive_session(session_id, messages, summary)

                    result["sessions_processed"] += 1
                    result["messages_archived"] += len(messages)

                    _log.info(
                        "Session summarized",
                        session_id=session_id[:8],
                        messages=len(messages),
                        summary_len=len(summary),
                    )
                except Exception as e:
                    _log.error(
                        "Session summarize failed",
                        session_id=session_id[:8],
                        error=str(e),
                    )
                    continue

        except Exception as e:
            _log.error("Summarize expired failed", error=str(e))

        return result
