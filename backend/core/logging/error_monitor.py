
import os
import time
import asyncio
from typing import Dict
from dataclasses import dataclass
from datetime import datetime
from backend.core.logging import get_logger

_logger = get_logger("error_monitor")

@dataclass
class ErrorCounter:

    count: int = 0
    first_seen: float = 0.0
    last_seen: float = 0.0

class ErrorMonitor:

    WINDOW_SECONDS = 300
    THRESHOLDS = {
        "503": 3,
        "429": 5,
        "timeout": 5,
    }
    ALERT_COOLDOWN = 600

    def __init__(self):
        self._counters: Dict[str, ErrorCounter] = {}
        self._last_alert: Dict[str, float] = {}
        self._discord_webhook = os.getenv("DISCORD_WEBHOOK_URL")

    def record(self, error_type: str, details: str = "") -> None:

        now = time.time()

        if error_type not in self._counters:
            self._counters[error_type] = ErrorCounter()

        counter = self._counters[error_type]

        if now - counter.first_seen > self.WINDOW_SECONDS:
            counter.count = 0
            counter.first_seen = now

        counter.count += 1
        counter.last_seen = now

        _logger.debug("Error recorded",
                     error_type=error_type,
                     count=counter.count,
                     window_seconds=self.WINDOW_SECONDS)

        threshold = self.THRESHOLDS.get(error_type, 10)
        if counter.count >= threshold:
            self._trigger_alert(error_type, counter, details)

    def _trigger_alert(self, error_type: str, counter: ErrorCounter, details: str) -> None:

        now = time.time()
        last = self._last_alert.get(error_type, 0)

        if now - last < self.ALERT_COOLDOWN:
            _logger.debug("Alert suppressed (cooldown)",
                         error_type=error_type,
                         cooldown_remaining=int(self.ALERT_COOLDOWN - (now - last)))
            return

        self._last_alert[error_type] = now

        _logger.critical(f"ALERT: {error_type} errors exceeded threshold",
                        count=counter.count,
                        window_seconds=self.WINDOW_SECONDS,
                        threshold=self.THRESHOLDS.get(error_type),
                        details=details[:200] if details else "")

        if self._discord_webhook:
            try:
                asyncio.create_task(self._send_discord_alert(error_type, counter, details))
            except RuntimeError:

                _logger.debug("Discord alert skipped (no event loop)")

    async def _send_discord_alert(self, error_type: str, counter: ErrorCounter, details: str) -> None:

        try:
            import aiohttp

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            message = {
                "embeds": [{
                    "title": f"AXEL Alert: {error_type.upper()}",
                    "color": 0xFF0000,
                    "fields": [
                        {"name": "Error Type", "value": error_type, "inline": True},
                        {"name": "Count", "value": str(counter.count), "inline": True},
                        {"name": "Window", "value": f"{self.WINDOW_SECONDS}s", "inline": True},
                        {"name": "Details", "value": details[:500] if details else "N/A", "inline": False},
                    ],
                    "footer": {"text": f"AXEL Backend - {timestamp}"}
                }]
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(self._discord_webhook, json=message) as resp:
                    if resp.status == 204:
                        _logger.info("Discord alert sent", error_type=error_type)
                    else:
                        _logger.warning("Discord alert failed", status=resp.status)

        except Exception as e:
            _logger.error("Discord alert error", error=str(e))

    def get_stats(self) -> Dict[str, Dict]:

        now = time.time()
        stats = {}
        for error_type, counter in self._counters.items():
            if now - counter.first_seen <= self.WINDOW_SECONDS:
                stats[error_type] = {
                    "count": counter.count,
                    "first_seen": counter.first_seen,
                    "last_seen": counter.last_seen,
                    "threshold": self.THRESHOLDS.get(error_type, 10),
                }
        return stats

error_monitor = ErrorMonitor()
