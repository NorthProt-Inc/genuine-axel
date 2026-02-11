"""Tests for backend.core.logging.error_monitor module.

Covers: ErrorCounter, ErrorMonitor.record(), threshold alerts, cooldown,
get_stats(), Discord alert dispatch.
"""

import time
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

from backend.core.logging.error_monitor import ErrorCounter, ErrorMonitor


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def monitor():
    """Fresh ErrorMonitor with no Discord webhook."""
    m = ErrorMonitor()
    m._discord_webhook = None
    return m


@pytest.fixture
def monitor_with_webhook():
    """ErrorMonitor with a fake Discord webhook URL."""
    m = ErrorMonitor()
    m._discord_webhook = "https://discord.com/api/webhooks/fake"
    return m


# ---------------------------------------------------------------------------
# ErrorCounter
# ---------------------------------------------------------------------------
class TestErrorCounter:
    def test_defaults(self):
        c = ErrorCounter()
        assert c.count == 0
        assert c.first_seen == 0.0
        assert c.last_seen == 0.0

    def test_custom_values(self):
        c = ErrorCounter(count=5, first_seen=1000.0, last_seen=1005.0)
        assert c.count == 5
        assert c.first_seen == 1000.0
        assert c.last_seen == 1005.0


# ---------------------------------------------------------------------------
# ErrorMonitor.record()
# ---------------------------------------------------------------------------
class TestRecord:
    def test_first_record_creates_counter(self, monitor):
        monitor.record("503")
        assert "503" in monitor._counters
        assert monitor._counters["503"].count == 1

    def test_multiple_records_increment_count(self, monitor):
        monitor.record("503")
        monitor.record("503")
        assert monitor._counters["503"].count == 2

    def test_last_seen_updated(self, monitor):
        monitor.record("timeout")
        first_seen = monitor._counters["timeout"].last_seen
        time.sleep(0.01)
        monitor.record("timeout")
        assert monitor._counters["timeout"].last_seen >= first_seen

    def test_window_resets_count(self, monitor):
        """After WINDOW_SECONDS pass, count resets."""
        monitor.record("429")
        # Simulate window expiry by backdating first_seen
        monitor._counters["429"].first_seen = time.time() - monitor.WINDOW_SECONDS - 1
        monitor.record("429")
        assert monitor._counters["429"].count == 1  # reset + 1

    def test_unknown_error_type_uses_default_threshold(self, monitor):
        """Error types not in THRESHOLDS use default threshold of 10."""
        for _ in range(9):
            monitor.record("custom_error")
        # Should not have triggered an alert yet (threshold=10)
        assert monitor._counters["custom_error"].count == 9


# ---------------------------------------------------------------------------
# Alert triggering
# ---------------------------------------------------------------------------
class TestAlertTriggering:
    def test_alert_triggered_at_threshold(self, monitor):
        """503 threshold is 3 -- reaching 3 should trigger alert."""
        with patch.object(monitor, "_trigger_alert") as mock_trigger:
            for _ in range(3):
                monitor.record("503", details="server down")
            mock_trigger.assert_called_once()

    def test_alert_not_triggered_below_threshold(self, monitor):
        with patch.object(monitor, "_trigger_alert") as mock_trigger:
            monitor.record("503")
            monitor.record("503")
            mock_trigger.assert_not_called()

    def test_429_threshold(self, monitor):
        """429 threshold is 5."""
        with patch.object(monitor, "_trigger_alert") as mock_trigger:
            for _ in range(5):
                monitor.record("429")
            mock_trigger.assert_called_once()

    def test_timeout_threshold(self, monitor):
        """timeout threshold is 5."""
        with patch.object(monitor, "_trigger_alert") as mock_trigger:
            for _ in range(5):
                monitor.record("timeout")
            mock_trigger.assert_called_once()


# ---------------------------------------------------------------------------
# Alert cooldown
# ---------------------------------------------------------------------------
class TestAlertCooldown:
    def test_cooldown_prevents_repeat_alert(self, monitor):
        """Second alert within cooldown should be suppressed."""
        # First alert
        monitor.record("503")
        monitor.record("503")
        monitor.record("503")
        # Simulate window reset to trigger again
        monitor._counters["503"].first_seen = time.time() - monitor.WINDOW_SECONDS - 1
        with patch("backend.core.logging.error_monitor._log") as mock_logger:
            for _ in range(3):
                monitor.record("503")
            # critical should NOT be called again (cooldown)
            critical_calls = [
                c for c in mock_logger.critical.call_args_list
                if "ALERT" in str(c)
            ]
            assert len(critical_calls) == 0

    def test_alert_fires_after_cooldown_expires(self, monitor):
        """After cooldown, a new alert should fire."""
        # Trigger first alert
        for _ in range(3):
            monitor.record("503")
        # Backdate the last alert time past cooldown
        monitor._last_alert["503"] = time.time() - monitor.ALERT_COOLDOWN - 1
        # Reset counter window
        monitor._counters["503"].first_seen = time.time() - monitor.WINDOW_SECONDS - 1

        with patch("backend.core.logging.error_monitor._log") as mock_logger:
            for _ in range(3):
                monitor.record("503")
            assert mock_logger.critical.called


