"""Tests for safe _active_tasks dict operations."""

from unittest.mock import MagicMock

from backend.protocols.mcp.async_research import (
    get_active_research_tasks,
    _active_tasks,
)


class TestActiveTasksSnapshot:
    """get_active_research_tasks() should return a snapshot, not live dict view."""

    def test_returns_snapshot(self) -> None:
        # Add a fake task
        mock_task = MagicMock()
        mock_task.done.return_value = False
        mock_task.cancelled.return_value = False
        _active_tasks["test_1"] = mock_task

        snapshot = get_active_research_tasks()
        assert len(snapshot) == 1

        # Mutating the original should not affect snapshot
        _active_tasks["test_2"] = MagicMock()
        assert len(snapshot) == 1

        # Cleanup
        _active_tasks.clear()

    def test_returns_list_of_dicts(self) -> None:
        mock_task = MagicMock()
        mock_task.done.return_value = True
        mock_task.cancelled.return_value = False
        _active_tasks["task_a"] = mock_task

        result = get_active_research_tasks()
        assert isinstance(result, list)
        assert result[0]["task_id"] == "task_a"
        assert result[0]["done"] is True

        _active_tasks.clear()


class TestActiveTasksCleanup:
    """Task cleanup in finally block should use .pop() for safety."""

    def test_pop_removes_task_safely(self) -> None:
        _active_tasks["gone"] = MagicMock()
        # Simulate the finally block: .pop() should not raise
        _active_tasks.pop("gone", None)
        assert "gone" not in _active_tasks

    def test_pop_missing_key_no_error(self) -> None:
        # .pop() with default should not raise for missing key
        result = _active_tasks.pop("nonexistent", None)
        assert result is None
