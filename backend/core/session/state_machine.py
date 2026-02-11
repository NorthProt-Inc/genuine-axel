"""Session lifecycle state machine."""

from enum import Enum
from backend.core.logging import get_logger

_log = get_logger("core.session")


class SessionState(str, Enum):
    INITIALIZING = "initializing"
    ACTIVE = "active"
    THINKING = "thinking"
    TOOL_EXECUTING = "tool_executing"
    SUMMARIZING = "summarizing"
    ENDING = "ending"
    ENDED = "ended"


VALID_TRANSITIONS = {
    SessionState.INITIALIZING: {SessionState.ACTIVE},
    SessionState.ACTIVE: {SessionState.THINKING, SessionState.SUMMARIZING, SessionState.ENDING},
    SessionState.THINKING: {SessionState.ACTIVE, SessionState.TOOL_EXECUTING, SessionState.SUMMARIZING},
    SessionState.TOOL_EXECUTING: {SessionState.THINKING},
    SessionState.SUMMARIZING: {SessionState.ENDING},
    SessionState.ENDING: {SessionState.ENDED},
    SessionState.ENDED: set(),
}


class SessionTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""
    pass


class SessionStateMachine:
    """Manages session lifecycle state transitions."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self._state = SessionState.INITIALIZING

    @property
    def state(self) -> SessionState:
        return self._state

    def transition(self, new_state: SessionState) -> None:
        """Transition to a new state.

        Args:
            new_state: Target state

        Raises:
            SessionTransitionError: If transition is not valid
        """
        if new_state not in VALID_TRANSITIONS.get(self._state, set()):
            raise SessionTransitionError(
                f"Invalid: {self._state.value} -> {new_state.value}"
            )
        old = self._state
        self._state = new_state
        _log.debug(
            "Session transition",
            session=self.session_id[:8],
            old=old.value,
            new=new_state.value,
        )
