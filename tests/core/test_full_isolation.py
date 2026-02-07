"""Integration test: full isolation across all Lazy singletons and AppState."""


from backend.api.deps import get_state
from backend.core.utils.rate_limiter import get_embedding_limiter
from backend.core.utils.task_tracker import get_task_tracker
from backend.core.utils.async_utils import _get_semaphore


class TestFullIsolationA:
    """Create singletons and mutate AppState."""

    def test_create_all_singletons(self) -> None:
        state = get_state()
        state.gemini_client = "test_model_a"
        state.turn_count = 99

        limiter = get_embedding_limiter()
        tracker = get_task_tracker()
        semaphore = _get_semaphore()

        TestFullIsolationA.limiter_id = id(limiter)
        TestFullIsolationA.tracker_id = id(tracker)
        TestFullIsolationA.semaphore_id = id(semaphore)

        assert limiter is not None
        assert tracker is not None
        assert semaphore is not None


class TestFullIsolationB:
    """After conftest reset, all singletons and state should be fresh."""

    def test_all_singletons_are_fresh(self) -> None:
        state = get_state()
        # AppState should have been reset
        assert state.gemini_client is None
        assert state.turn_count == 0

        # All singletons should be new instances
        limiter = get_embedding_limiter()
        tracker = get_task_tracker()
        semaphore = _get_semaphore()

        assert id(limiter) != TestFullIsolationA.limiter_id
        assert id(tracker) != TestFullIsolationA.tracker_id
        assert id(semaphore) != TestFullIsolationA.semaphore_id
