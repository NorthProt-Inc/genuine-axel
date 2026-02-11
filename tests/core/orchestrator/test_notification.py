"""Tests for notification scheduler (Wave 2.3)."""

from datetime import datetime

import pytest

from backend.core.orchestrator.notification import (
    NotificationRule,
    NotificationScheduler,
    parse_cron_field,
)


class TestParseCronField:

    def test_wildcard(self):
        assert parse_cron_field("*", 0, 59) == set(range(60))

    def test_single_value(self):
        assert parse_cron_field("5", 0, 59) == {5}

    def test_range(self):
        assert parse_cron_field("1-5", 0, 59) == {1, 2, 3, 4, 5}

    def test_list(self):
        assert parse_cron_field("1,3,5", 0, 59) == {1, 3, 5}

    def test_step(self):
        assert parse_cron_field("*/15", 0, 59) == {0, 15, 30, 45}

    def test_range_with_step(self):
        assert parse_cron_field("0-30/10", 0, 59) == {0, 10, 20, 30}

    def test_invalid_value_raises(self):
        with pytest.raises(ValueError):
            parse_cron_field("abc", 0, 59)

    def test_out_of_range_clamped(self):
        result = parse_cron_field("100", 0, 59)
        assert 100 not in result


class TestNotificationRule:

    def test_create_rule(self):
        rule = NotificationRule(
            rule_id="morning",
            cron="0 8 * * *",
            message="Good morning!",
        )
        assert rule.rule_id == "morning"
        assert rule.enabled is True

    def test_matches_time(self):
        rule = NotificationRule(
            rule_id="test",
            cron="30 14 * * *",
            message="Test",
        )
        dt = datetime(2024, 1, 15, 14, 30)
        assert rule.matches(dt) is True

    def test_no_match(self):
        rule = NotificationRule(
            rule_id="test",
            cron="30 14 * * *",
            message="Test",
        )
        dt = datetime(2024, 1, 15, 15, 0)
        assert rule.matches(dt) is False

    def test_disabled_never_matches(self):
        rule = NotificationRule(
            rule_id="test",
            cron="* * * * *",
            message="Test",
            enabled=False,
        )
        dt = datetime(2024, 1, 15, 14, 30)
        assert rule.matches(dt) is False


class TestNotificationScheduler:

    def test_add_rule(self):
        scheduler = NotificationScheduler()
        scheduler.add_rule(NotificationRule("r1", "0 8 * * *", "Hello"))
        assert len(scheduler.rules) == 1

    def test_remove_rule(self):
        scheduler = NotificationScheduler()
        scheduler.add_rule(NotificationRule("r1", "0 8 * * *", "Hello"))
        scheduler.remove_rule("r1")
        assert len(scheduler.rules) == 0

    def test_enable_disable(self):
        scheduler = NotificationScheduler()
        rule = NotificationRule("r1", "0 8 * * *", "Hello")
        scheduler.add_rule(rule)
        scheduler.disable_rule("r1")
        assert scheduler.rules[0].enabled is False
        scheduler.enable_rule("r1")
        assert scheduler.rules[0].enabled is True

    def test_check_and_send(self):
        sent = []

        def sender(msg: str) -> bool:
            sent.append(msg)
            return True

        scheduler = NotificationScheduler(sender=sender)
        scheduler.add_rule(NotificationRule("r1", "30 14 * * *", "Time!"))

        dt = datetime(2024, 1, 15, 14, 30)
        results = scheduler.check_and_send(dt)
        assert len(results) == 1
        assert results[0]["success"] is True
        assert sent == ["Time!"]

    def test_check_no_match(self):
        scheduler = NotificationScheduler(sender=lambda m: True)
        scheduler.add_rule(NotificationRule("r1", "30 14 * * *", "Time!"))

        dt = datetime(2024, 1, 15, 15, 0)
        results = scheduler.check_and_send(dt)
        assert len(results) == 0

    def test_sender_failure_tracked(self):
        def failing_sender(msg: str) -> bool:
            return False

        scheduler = NotificationScheduler(sender=failing_sender)
        scheduler.add_rule(NotificationRule("r1", "30 14 * * *", "Time!"))

        dt = datetime(2024, 1, 15, 14, 30)
        results = scheduler.check_and_send(dt)
        assert results[0]["success"] is False
