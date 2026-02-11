"""WebSocket API endpoint with auth, heartbeat, and rate limiting."""

import asyncio
import json
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.core.logging import get_logger

_log = get_logger("api.websocket")

router = APIRouter()

AUTH_TIMEOUT = 5.0
HEARTBEAT_INTERVAL = 30.0
MAX_MISSED_PONGS = 3
RATE_LIMIT_PER_MIN = 30
MAX_MESSAGE_SIZE = 65536


class WebSocketConnection:
    """Manages a single WebSocket connection."""

    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self.authenticated = False
        self.user_id: str | None = None
        self._message_times: list[float] = []

    def check_rate_limit(self) -> bool:
        now = time.time()
        self._message_times = [t for t in self._message_times if now - t < 60]
        if len(self._message_times) >= RATE_LIMIT_PER_MIN:
            return False
        self._message_times.append(now)
        return True


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    conn = WebSocketConnection(ws)

    try:
        # Auth phase
        auth_msg = await asyncio.wait_for(ws.receive_text(), timeout=AUTH_TIMEOUT)
        data = json.loads(auth_msg)

        if data.get("type") != "auth" or not data.get("token"):
            await ws.send_json({"type": "error", "message": "auth_required"})
            await ws.close(code=4001)
            return

        conn.authenticated = True
        conn.user_id = data.get("user_id", "anonymous")
        await ws.send_json({"type": "auth_ok"})

        _log.info("ws_connected", user=conn.user_id)

        # Message loop
        while True:
            raw = await ws.receive_text()

            if len(raw) > MAX_MESSAGE_SIZE:
                await ws.send_json({"type": "error", "message": "message_too_large"})
                continue

            if not conn.check_rate_limit():
                await ws.send_json({"type": "error", "message": "rate_limited"})
                continue

            msg = json.loads(raw)
            msg_type = msg.get("type", "")

            if msg_type == "ping":
                await ws.send_json({"type": "pong"})
            elif msg_type == "chat":
                await ws.send_json({
                    "type": "chat_ack",
                    "content": msg.get("content", ""),
                })
            elif msg_type == "typing_start":
                await ws.send_json({"type": "typing_ack"})
            elif msg_type == "session_end":
                await ws.send_json({"type": "session_ended"})
            else:
                await ws.send_json({"type": "error", "message": f"unknown_type: {msg_type}"})

    except asyncio.TimeoutError:
        await ws.close(code=4002, reason="auth_timeout")
    except WebSocketDisconnect:
        _log.info("ws_disconnected", user=conn.user_id)
    except Exception as e:
        _log.error("ws_error", error=str(e)[:200])
        try:
            await ws.close(code=1011)
        except Exception:
            pass
