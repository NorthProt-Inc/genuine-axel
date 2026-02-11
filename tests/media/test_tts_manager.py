"""Tests for backend.media.tts_manager - TTSManager class.

Covers:
- touch(): updates last_used, increments counter, starts idle checker
- _check_idle(): monitors and triggers unload after timeout
- _unload(): resets lazy singletons, clears CUDA cache, runs gc
- shutdown(): cancels idle checker and unloads
- get_tts_manager(): lazy singleton factory
"""

import asyncio
import gc
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.media.tts_manager import TTSManager, get_tts_manager


# ---------------------------------------------------------------------------
# TTSManager.touch()
# ---------------------------------------------------------------------------


class TestTouch:

    def test_updates_last_used(self) -> None:
        mgr = TTSManager(idle_timeout=300)
        before = time.time()
        mgr.touch()
        after = time.time()

        assert before <= mgr._last_used <= after

    def test_increments_use_count(self) -> None:
        mgr = TTSManager(idle_timeout=300)
        assert mgr._use_count == 0

        mgr.touch()
        assert mgr._use_count == 1

        mgr.touch()
        assert mgr._use_count == 2

    async def test_starts_idle_checker_task(self) -> None:
        mgr = TTSManager(idle_timeout=300)
        assert mgr._idle_checker is None

        mgr.touch()

        assert mgr._idle_checker is not None
        assert not mgr._idle_checker.done()

        # Cleanup
        mgr._idle_checker.cancel()
        try:
            await mgr._idle_checker
        except asyncio.CancelledError:
            pass

    async def test_does_not_restart_running_checker(self) -> None:
        mgr = TTSManager(idle_timeout=300)
        mgr.touch()
        first_task = mgr._idle_checker

        mgr.touch()
        assert mgr._idle_checker is first_task

        # Cleanup
        mgr._idle_checker.cancel()
        try:
            await mgr._idle_checker
        except asyncio.CancelledError:
            pass

    def test_no_event_loop_does_not_crash(self) -> None:
        """touch() without a running event loop should not raise."""
        mgr = TTSManager(idle_timeout=300)
        # In a non-async context with no running loop, touch() catches RuntimeError
        # but since pytest-asyncio provides a loop, we simulate by patching
        with patch("asyncio.get_running_loop", side_effect=RuntimeError):
            mgr.touch()

        assert mgr._use_count == 1
        assert mgr._idle_checker is None


# ---------------------------------------------------------------------------
# TTSManager._check_idle()
# ---------------------------------------------------------------------------


class TestCheckIdle:

    async def test_unloads_after_timeout(self) -> None:
        mgr = TTSManager(idle_timeout=0)  # immediate timeout
        mgr._last_used = time.time() - 10  # well past timeout

        with patch.object(mgr, "_unload") as mock_unload:
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                await mgr._check_idle()

        mock_unload.assert_called_once()

    async def test_exits_when_last_used_zero(self) -> None:
        mgr = TTSManager(idle_timeout=300)
        mgr._last_used = 0.0

        with patch.object(mgr, "_unload") as mock_unload:
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await mgr._check_idle()

        mock_unload.assert_not_called()


# ---------------------------------------------------------------------------
# TTSManager._unload()
# ---------------------------------------------------------------------------


