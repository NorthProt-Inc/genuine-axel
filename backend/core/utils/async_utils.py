import asyncio
from typing import Callable, Any, Optional

from backend.core.logging import get_logger

_logger = get_logger("async_utils")

class ConcurrencyLimitError(Exception):

    pass

_thread_semaphore: Optional[asyncio.Semaphore] = None
_MAX_CONCURRENT_THREADS = 8

def _get_semaphore() -> asyncio.Semaphore:

    global _thread_semaphore
    if _thread_semaphore is None:
        _thread_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_THREADS)
    return _thread_semaphore

async def bounded_to_thread(
    func: Callable[..., Any],
    *args,
    timeout_seconds: float = 30.0,
    **kwargs
) -> Any:

    semaphore = _get_semaphore()

    try:

        acquired = await asyncio.wait_for(
            semaphore.acquire(),
            timeout=5.0
        )
    except asyncio.TimeoutError:
        raise ConcurrencyLimitError(
            f"Could not acquire thread slot within 5s. "
            f"Max concurrent: {_MAX_CONCURRENT_THREADS}"
        )

    try:

        return await asyncio.wait_for(
            asyncio.to_thread(func, *args, **kwargs),
            timeout=timeout_seconds
        )
    except asyncio.TimeoutError:
        raise TimeoutError(
            f"Operation timed out after {timeout_seconds}s: {func.__name__}"
        )
    except asyncio.CancelledError:

        raise
    finally:
        semaphore.release()
