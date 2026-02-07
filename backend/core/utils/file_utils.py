import os
import time
from pathlib import Path
from typing import List
from backend.core.logging import get_logger

_logger = get_logger("file_utils")

TMP_FILE_PREFIX = ".axnmihn_tmp_"

TMP_MAX_AGE_SECONDS = 3600

def fsync_directory(dir_path: Path) -> None:

    if os.name == "nt":
        return

    try:

        o_directory = getattr(os, "O_DIRECTORY", 0)
        dir_fd = os.open(str(dir_path), os.O_RDONLY | o_directory)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except (OSError, PermissionError) as e:

        _logger.warning("Directory fsync failed", path=str(dir_path), error=str(e))

def cleanup_orphaned_tmp_files(dir_path: Path) -> int:

    if not dir_path.exists():
        return 0

    now = time.time()
    deleted = 0

    try:
        for p in dir_path.iterdir():
            if not p.name.startswith(TMP_FILE_PREFIX):
                continue
            try:
                age = now - p.stat().st_mtime
                if age >= TMP_MAX_AGE_SECONDS:
                    p.unlink(missing_ok=True)
                    _logger.info("Cleaned orphaned tmp", file=p.name, age_seconds=int(age))
                    deleted += 1
            except FileNotFoundError:
                pass
            except Exception as e:
                _logger.warning("Cleanup error", file=p.name, error=str(e))
    except Exception:
        _logger.exception("Directory scan error", path=str(dir_path))

    return deleted

async def startup_cleanup(data_dirs: List[Path]) -> int:

    from backend.core.utils.async_utils import bounded_to_thread

    total = 0
    for dir_path in data_dirs:
        try:
            count = await bounded_to_thread(
                cleanup_orphaned_tmp_files,
                dir_path,
                timeout_seconds=10.0
            )
            total += count
        except Exception:
            _logger.exception("Startup cleanup error", path=str(dir_path))

    if total > 0:
        _logger.info("Startup cleanup complete", deleted_count=total)

    return total

import asyncio
from contextlib import asynccontextmanager
from typing import Dict

ENABLE_OS_LOCK = os.environ.get("ENABLE_OS_LOCK", "").lower() in ("true", "1", "yes", "on")

from backend.core.utils.lazy import Lazy

_async_locks: Dict[str, asyncio.Lock] = {}
_locks_lock: Lazy[asyncio.Lock] = Lazy(asyncio.Lock)


def _get_locks_lock() -> asyncio.Lock:
    """Get the singleton lock that guards _async_locks dict."""
    return _locks_lock.get()

def _acquire_os_lock(lock_path: str, timeout_seconds: float = 10.0) -> int:

    if os.name == "nt":
        raise RuntimeError("OS lock not supported on Windows. Set ENABLE_OS_LOCK=False")

    import fcntl
    deadline = time.monotonic() + timeout_seconds
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)

    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return fd
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"flock timeout after {timeout_seconds}s: {lock_path}")
                time.sleep(0.05)
    except Exception:
        os.close(fd)
        raise

def _release_os_lock(lock_fd: int) -> None:

    if os.name == "nt":
        return

    try:
        import fcntl
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
    except (ImportError, OSError) as e:
        _logger.warning("OS lock release failed", error=str(e))

async def get_async_file_lock(path: Path) -> asyncio.Lock:

    path_key = str(path.resolve())

    async with _get_locks_lock():
        if path_key not in _async_locks:
            _async_locks[path_key] = asyncio.Lock()
        return _async_locks[path_key]

@asynccontextmanager
async def async_file_lock(path: Path):

    os_lock_fd = None
    lock_file_path = str(path.resolve()) + ".lock"

    try:

        async_lock = await get_async_file_lock(path)
        async with async_lock:

            if ENABLE_OS_LOCK:
                from backend.core.utils.async_utils import bounded_to_thread

                if os.name == "nt":
                    _logger.warning(
                        "ENABLE_OS_LOCK is enabled but not supported on Windows",
                        hint="Set ENABLE_OS_LOCK=False or use POSIX system"
                    )
                else:

                    os_lock_fd = await bounded_to_thread(
                        _acquire_os_lock, lock_file_path, 10.0,
                        timeout_seconds=15.0
                    )

            yield
    finally:

        if os_lock_fd is not None:
            from backend.core.utils.async_utils import bounded_to_thread
            try:
                await bounded_to_thread(
                    _release_os_lock, os_lock_fd, timeout_seconds=2.0
                )
            except Exception as e:
                _logger.error("Failed to release OS lock", error=str(e))
