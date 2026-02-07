"""
Async task tracking system for long-running operations.

Tracks progress of background tasks like Google Deep Research.
"""

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from backend.core.logging import get_logger

_log = get_logger("task_tracker")


class TaskStatus(Enum):
    """Task execution status."""
    PENDING = "pending"      # Created but not started
    RUNNING = "running"      # Currently executing
    COMPLETED = "completed"  # Finished successfully
    FAILED = "failed"        # Finished with error
    CANCELLED = "cancelled"  # Manually cancelled


@dataclass
class TaskInfo:
    """Information about a tracked task."""

    task_id: str
    name: str
    status: TaskStatus
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    progress: float = 0.0  # 0.0 - 1.0
    progress_message: str = ""
    result: Optional[Any] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def duration_seconds(self) -> Optional[float]:
        """Get task duration in seconds."""
        if not self.started_at:
            return None
        end_time = self.completed_at or datetime.now()
        return (end_time - self.started_at).total_seconds()

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "task_id": self.task_id,
            "name": self.name,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "progress": self.progress,
            "progress_message": self.progress_message,
            "duration_seconds": self.duration_seconds,
            "has_result": self.result is not None,
            "error": self.error,
            "metadata": self.metadata,
        }


class TaskTracker:
    """
    Singleton task tracker for managing async operations.

    Usage:
        tracker = get_task_tracker()
        task_id = tracker.create_task("google_research")

        tracker.start_task(task_id)
        tracker.update_progress(task_id, 0.5, "Processing results...")

        # On completion:
        tracker.complete_task(task_id, result={"findings": [...]})

        # Or on failure:
        tracker.fail_task(task_id, "API error: rate limited")
    """

    def __init__(self, max_tasks: int = 100):
        self._tasks: Dict[str, TaskInfo] = {}
        self._max_tasks = max_tasks
        self._lock = asyncio.Lock()

    async def create_task(
        self,
        name: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Create a new tracked task.

        Args:
            name: Task name/type
            metadata: Optional additional data

        Returns:
            Unique task ID
        """
        async with self._lock:
            task_id = str(uuid.uuid4())[:8]
            self._tasks[task_id] = TaskInfo(
                task_id=task_id,
                name=name,
                status=TaskStatus.PENDING,
                created_at=datetime.now(),
                metadata=metadata or {},
            )
            await self._cleanup_old_tasks()
            _log.debug("task created", task_id=task_id, name=name)
            return task_id

    async def start_task(self, task_id: str) -> bool:
        """Mark task as started."""
        async with self._lock:
            if task_id not in self._tasks:
                return False
            task = self._tasks[task_id]
            task.status = TaskStatus.RUNNING
            task.started_at = datetime.now()
            _log.debug("task started", task_id=task_id)
            return True

    async def update_progress(
        self,
        task_id: str,
        progress: float,
        message: str = ""
    ) -> bool:
        """
        Update task progress.

        Args:
            task_id: Task ID
            progress: Progress value (0.0 - 1.0)
            message: Optional progress message
        """
        async with self._lock:
            if task_id not in self._tasks:
                return False
            task = self._tasks[task_id]
            task.progress = max(0.0, min(1.0, progress))
            task.progress_message = message
            if task.status == TaskStatus.PENDING:
                task.status = TaskStatus.RUNNING
                task.started_at = datetime.now()
            return True

    async def complete_task(
        self,
        task_id: str,
        result: Optional[Any] = None
    ) -> bool:
        """Mark task as completed with optional result."""
        async with self._lock:
            if task_id not in self._tasks:
                return False
            task = self._tasks[task_id]
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now()
            task.progress = 1.0
            task.result = result
            _log.info(
                "task completed",
                task_id=task_id,
                name=task.name,
                duration=task.duration_seconds,
            )
            return True

    async def fail_task(self, task_id: str, error: str) -> bool:
        """Mark task as failed with error message."""
        async with self._lock:
            if task_id not in self._tasks:
                return False
            task = self._tasks[task_id]
            task.status = TaskStatus.FAILED
            task.completed_at = datetime.now()
            task.error = error
            _log.warning(
                "task failed",
                task_id=task_id,
                name=task.name,
                error=error[:100],
            )
            return True

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a pending or running task."""
        async with self._lock:
            if task_id not in self._tasks:
                return False
            task = self._tasks[task_id]
            if task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
                task.status = TaskStatus.CANCELLED
                task.completed_at = datetime.now()
                _log.info("task cancelled", task_id=task_id, name=task.name)
                return True
            return False

    def get_task(self, task_id: str) -> Optional[TaskInfo]:
        """Get task info by ID."""
        return self._tasks.get(task_id)

    def get_task_dict(self, task_id: str) -> Optional[dict]:
        """Get task info as dictionary."""
        task = self._tasks.get(task_id)
        return task.to_dict() if task else None

    def list_active_tasks(self) -> List[TaskInfo]:
        """Get all active (pending or running) tasks."""
        return [
            t for t in self._tasks.values()
            if t.status in (TaskStatus.PENDING, TaskStatus.RUNNING)
        ]

    def list_recent_tasks(self, limit: int = 10) -> List[TaskInfo]:
        """Get most recent tasks."""
        sorted_tasks = sorted(
            self._tasks.values(),
            key=lambda t: t.created_at,
            reverse=True
        )
        return sorted_tasks[:limit]

    def get_all_tasks_summary(self) -> dict:
        """Get summary of all tasks."""
        by_status = {}
        for task in self._tasks.values():
            status = task.status.value
            by_status[status] = by_status.get(status, 0) + 1

        return {
            "total": len(self._tasks),
            "by_status": by_status,
            "active": [t.to_dict() for t in self.list_active_tasks()],
        }

    async def _cleanup_old_tasks(self) -> None:
        """Remove old completed/failed tasks if over limit."""
        if len(self._tasks) <= self._max_tasks:
            return

        # Get completed/failed tasks sorted by completion time
        finished = [
            (k, v) for k, v in self._tasks.items()
            if v.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
        ]
        finished.sort(key=lambda x: x[1].completed_at or x[1].created_at)

        # Remove oldest finished tasks
        to_remove = len(self._tasks) - self._max_tasks
        for k, _ in finished[:to_remove]:
            del self._tasks[k]

        if to_remove > 0:
            _log.debug("cleaned up tasks", count=to_remove)


from backend.core.utils.lazy import Lazy

_tracker: Lazy[TaskTracker] = Lazy(TaskTracker)


def get_task_tracker() -> TaskTracker:
    """Get the global task tracker instance."""
    return _tracker.get()