class TestUnload:

    def test_resets_lazy_singletons(self) -> None:
        mgr = TTSManager(idle_timeout=300)
        mgr._use_count = 5

        mock_model = MagicMock()
        mock_voice = MagicMock()

        with (
            patch("backend.media.tts_manager._lazy_model", mock_model, create=True),
            patch("backend.media.tts_manager._lazy_voice_prompt", mock_voice, create=True),
            patch.dict("sys.modules", {
                "backend.media.qwen_tts": MagicMock(_lazy_model=mock_model, _lazy_voice_prompt=mock_voice),
                "backend.api.audio": MagicMock(_lazy_tts=MagicMock()),
                "backend.media.tts_service": MagicMock(_lazy_tts=MagicMock()),
                "torch": MagicMock(cuda=MagicMock(is_available=MagicMock(return_value=False))),
            }),
            patch("gc.collect") as mock_gc,
        ):
            mgr._unload()

        assert mgr._use_count == 0
        mock_gc.assert_called_once()

    def test_handles_missing_audio_module(self) -> None:
        """_unload gracefully handles ImportError from backend.api.audio."""
        mgr = TTSManager(idle_timeout=300)
        mgr._use_count = 3

        mock_model = MagicMock()
        mock_voice = MagicMock()

        with (
            patch.dict("sys.modules", {
                "backend.media.qwen_tts": MagicMock(_lazy_model=mock_model, _lazy_voice_prompt=mock_voice),
                "torch": MagicMock(cuda=MagicMock(is_available=MagicMock(return_value=False))),
            }),
            patch("gc.collect"),
        ):
            # If backend.api.audio doesn't exist, _unload catches ImportError
            mgr._unload()

        assert mgr._use_count == 0

    def test_handles_cuda_error_gracefully(self) -> None:
        """CUDA cache clear failure is caught and logged."""
        mgr = TTSManager(idle_timeout=300)
        mgr._use_count = 2

        mock_model = MagicMock()
        mock_voice = MagicMock()
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.empty_cache.side_effect = RuntimeError("CUDA error")

        with (
            patch.dict("sys.modules", {
                "backend.media.qwen_tts": MagicMock(_lazy_model=mock_model, _lazy_voice_prompt=mock_voice),
                "torch": mock_torch,
            }),
            patch("gc.collect"),
        ):
            # Should not raise
            mgr._unload()

        assert mgr._use_count == 0


# ---------------------------------------------------------------------------
# TTSManager.shutdown()
# ---------------------------------------------------------------------------


class TestShutdown:

    async def test_cancels_idle_checker(self) -> None:
        mgr = TTSManager(idle_timeout=9999)
        mgr.touch()
        assert mgr._idle_checker is not None

        with (
            patch.object(mgr, "_unload"),
        ):
            await mgr.shutdown()

        assert mgr._idle_checker.done()

    async def test_shutdown_without_checker(self) -> None:
        mgr = TTSManager(idle_timeout=300)
        assert mgr._idle_checker is None

        with patch.object(mgr, "_unload") as mock_unload:
            await mgr.shutdown()

        mock_unload.assert_called_once()

    async def test_shutdown_with_already_done_checker(self) -> None:
        mgr = TTSManager(idle_timeout=300)
        # Create a completed task
        mgr._idle_checker = asyncio.get_event_loop().create_future()
        mgr._idle_checker.set_result(None)

        with patch.object(mgr, "_unload") as mock_unload:
            await mgr.shutdown()

        mock_unload.assert_called_once()


# ---------------------------------------------------------------------------
# get_tts_manager singleton
# ---------------------------------------------------------------------------


class TestGetTTSManager:

    def test_returns_tts_manager_instance(self) -> None:
        mgr = get_tts_manager()
        assert isinstance(mgr, TTSManager)

    def test_returns_same_instance(self) -> None:
        mgr1 = get_tts_manager()
        mgr2 = get_tts_manager()
        assert mgr1 is mgr2


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


class TestConstructor:

    def test_default_idle_timeout(self) -> None:
        from backend.config import TTS_IDLE_TIMEOUT

        mgr = TTSManager()
        assert mgr._idle_timeout == TTS_IDLE_TIMEOUT

    def test_custom_idle_timeout(self) -> None:
        mgr = TTSManager(idle_timeout=42)
        assert mgr._idle_timeout == 42

    def test_initial_state(self) -> None:
        mgr = TTSManager(idle_timeout=100)
        assert mgr._last_used == 0.0
        assert mgr._idle_checker is None
        assert mgr._use_count == 0
