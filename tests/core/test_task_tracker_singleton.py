"""Tests for task_tracker singleton via Lazy[T]."""

from backend.core.utils.task_tracker import get_task_tracker, TaskTracker


class TestTaskTrackerSingleton:
    """get_task_tracker() should use Lazy[T] pattern."""

    def test_returns_task_tracker(self) -> None:
        tracker = get_task_tracker()
        assert isinstance(tracker, TaskTracker)

    def test_returns_same_instance(self) -> None:
        first = get_task_tracker()
        second = get_task_tracker()
        assert first is second

    def test_reset_creates_new_instance(self) -> None:
        from backend.core.utils.lazy import Lazy

        first = get_task_tracker()
        Lazy.reset_all()
        second = get_task_tracker()
        assert first is not second

    def test_no_class_level_instance_attr(self) -> None:
        """TaskTracker should not maintain its own _instance class var."""
        assert not hasattr(TaskTracker, "_instance") or TaskTracker._instance is None
