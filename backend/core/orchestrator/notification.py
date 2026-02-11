"""Cron-based notification scheduler.

Supports 5-field cron expressions with wildcards, ranges, lists, and steps.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from backend.core.logging import get_logger

_log = get_logger("core.orchestrator.notification")


def parse_cron_field(expr: str, min_val: int, max_val: int) -> set[int]:
    """Parse a single cron field into a set of matching values."""
    result: set[int] = set()

    for part in expr.split(","):
        part = part.strip()

        if "/" in part:
            base, step_str = part.split("/", 1)
            step = int(step_str)
            if base == "*":
                start, end = min_val, max_val
            elif "-" in base:
                s, e = base.split("-", 1)
                start, end = int(s), int(e)
            else:
                start, end = min_val, max_val
            result.update(range(start, end + 1, step))

        elif "-" in part:
            s, e = part.split("-", 1)
            result.update(range(int(s), int(e) + 1))

        elif part == "*":
            result.update(range(min_val, max_val + 1))

        else:
            try:
                val = int(part)
            except ValueError:
                raise ValueError(f"Invalid cron value: {part}")
            if min_val <= val <= max_val:
                result.add(val)

    return result


@dataclass
class NotificationRule:
    """A cron-scheduled notification rule."""

    rule_id: str
    cron: str
    message: str
    enabled: bool = True

    def matches(self, dt: datetime) -> bool:
        """Check if this rule matches the given datetime."""
        if not self.enabled:
            return False

        parts = self.cron.split()
        if len(parts) != 5:
            return False

        minute, hour, dom, month, dow = parts

        return (
            dt.minute in parse_cron_field(minute, 0, 59)
            and dt.hour in parse_cron_field(hour, 0, 23)
            and dt.day in parse_cron_field(dom, 1, 31)
            and dt.month in parse_cron_field(month, 1, 12)
            and dt.weekday() in parse_cron_field(dow, 0, 6)
        )


class NotificationScheduler:
    """Manages and triggers cron-based notifications."""

    def __init__(self, sender: Callable[[str], bool] | None = None) -> None:
        self.rules: list[NotificationRule] = []
        self._sender = sender

    def add_rule(self, rule: NotificationRule) -> None:
        self.rules.append(rule)

    def remove_rule(self, rule_id: str) -> None:
        self.rules = [r for r in self.rules if r.rule_id != rule_id]

    def enable_rule(self, rule_id: str) -> None:
        for r in self.rules:
            if r.rule_id == rule_id:
                r.enabled = True

    def disable_rule(self, rule_id: str) -> None:
        for r in self.rules:
            if r.rule_id == rule_id:
                r.enabled = False

    def check_and_send(self, now: datetime) -> list[dict]:
        """Check all rules and send matching notifications."""
        results = []

        for rule in self.rules:
            if not rule.matches(now):
                continue

            success = False
            if self._sender:
                try:
                    success = self._sender(rule.message)
                except Exception as e:
                    _log.warning("notification_send_error", rule=rule.rule_id, error=str(e))

            results.append({
                "rule_id": rule.rule_id,
                "success": success,
            })

        return results