# ---------------------------------------------------------------------------
# _trigger_alert details
# ---------------------------------------------------------------------------
class TestTriggerAlert:
    def test_logs_critical_with_details(self, monitor):
        counter = ErrorCounter(count=5, first_seen=time.time())
        with patch("backend.core.logging.error_monitor._log") as mock_logger:
            monitor._trigger_alert("503", counter, "service unavailable")
            mock_logger.critical.assert_called_once()
            kwargs = mock_logger.critical.call_args[1]
            assert kwargs["count"] == 5
            assert "service unavailable" in kwargs["details"]

    def test_details_truncated_to_200(self, monitor):
        counter = ErrorCounter(count=5, first_seen=time.time())
        long_details = "x" * 300
        with patch("backend.core.logging.error_monitor._log") as mock_logger:
            monitor._trigger_alert("503", counter, long_details)
            kwargs = mock_logger.critical.call_args[1]
            assert len(kwargs["details"]) <= 200

    def test_empty_details(self, monitor):
        counter = ErrorCounter(count=5, first_seen=time.time())
        with patch("backend.core.logging.error_monitor._log") as mock_logger:
            monitor._trigger_alert("503", counter, "")
            kwargs = mock_logger.critical.call_args[1]
            assert kwargs["details"] == ""


# ---------------------------------------------------------------------------
# Discord alert
# ---------------------------------------------------------------------------
class TestDiscordAlert:
    def test_discord_task_created_when_webhook_set(self, monitor_with_webhook):
        counter = ErrorCounter(count=5, first_seen=time.time())
        with patch("asyncio.create_task") as mock_create_task:
            monitor_with_webhook._trigger_alert("503", counter, "details")
            mock_create_task.assert_called_once()

    def test_no_discord_when_no_webhook(self, monitor):
        counter = ErrorCounter(count=5, first_seen=time.time())
        with patch("asyncio.create_task") as mock_create_task:
            monitor._trigger_alert("503", counter, "details")
            mock_create_task.assert_not_called()

    def test_discord_runtime_error_caught(self, monitor_with_webhook):
        """When no event loop, RuntimeError is caught gracefully."""
        counter = ErrorCounter(count=5, first_seen=time.time())
        with patch("asyncio.create_task", side_effect=RuntimeError("no event loop")):
            # Should not raise
            monitor_with_webhook._trigger_alert("503", counter, "details")

    async def test_send_discord_alert_success(self, monitor_with_webhook):
        counter = ErrorCounter(count=5, first_seen=time.time())
        mock_resp = AsyncMock()
        mock_resp.status = 204

        mock_post_ctx = AsyncMock()
        mock_post_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_post_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_post_ctx)

        with patch.object(monitor_with_webhook, "_get_session", return_value=mock_session):
            await monitor_with_webhook._send_discord_alert("503", counter, "test details")

    async def test_send_discord_alert_failure_status(self, monitor_with_webhook):
        counter = ErrorCounter(count=5, first_seen=time.time())
        mock_resp = AsyncMock()
        mock_resp.status = 500

        mock_post_ctx = AsyncMock()
        mock_post_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_post_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_post_ctx)

        with patch.object(monitor_with_webhook, "_get_session", return_value=mock_session):
            with patch("backend.core.logging.error_monitor._log") as mock_logger:
                await monitor_with_webhook._send_discord_alert("503", counter, "test")
                mock_logger.warning.assert_called()

    async def test_send_discord_alert_exception(self, monitor_with_webhook):
        counter = ErrorCounter(count=5, first_seen=time.time())
        with patch.object(monitor_with_webhook, "_get_session", side_effect=Exception("connection error")):
            with patch("backend.core.logging.error_monitor._log") as mock_logger:
                await monitor_with_webhook._send_discord_alert("503", counter, "test")
                mock_logger.error.assert_called()


# ---------------------------------------------------------------------------
# get_stats
# ---------------------------------------------------------------------------
class TestGetStats:
    def test_empty_stats(self, monitor):
        assert monitor.get_stats() == {}

    def test_stats_within_window(self, monitor):
        monitor.record("503")
        monitor.record("503")
        stats = monitor.get_stats()
        assert "503" in stats
        assert stats["503"]["count"] == 2
        assert stats["503"]["threshold"] == 3

    def test_stats_exclude_expired(self, monitor):
        monitor.record("503")
        # Backdate past window
        monitor._counters["503"].first_seen = time.time() - monitor.WINDOW_SECONDS - 1
        stats = monitor.get_stats()
        assert "503" not in stats

    def test_stats_multiple_types(self, monitor):
        monitor.record("503")
        monitor.record("429")
        monitor.record("timeout")
        stats = monitor.get_stats()
        assert len(stats) == 3

    def test_stats_default_threshold(self, monitor):
        monitor.record("unknown_type")
        stats = monitor.get_stats()
        assert stats["unknown_type"]["threshold"] == 10


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
class TestModuleSingleton:
    def test_error_monitor_singleton_exists(self):
        from backend.core.logging.error_monitor import error_monitor
        assert isinstance(error_monitor, ErrorMonitor)
