import asyncio
from typing import Callable, Any
from backend.core.logging import get_logger

_log = get_logger("async_utils")

class ConcurrencyLimitError(Exception):
    pass

from backend.core.utils.lazy import Lazy

_MAX_CONCURRENT_THREADS = 8

_thread_semaphore: Lazy[asyncio.Semaphore] = Lazy(
    lambda: asyncio.Semaphore(_MAX_CONCURRENT_THREADS)
)


def _get_semaphore() -> asyncio.Semaphore:
    """Get the singleton thread semaphore."""
    return _thread_semaphore.get()

async def bounded_to_thread(
    func: Callable[..., Any],
    *args,
    timeout_seconds: float = 30.0,
    **kwargs
) -> Any:

    semaphore = _get_semaphore()

    try:

        await asyncio.wait_for(
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
