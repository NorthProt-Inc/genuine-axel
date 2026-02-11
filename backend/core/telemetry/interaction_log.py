"""LLM interaction telemetry logging."""

import json
from dataclasses import dataclass, field
from typing import Optional, List
from backend.core.logging import get_logger

_log = get_logger("core.telemetry")


@dataclass
class InteractionLog:
    """Single LLM interaction record."""

    session_id: str = ""
    channel_id: str = "default"
    effective_model: str = ""
    tier: str = "standard"
    router_reason: str = ""
    latency_ms: int = 0
    ttft_ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    tool_calls: List[str] = field(default_factory=list)
    error: Optional[str] = None


def log_interaction(conn_mgr, log: InteractionLog) -> int:
    """Store interaction log to SQLite.

    Args:
        conn_mgr: SQLiteConnectionManager instance
        log: InteractionLog to store

    Returns:
        Row ID of inserted record
    """
    with conn_mgr.get_connection() as conn:
        cursor = conn.execute(
            """INSERT INTO interaction_logs
            (conversation_id, effective_model, tier,
             router_reason, latency_ms, ttft_ms, tokens_in, tokens_out,
             tool_calls_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                log.session_id,
                log.effective_model,
                log.tier,
                log.router_reason,
                log.latency_ms,
                log.ttft_ms,
                log.tokens_in,
                log.tokens_out,
                json.dumps(log.tool_calls),
            ),
        )
        conn.commit()
        return cursor.lastrowid


def query_interactions(
    conn_mgr, session_id: str = None, limit: int = 50
) -> List[dict]:
    """Query interaction logs, optionally filtered by session.

    Args:
        conn_mgr: SQLiteConnectionManager instance
        session_id: Optional session ID filter
        limit: Maximum records to return

    Returns:
        List of interaction log dicts
    """
    with conn_mgr.get_connection() as conn:
        if session_id:
            rows = conn.execute(
                "SELECT * FROM interaction_logs WHERE conversation_id = ? ORDER BY ts DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM interaction_logs ORDER BY ts DESC LIMIT ?",
                (limit,),
            ).fetchall()

        # Get column names from table info
        table_info = conn.execute("PRAGMA table_info(interaction_logs)").fetchall()
        col_names = [c[1] for c in table_info]

        result = []
        for row in rows:
            result.append(dict(zip(col_names, row)))
        return result
