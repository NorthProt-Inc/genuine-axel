import asyncio
import random
import time
from dataclasses import dataclass, field
from collections.abc import AsyncGenerator
from typing import Any, Callable, Optional, Set, TypeVar
from backend.core.logging import get_logger

_log = get_logger("retry")

T = TypeVar("T")

@dataclass
class RetryConfig:

    max_retries: int = 5
    base_delay: float = 2.0
    max_delay: float = 60.0
    jitter: float = 0.3
    retryable_check: Callable[[Exception], bool] | None = None

    retryable_patterns: Set[str] = field(default_factory=lambda: {
        "429", "resource_exhausted",
        "500", "502", "503",
        "timeout", "overloaded",
        "unavailable",

        "ssl", "certificate", "handshake",
        "connection reset", "broken pipe", "eof occurred",
    })

DEFAULT_RETRY_CONFIG = RetryConfig()

def is_retryable_error(error: Exception, config: RetryConfig | None = None) -> bool:

    config = config or DEFAULT_RETRY_CONFIG
    if config.retryable_check is not None:
        return config.retryable_check(error)
    error_str = str(error).lower()
    return any(pattern in error_str for pattern in config.retryable_patterns)

def classify_error(error: Exception) -> str:

    error_str = str(error).lower()

    if any(x in error_str for x in ["ssl", "certificate", "handshake",
                                     "connection reset", "broken pipe", "eof occurred"]):
        return "ssl"
    elif "429" in error_str or "resource_exhausted" in error_str:
        return "rate_limit"
    elif any(x in error_str for x in ["503", "unavailable", "overloaded"]):
        return "server_error"
    elif "timeout" in error_str:
        return "timeout"
    elif any(x in error_str for x in ["500", "502"]):
        return "server_error"
    else:
        return "unknown"

def calculate_backoff(
    attempt: int,
    error_type: str = "unknown",
    config: RetryConfig = None
) -> float:

    config = config or DEFAULT_RETRY_CONFIG

    delay = config.base_delay * (2 ** (attempt - 1))

    if error_type == "server_error":
        delay *= 1.5
    elif error_type == "rate_limit":
        delay *= 1.0
    elif error_type == "timeout":
        delay *= 1.2

    jitter = random.uniform(0, config.jitter)
    delay *= (1 + jitter)

    return min(delay, config.max_delay)

async def retry_async(
    func: Callable[..., Any],
    *args,
    config: RetryConfig = None,
    on_retry: Optional[Callable[[int, Exception, float], None]] = None,
    **kwargs
) -> Any:

    config = config or DEFAULT_RETRY_CONFIG
    last_error = None

    for attempt in range(1, config.max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            last_error = e

            if not is_retryable_error(e, config) or attempt == config.max_retries:
                raise

            error_type = classify_error(e)
            delay = calculate_backoff(attempt, error_type, config)

            _log.warning(
                "Retry scheduled",
                attempt=attempt,
                max_retries=config.max_retries,
                error_type=error_type,
                delay=round(delay, 2),
                error_preview=str(e)[:100]
            )

            if on_retry:
                on_retry(attempt, e, delay)

            await asyncio.sleep(delay)

    raise last_error

def retry_sync(
    func: Callable[..., Any],
    *args,
    config: RetryConfig = None,
    on_retry: Optional[Callable[[int, Exception, float], None]] = None,
    **kwargs
) -> Any:

    config = config or DEFAULT_RETRY_CONFIG
    last_error = None

    for attempt in range(1, config.max_retries + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_error = e

            if not is_retryable_error(e, config) or attempt == config.max_retries:
                raise

            error_type = classify_error(e)
            delay = calculate_backoff(attempt, error_type, config)

            _log.warning(
                "Retry scheduled (sync)",
                attempt=attempt,
                max_retries=config.max_retries,
                error_type=error_type,
                delay=round(delay, 2),
                error_preview=str(e)[:100]
            )

            if on_retry:
                on_retry(attempt, e, delay)

            time.sleep(delay)

    raise last_error


async def retry_async_generator(
    factory: Callable[..., AsyncGenerator[Any, None]],
    *args: Any,
    config: RetryConfig | None = None,
    on_retry: Callable[[int, Exception, float], None] | None = None,
    **kwargs: Any,
) -> AsyncGenerator[Any, None]:
    """Retry an async generator factory on retryable errors.

    Calls *factory* to create an async generator and iterates it. If a
    retryable exception is raised during iteration, the factory is called
    again (up to ``config.max_retries`` total attempts). Items already
    yielded from earlier attempts are **not** suppressed -- callers must
    handle partial data if necessary.

    Args:
        factory: Zero-arg async generator factory (or accepts *args/**kwargs).
        config: Retry configuration.
        on_retry: Optional callback ``(attempt, error, delay)``.
    """
    config = config or DEFAULT_RETRY_CONFIG

    for attempt in range(1, config.max_retries + 1):
        try:
            async for item in factory(*args, **kwargs):
                yield item
            return  # generator exhausted normally
        except Exception as e:
            if not is_retryable_error(e, config) or attempt == config.max_retries:
                raise

            error_type = classify_error(e)
            delay = calculate_backoff(attempt, error_type, config)

            _log.warning(
                "Retry scheduled (async generator)",
                attempt=attempt,
                max_retries=config.max_retries,
                error_type=error_type,
                delay=round(delay, 2),
                error_preview=str(e)[:100],
            )

            if on_retry:
                on_retry(attempt, e, delay)

            await asyncio.sleep(delay)
