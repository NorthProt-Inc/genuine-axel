"""TTS model lifecycle manager with idle unloading.

Tracks last usage time and automatically unloads the TTS model
(Qwen3-TTS + PyTorch/CUDA runtime) after an idle timeout to
reclaim ~2GB of memory.
"""

import asyncio
import gc
import time

from backend.config import TTS_IDLE_TIMEOUT
from backend.core.logging import get_logger
from backend.core.utils.lazy import Lazy

_log = get_logger("media.tts_manager")


class TTSManager:
    """Manages TTS model lifecycle with idle-based unloading."""

    def __init__(self, idle_timeout: int = TTS_IDLE_TIMEOUT) -> None:
        self._idle_timeout = idle_timeout
        self._last_used: float = 0.0
        self._idle_checker: asyncio.Task[None] | None = None
        self._use_count: int = 0

    def touch(self) -> None:
        """Record TTS usage and start idle checker if not running."""
        self._last_used = time.time()
        self._use_count += 1

        if self._idle_checker is None or self._idle_checker.done():
            try:
                loop = asyncio.get_running_loop()
                self._idle_checker = loop.create_task(self._check_idle())
            except RuntimeError:
                pass

    async def _check_idle(self) -> None:
        """Periodically check if TTS has been idle long enough to unload."""
        while True:
            await asyncio.sleep(60)
            if self._last_used == 0.0:
                break
            elapsed = time.time() - self._last_used
            if elapsed >= self._idle_timeout:
                _log.info(
                    "TTS idle unload",
                    idle_sec=int(elapsed),
                    uses=self._use_count,
                )
                self._unload()
                break

    def _unload(self) -> None:
        """Release TTS model and CUDA memory."""
        from backend.media.qwen_tts import _lazy_model, _lazy_voice_prompt

        _lazy_model.reset()
        _lazy_voice_prompt.reset()

        # Reset the Qwen3TTS singleton in whichever module owns it
        try:
            from backend.api.audio import _lazy_tts

            _lazy_tts.reset()
        except ImportError:
            pass

        try:
            from backend.media.tts_service import _lazy_tts as _svc_lazy_tts

            _svc_lazy_tts.reset()
        except ImportError:
            pass

        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception as e:
            _log.warning("CUDA cache clear failed", error=str(e))

        gc.collect()
        self._use_count = 0
        _log.info("TTS model unloaded")

    async def shutdown(self) -> None:
        """Cancel idle checker and unload model."""
        if self._idle_checker and not self._idle_checker.done():
            self._idle_checker.cancel()
            try:
                await self._idle_checker
            except asyncio.CancelledError:
                pass

        self._unload()
        _log.info("TTSManager shutdown complete")


def _create_tts_manager() -> TTSManager:
    """Factory for lazy TTSManager singleton."""
    return TTSManager()


_lazy_tts_manager: Lazy[TTSManager] = Lazy(_create_tts_manager)


def get_tts_manager() -> TTSManager:
    """Return the TTSManager singleton (thread-safe lazy init)."""
    return _lazy_tts_manager.get()
