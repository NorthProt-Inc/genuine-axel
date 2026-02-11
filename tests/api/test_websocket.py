"""Tests for WebSocket support (Wave 3.3)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.api.websocket import router as ws_router, MAX_MESSAGE_SIZE


class TestWebSocketConstants:

    def test_max_message_size(self):
        assert MAX_MESSAGE_SIZE == 65536

class TestWebSocketAuth:

    def test_router_exists(self):
        app = FastAPI()
        app.include_router(ws_router)
        assert any(r.path == "/ws" for r in app.routes)
