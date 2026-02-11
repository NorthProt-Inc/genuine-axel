"""ChannelManager — lifecycle management for channel adapters.

Registers, starts, stops, and monitors all active channel adapters.
Integrates with FastAPI lifespan for clean startup/shutdown.
"""

from __future__ import annotations

import asyncio
import time
from typing import Callable, Awaitable

from backend.channels.protocol import (
    ChannelAdapter,
    HealthStatus,
    InboundMessage,
    Platform,
)
from backend.core.logging import get_logger

_log = get_logger("channels.manager")

MessageHandler = Callable[[InboundMessage], Awaitable[None]]


class ChannelManager:
    """Manages the lifecycle of all registered channel adapters."""

    def __init__(self) -> None:
        self._adapters: dict[Platform, ChannelAdapter] = {}
        self._running: bool = False
        self._message_handler: MessageHandler | None = None

    def register(self, adapter: ChannelAdapter) -> None:
        """Register a channel adapter."""
        platform = adapter.platform
        if platform in self._adapters:
            _log.warning("CHANNEL adapter already registered, replacing", platform=platform.value)
        self._adapters[platform] = adapter
        _log.info("CHANNEL adapter registered", platform=platform.value)

    def set_message_handler(self, handler: MessageHandler) -> None:
        """Set the callback invoked when any adapter receives a message."""
        self._message_handler = handler

    async def start_all(self) -> None:
        """Start all registered adapters concurrently."""
        if not self._adapters:
            _log.info("CHANNEL no adapters registered, skipping start")
            return

        _log.info("CHANNEL starting adapters", count=len(self._adapters))
        results = await asyncio.gather(
            *(self._start_one(p, a) for p, a in self._adapters.items()),
            return_exceptions=True,
        )
        succeeded = sum(1 for r in results if r is None)
        failed = sum(1 for r in results if isinstance(r, BaseException))
        self._running = True
        _log.info("CHANNEL adapters started", succeeded=succeeded, failed=failed)

    async def _start_one(self, platform: Platform, adapter: ChannelAdapter) -> None:
        try:
            await adapter.start()
            _log.info("CHANNEL adapter started", platform=platform.value)
        except Exception:
            _log.exception("CHANNEL adapter start failed", platform=platform.value)
            raise

    async def stop_all(self) -> None:
        """Stop all running adapters gracefully."""
        if not self._running:
            return

        _log.info("CHANNEL stopping adapters", count=len(self._adapters))
        await asyncio.gather(
            *(self._stop_one(p, a) for p, a in self._adapters.items()),
            return_exceptions=True,
        )
        self._running = False
        _log.info("CHANNEL all adapters stopped")

    async def _stop_one(self, platform: Platform, adapter: ChannelAdapter) -> None:
        try:
            await adapter.stop()
            _log.info("CHANNEL adapter stopped", platform=platform.value)
        except Exception:
            _log.exception("CHANNEL adapter stop failed", platform=platform.value)

    async def health_check_all(self) -> dict[str, HealthStatus]:
        """Run health checks on all adapters."""
        results: dict[str, HealthStatus] = {}
        for platform, adapter in self._adapters.items():
            try:
                t0 = time.perf_counter()
                status = await adapter.health_check()
                status.latency_ms = (time.perf_counter() - t0) * 1000
                results[platform.value] = status
            except Exception as e:
                results[platform.value] = HealthStatus(
                    healthy=False,
                    platform=platform,
                    details=str(e),
                )
        return results

    def get_adapter(self, platform: Platform) -> ChannelAdapter | None:
        """Get a specific adapter by platform."""
        return self._adapters.get(platform)

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def registered_platforms(self) -> list[Platform]:
        return list(self._adapters.keys())
