"""Browser lifecycle management for headless Playwright."""

import asyncio
import random
import time
from typing import Optional

from playwright.async_api import async_playwright

from backend.core.logging import get_logger
from backend.protocols.mcp.research.config import (
    BROWSER_IDLE_TIMEOUT,
    BROWSER_MAX_USES,
    USER_AGENTS,
)

_log = get_logger("research.browser")


from backend.core.utils.lazy import Lazy as _Lazy


class BrowserManager:
    """Manages a single Playwright browser instance with auto-restart and idle cleanup."""

    _lock: asyncio.Lock = asyncio.Lock()

    def __init__(self) -> None:
        self._playwright = None
        self._browser = None
        self._context = None
        self._use_count: int = 0
        self._max_uses: int = BROWSER_MAX_USES
        self._last_used: float = 0.0
        self._idle_timeout: int = BROWSER_IDLE_TIMEOUT
        self._idle_checker: Optional[asyncio.Task] = None

    @classmethod
    async def get_instance(cls) -> "BrowserManager":
        """Return the singleton BrowserManager, creating if needed."""
        return _browser_instance.get()

    async def get_page(self):
        """Create and return a new browser page.

        Automatically restarts the browser when max_uses is exceeded.
        """
        async with self._lock:
            if self._browser and self._use_count >= self._max_uses:
                _log.info("Browser restart needed", uses=self._use_count, max_uses=self._max_uses)
                await self._cleanup()

            if self._playwright is None:
                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(
                    headless=True,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--disable-dev-shm-usage",
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-gpu",
                        "--disable-extensions",
                    ],
                )
                self._context = await self._browser.new_context(
                    user_agent=random.choice(USER_AGENTS),
                    viewport={"width": 1920, "height": 1080},
                    locale="en-US",
                    timezone_id="America/New_York",
                )
                await self._context.route(
                    "**/*.{png,jpg,jpeg,gif,svg,ico,webp,woff,woff2,ttf}",
                    lambda route: route.abort(),
                )
                _log.info("Browser launched successfully")

            self._use_count += 1
            self._last_used = time.time()

            if self._idle_checker is None or self._idle_checker.done():
                self._start_idle_checker()

            return await self._context.new_page()

    def _start_idle_checker(self) -> None:
        """Start a background task that cleans up the browser after idle timeout."""

        async def _check_idle():
            while True:
                await asyncio.sleep(60)
                async with self._lock:
                    if self._playwright is None:
                        break
                    elapsed = time.time() - self._last_used
                    if elapsed >= self._idle_timeout:
                        _log.info(
                            "Browser idle cleanup",
                            idle_sec=int(elapsed),
                            uses=self._use_count,
                        )
                        await self._cleanup_inner()
                        break

        self._idle_checker = asyncio.create_task(_check_idle())

    async def _cleanup_inner(self) -> None:
        """Release all browser resources, tolerating individual failures."""
        try:
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception as e:
            _log.error("Browser cleanup error", error=str(e))
        finally:
            self._playwright = None
            self._browser = None
            self._context = None
            self._use_count = 0
            self._last_used = 0.0
            self._idle_checker = None

    async def _cleanup(self) -> None:
        """Cancel idle checker then release resources."""
        if self._idle_checker and not self._idle_checker.done():
            self._idle_checker.cancel()
        await self._cleanup_inner()

    async def close(self) -> None:
        """Public close: acquire lock and clean up."""
        async with self._lock:
            await self._cleanup()


_browser_instance: _Lazy[BrowserManager] = _Lazy(BrowserManager)


async def get_browser_manager() -> BrowserManager:
    """Return the singleton BrowserManager instance."""
    return _browser_instance.get()
