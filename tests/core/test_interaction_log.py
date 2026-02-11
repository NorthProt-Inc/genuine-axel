"""Tests for interaction logging."""

import pytest
from backend.core.telemetry.interaction_log import (
    InteractionLog,
    log_interaction,
    query_interactions,
)


class TestInteractionLog:

    def test_log_interaction_stored(self, initialized_db):
        log = InteractionLog(
            session_id="test-session-1",
            effective_model="gemini-3-flash",
            tier="standard",
            router_reason="default",
            latency_ms=150,
            tokens_in=100,
            tokens_out=200,
        )
        row_id = log_interaction(initialized_db, log)
        assert row_id > 0

    def test_query_by_session(self, initialized_db):
        for i in range(3):
            log = InteractionLog(
                session_id="session-A",
                effective_model="gemini",
                tier="standard",
                router_reason="test",
            )
            log_interaction(initialized_db, log)

        log_other = InteractionLog(
            session_id="session-B",
            effective_model="claude",
            tier="premium",
            router_reason="test",
        )
        log_interaction(initialized_db, log_other)

        results = query_interactions(initialized_db, session_id="session-A")
        assert len(results) == 3

    def test_missing_optional_fields(self, initialized_db):
        log = InteractionLog(
            effective_model="test-model",
            tier="standard",
            router_reason="test",
        )
        row_id = log_interaction(initialized_db, log)
        assert row_id > 0
