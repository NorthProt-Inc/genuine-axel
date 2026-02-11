"""Tests for session state machine."""

import pytest
from backend.core.session.state_machine import (
    SessionStateMachine,
    SessionState,
    SessionTransitionError,
)


class TestSessionStateMachine:

    def test_valid_transition_sequence(self):
        sm = SessionStateMachine("test-session")
        assert sm.state == SessionState.INITIALIZING

        sm.transition(SessionState.ACTIVE)
        assert sm.state == SessionState.ACTIVE

        sm.transition(SessionState.THINKING)
        assert sm.state == SessionState.THINKING

        sm.transition(SessionState.ACTIVE)
        assert sm.state == SessionState.ACTIVE

        sm.transition(SessionState.ENDING)
        assert sm.state == SessionState.ENDING

        sm.transition(SessionState.ENDED)
        assert sm.state == SessionState.ENDED

    def test_invalid_transition_raises(self):
        sm = SessionStateMachine("test-session")
        with pytest.raises(SessionTransitionError, match="Invalid"):
            sm.transition(SessionState.ENDED)

    def test_thinking_tool_loop(self):
        sm = SessionStateMachine("test-session")
        sm.transition(SessionState.ACTIVE)
        sm.transition(SessionState.THINKING)

        for _ in range(3):
            sm.transition(SessionState.TOOL_EXECUTING)
            assert sm.state == SessionState.TOOL_EXECUTING
            sm.transition(SessionState.THINKING)
            assert sm.state == SessionState.THINKING

    def test_ended_is_terminal(self):
        sm = SessionStateMachine("test-session")
        sm.transition(SessionState.ACTIVE)
        sm.transition(SessionState.ENDING)
        sm.transition(SessionState.ENDED)

        with pytest.raises(SessionTransitionError):
            sm.transition(SessionState.ACTIVE)
        with pytest.raises(SessionTransitionError):
            sm.transition(SessionState.INITIALIZING)
