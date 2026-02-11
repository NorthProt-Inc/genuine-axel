"""Interaction logging — PostgreSQL backend."""

import json
from typing import Dict, List, Set

from backend.core.logging import get_logger

from .connection import PgConnectionManager

_log = get_logger("memory.pg.interaction")


class PgInteractionLogger:
    """PostgreSQL replacement for SQLite InteractionLogger."""

    def __init__(self, conn_mgr: PgConnectionManager):
        self._conn = conn_mgr
        self._known_session_ids: Set[str] = set()  # PERF-039: Cache known session IDs

    def log_interaction(
        self,
        routing_decision: dict,
        conversation_id: str = None,
        turn_id: int = None,
        latency_ms: int = None,
        ttft_ms: int = None,
        tokens_in: int = None,
        tokens_out: int = None,
        tool_calls: list = None,
        refusal_detected: bool = False,
        response_text: str = None,
    ) -> bool:
        try:
            # session_id FK → sessions(session_id); pass None if not yet persisted
            safe_session_id = self._resolve_session_id(conversation_id)

            self._conn.execute(
                """INSERT INTO interaction_logs (
                       session_id, turn_id,
                       effective_model, tier, router_reason,
                       latency_ms, ttft_ms, tokens_in, tokens_out,
                       tool_calls, error
                   ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)""",
                (
                    safe_session_id,
                    turn_id,
                    routing_decision.get("effective_model", "unknown"),
                    routing_decision.get("tier", "unknown"),
                    routing_decision.get("router_reason", "unknown"),
                    latency_ms,
                    ttft_ms,
                    tokens_in,
                    tokens_out,
                    json.dumps(tool_calls, ensure_ascii=False) if tool_calls else "[]",
                    routing_decision.get("error"),
                ),
            )

            _log.debug(
                "Interaction logged",
                tier=routing_decision.get("tier"),
                router_reason=routing_decision.get("router_reason"),
                latency_ms=latency_ms,
            )
            return True
        except Exception as e:
            _log.error("Log interaction failed", error=str(e))
            return False

    def _resolve_session_id(self, session_id: str | None) -> str | None:
        """Return session_id only if it exists in the sessions table."""
        if not session_id:
            return None
        # PERF-039: Check cache first to avoid DB query
        if session_id in self._known_session_ids:
            return session_id
        row = self._conn.execute_one(
            "SELECT 1 FROM sessions WHERE session_id = %s", (session_id,)
        )
        if row:
            self._known_session_ids.add(session_id)
            return session_id
        return None

    def get_recent_logs(self, limit: int = 20) -> List[Dict]:
        try:
            return self._conn.execute_dict(
                "SELECT * FROM interaction_logs ORDER BY ts DESC LIMIT %s",
                (limit,),
            )
        except Exception as e:
            _log.error("Get interaction logs failed", error=str(e))
            return []
