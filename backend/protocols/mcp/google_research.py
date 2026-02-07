import asyncio
import importlib.util
import sys
import time
from pathlib import Path

AXEL_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(AXEL_ROOT))

from dotenv import load_dotenv
load_dotenv(AXEL_ROOT / ".env")

from backend.core.logging import get_logger
from backend.core.utils.gemini_client import get_gemini_client
from backend.core.utils.retry import retry_async, RetryConfig, DEFAULT_RETRY_CONFIG
from backend.config import RESEARCH_POLL_INTERVAL, RESEARCH_MAX_POLL_TIME

_log = get_logger("protocols.google")

POLL_INTERVAL_SECONDS = RESEARCH_POLL_INTERVAL
MAX_POLL_TIME_SECONDS = RESEARCH_MAX_POLL_TIME

GOOGLE_RETRY_CONFIG = RetryConfig(
    max_retries=3,
    base_delay=10.0,
    max_delay=60.0,
    jitter=0.3,
    retryable_patterns=DEFAULT_RETRY_CONFIG.retryable_patterns | {"failed", "cancelled"},
)


class GoogleResearchError(Exception):
    """Google Research 실행 중 발생한 에러."""
    pass


async def google_deep_research(query: str, depth: int = 3) -> str:
    """Google Deep Research 실행."""

    if importlib.util.find_spec("google.genai") is None:
        return "Error: google-genai package not installed. Run: pip install google-genai"

    total_start = time.time()

    async def _execute_research() -> str:
        """단일 research 시도를 실행."""
        _log.info("REQ handling", tool="google_deep_research", query=query[:80])

        client = get_gemini_client()

        interaction = client.interactions.create(
            input=query,
            agent="deep-research-pro-preview-12-2025",
            background=True
        )

        _log.info("Research started", interaction_id=interaction.id, query=query[:50])

        poll_start = time.time()
        while True:
            elapsed = time.time() - poll_start
            if elapsed > MAX_POLL_TIME_SECONDS:
                _log.warning("Research timeout", dur_ms=int(elapsed * 1000), max_ms=MAX_POLL_TIME_SECONDS * 1000)
                return f"Error: Research timeout after {int(elapsed)} seconds. Query may be too complex."

            interaction = client.interactions.get(interaction.id)
            _log.debug("Poll status", status=interaction.status, elapsed_s=int(elapsed))

            if interaction.status == "completed":
                for output in interaction.outputs:
                    if hasattr(output, 'text') and output.text:
                        dur_ms = int((time.time() - total_start) * 1000)
                        _log.info("RES complete", tool="google_deep_research", dur_ms=dur_ms, chars=len(output.text))
                        return output.text

                _log.warning("Completed but no text output", interaction_id=interaction.id)
                return "Error: Research completed but no text output found"

            elif interaction.status in ["failed", "cancelled"]:
                _log.error("Research status failed", status=interaction.status, interaction_id=interaction.id)
                raise GoogleResearchError(f"Research {interaction.status}: {interaction.id}")

            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    def _on_retry(attempt: int, error: Exception, delay: float):
        _log.warning(
            "Google research retry",
            attempt=attempt,
            error=str(error),
            delay=round(delay, 2)
        )

    try:
        return await retry_async(
            _execute_research,
            config=GOOGLE_RETRY_CONFIG,
            on_retry=_on_retry
        )
    except Exception as e:
        dur_ms = int((time.time() - total_start) * 1000)
        _log.error("Research exhausted retries", dur_ms=dur_ms, error=str(e))
        return f"Error: Google Deep Research failed. Last error: {str(e)}"
