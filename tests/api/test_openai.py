"""Tests for backend.api.openai -- OpenAI-compatible chat endpoints."""

import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from dataclasses import dataclass

from backend.api.openai import (
    _parse_multimodal_content,
    _parse_file_attachment,
    _b64_length_to_bytes,
    _is_b64_too_large,
    MODEL_TIER_MAP,
)


# ---------------------------------------------------------------------------
# Helper event types for mocking ChatHandler.process()
# ---------------------------------------------------------------------------

@dataclass
class _FakeEvent:
    type: str
    content: str = ""
    metadata: dict = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


# ---------------------------------------------------------------------------
# Unit tests: _b64_length_to_bytes / _is_b64_too_large
# ---------------------------------------------------------------------------


class TestBase64SizeHelpers:

    def test_b64_length_to_bytes(self):
        # 4 base64 chars -> 3 bytes
        assert _b64_length_to_bytes(4) == 3
        assert _b64_length_to_bytes(100) == 75

    def test_is_b64_too_large_under_limit(self):
        assert _is_b64_too_large("AAAA", max_bytes=10) is False

    def test_is_b64_too_large_over_limit(self):
        # 100 b64 chars -> 75 bytes
        assert _is_b64_too_large("A" * 100, max_bytes=50) is True


# ---------------------------------------------------------------------------
# Unit tests: _parse_multimodal_content
# ---------------------------------------------------------------------------


class TestParseMultimodalContent:

    def test_plain_string(self):
        text, images = _parse_multimodal_content("hello world")
        assert text == "hello world"
        assert images == []

    def test_non_string_non_list(self):
        text, images = _parse_multimodal_content(42)
        assert text == "42"
        assert images == []

    def test_text_parts(self):
        content = [
            {"type": "text", "text": "Part A"},
            {"type": "text", "text": "Part B"},
        ]
        text, images = _parse_multimodal_content(content)
        assert "Part A" in text
        assert "Part B" in text
        assert images == []

    def test_image_url_data_uri(self):
        b64_data = "QUFB"  # small
        content = [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_data}"}}
        ]
        text, images = _parse_multimodal_content(content)
        assert len(images) == 1
        assert images[0]["mime_type"] == "image/png"
        assert images[0]["data"] == b64_data

    @patch("backend.api.openai.MAX_ATTACHMENT_BYTES", 1)
    def test_image_url_too_large(self):
        b64_data = "A" * 1000
        content = [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_data}"}}
        ]
        text, images = _parse_multimodal_content(content)
        assert images == []
        assert "skipped" in text.lower()

    def test_image_url_string_object(self):
        """image_url can be a plain string instead of dict."""
        content = [
            {"type": "image_url", "image_url": "https://example.com/img.png"}
        ]
        text, images = _parse_multimodal_content(content)
        # Non-data URLs are ignored (no base64 extraction), but text is appended
        assert "[Image attached]" in text
        assert images == []

    def test_file_attachment_with_content_key(self):
        content = [
            {"type": "file", "content": "file text here", "file": {}}
        ]
        text, images = _parse_multimodal_content(content)
        assert "file text here" in text

    def test_empty_list_returns_attachment_placeholder(self):
        text, images = _parse_multimodal_content([])
        assert text == "[Attachment]"
        assert images == []

    def test_skips_non_dict_parts(self):
        content = ["just a string", 42, None]
        text, images = _parse_multimodal_content(content)
        assert text == "[Attachment]"


# ---------------------------------------------------------------------------
# Unit tests: _parse_file_attachment
# ---------------------------------------------------------------------------


class TestParseFileAttachment:

    def test_part_has_content(self):
        text, images = _parse_file_attachment({}, {"content": "hello"})
        assert text == "hello"
        assert images == []

    def test_file_obj_has_content(self):
        text, images = _parse_file_attachment({"content": "from file"}, {})
        assert text == "from file"

    def test_file_obj_has_text(self):
        text, images = _parse_file_attachment({"text": "from text"}, {})
        assert text == "from text"

    def test_part_has_text(self):
        text, images = _parse_file_attachment({}, {"text": "part text"})
        assert text == "part text"

    def test_text_file_decoded(self):
        import base64
        raw = "Hello UTF-8 content"
        b64 = base64.b64encode(raw.encode()).decode()
        file_obj = {
            "file_data": f"data:text/plain;base64,{b64}",
            "filename": "readme.txt",
        }
        text, images = _parse_file_attachment(file_obj, {})
        assert "Hello UTF-8 content" in text

    def test_image_file_stored(self):
        import base64
        b64 = base64.b64encode(b"\x89PNG").decode()
        file_obj = {
            "file_data": f"data:image/png;base64,{b64}",
            "filename": "photo.png",
        }
        text, images = _parse_file_attachment(file_obj, {})
        assert len(images) == 1
        assert images[0]["mime_type"] == "image/png"

    @patch("backend.api.openai.MAX_ATTACHMENT_BYTES", 1)
    def test_file_too_large_skipped(self):
        file_obj = {
            "file_data": f"data:text/plain;base64,{'A' * 1000}",
            "filename": "big.txt",
        }
        text, images = _parse_file_attachment(file_obj, {})
        assert "skipped" in text.lower()

    def test_empty_file_obj(self):
        text, images = _parse_file_attachment({}, {})
        assert text == ""
        assert images == []


# ---------------------------------------------------------------------------
# MODEL_TIER_MAP
# ---------------------------------------------------------------------------


class TestModelTierMap:

    def test_known_models_map_to_axel(self):
        for model_name in ["axel-auto", "axel-mini", "axel", "axel-pro"]:
            assert MODEL_TIER_MAP[model_name] == "axel"

    def test_unknown_model_falls_back(self):
        # .get with default "auto"
        assert MODEL_TIER_MAP.get("unknown-model", "auto") == "auto"


# ---------------------------------------------------------------------------
# Endpoint tests: GET /v1/models
# ---------------------------------------------------------------------------


class TestListModels:

    def test_returns_model_list(self, no_auth_client):
        resp = no_auth_client.get("/v1/models")
        assert resp.status_code == 200
        body = resp.json()
        assert body["object"] == "list"
        assert len(body["data"]) >= 1
        assert body["data"][0]["id"] == "axel"
        assert body["data"][0]["owned_by"] == "axnmihn"

    def test_requires_auth_when_configured(self, client):
        """With API key configured but not supplied, should get 401."""
        import backend.api.deps as deps_mod
        import backend.config as config_mod
        original = config_mod.AXNMIHN_API_KEY
        config_mod.AXNMIHN_API_KEY = "secret"
        deps_mod.AXNMIHN_API_KEY = "secret"
        try:
            resp = client.get("/v1/models")
            assert resp.status_code == 401
        finally:
            config_mod.AXNMIHN_API_KEY = original
            deps_mod.AXNMIHN_API_KEY = original


# ---------------------------------------------------------------------------
# Endpoint tests: POST /v1/chat/completions (non-streaming)
# ---------------------------------------------------------------------------


class TestChatCompletionsNonStream:

    @patch("backend.api.openai.ChatHandler")
    def test_basic_completion(self, MockHandler, no_auth_client, mock_state):
        from backend.core.services.react_service import EventType, ChatEvent

        events = [
            ChatEvent(type=EventType.TEXT, content="Hello!"),
            ChatEvent(type=EventType.DONE),
        ]

        handler_instance = MockHandler.return_value
        handler_instance.process = MagicMock(return_value=_async_iter(events))

        resp = no_auth_client.post("/v1/chat/completions", json={
            "messages": [{"role": "user", "content": "Hi"}],
            "stream": False,
        })

        assert resp.status_code == 200
        body = resp.json()
        assert body["object"] == "chat.completion"
        assert body["choices"][0]["message"]["content"] == "Hello!"
        assert body["choices"][0]["finish_reason"] == "stop"
        assert "usage" in body

    @patch("backend.api.openai.ChatHandler")
    def test_error_event_in_response(self, MockHandler, no_auth_client, mock_state):
        from backend.core.services.react_service import EventType, ChatEvent

        events = [
            ChatEvent(type=EventType.ERROR, content="something broke"),
            ChatEvent(type=EventType.DONE),
        ]
        handler_instance = MockHandler.return_value
        handler_instance.process = MagicMock(return_value=_async_iter(events))

        resp = no_auth_client.post("/v1/chat/completions", json={
            "messages": [{"role": "user", "content": "Hi"}],
            "stream": False,
        })
        assert resp.status_code == 200
        body = resp.json()
        assert "Error:" in body["choices"][0]["message"]["content"]

    def test_no_user_message_returns_400(self, no_auth_client):
        resp = no_auth_client.post("/v1/chat/completions", json={
            "messages": [{"role": "system", "content": "system prompt"}],
            "stream": False,
        })
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Endpoint tests: POST /v1/chat/completions (streaming)
# ---------------------------------------------------------------------------


class TestChatCompletionsStream:

    @patch("backend.api.openai.ChatHandler")
    def test_stream_text_events(self, MockHandler, no_auth_client, mock_state):
        from backend.core.services.react_service import EventType, ChatEvent

        events = [
            ChatEvent(type=EventType.TEXT, content="chunk1"),
            ChatEvent(type=EventType.TEXT, content="chunk2"),
            ChatEvent(type=EventType.DONE),
        ]
        handler_instance = MockHandler.return_value
        handler_instance.process = MagicMock(return_value=_async_iter(events))

        resp = no_auth_client.post("/v1/chat/completions", json={
            "messages": [{"role": "user", "content": "Hi"}],
            "stream": True,
        })
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

        lines = resp.text.strip().split("\n")
        data_lines = [l for l in lines if l.startswith("data:")]

        # Should have at least text chunks + final [DONE]
        assert any("[DONE]" in l for l in data_lines)
        text_chunks = [l for l in data_lines if l != "data: [DONE]"]
        assert len(text_chunks) >= 2

    @patch("backend.api.openai.ChatHandler")
    def test_stream_thinking_events(self, MockHandler, no_auth_client, mock_state):
        from backend.core.services.react_service import EventType, ChatEvent

        events = [
            ChatEvent(type=EventType.THINKING_START),
            ChatEvent(type=EventType.THINKING, content="hmm let me think"),
            ChatEvent(type=EventType.THINKING_END),
            ChatEvent(type=EventType.TEXT, content="answer"),
            ChatEvent(type=EventType.DONE),
        ]
        handler_instance = MockHandler.return_value
        handler_instance.process = MagicMock(return_value=_async_iter(events))

        resp = no_auth_client.post("/v1/chat/completions", json={
            "messages": [{"role": "user", "content": "think"}],
            "stream": True,
        })
        assert resp.status_code == 200
        # Thinking should appear as a <details> block in the streamed data
        assert "reasoning" in resp.text or "Thinking" in resp.text

    @patch("backend.api.openai.ChatHandler")
    def test_stream_tool_events(self, MockHandler, no_auth_client, mock_state):
        from backend.core.services.react_service import EventType, ChatEvent

        events = [
            ChatEvent(type=EventType.TOOL_START, metadata={"tool_name": "search"}),
            ChatEvent(type=EventType.TOOL_END, metadata={"tool_name": "search", "success": True}),
            ChatEvent(type=EventType.TEXT, content="result"),
            ChatEvent(type=EventType.DONE),
        ]
        handler_instance = MockHandler.return_value
        handler_instance.process = MagicMock(return_value=_async_iter(events))

        resp = no_auth_client.post("/v1/chat/completions", json={
            "messages": [{"role": "user", "content": "search something"}],
            "stream": True,
        })
        assert resp.status_code == 200
        assert "tool_calls" in resp.text

    @patch("backend.api.openai.ChatHandler")
    def test_stream_error_event(self, MockHandler, no_auth_client, mock_state):
        from backend.core.services.react_service import EventType, ChatEvent

        events = [
            ChatEvent(type=EventType.ERROR, content="boom"),
        ]
        handler_instance = MockHandler.return_value
        handler_instance.process = MagicMock(return_value=_async_iter(events))

        resp = no_auth_client.post("/v1/chat/completions", json={
            "messages": [{"role": "user", "content": "oops"}],
            "stream": True,
        })
        assert resp.status_code == 200
        assert "Error: boom" in resp.text
        assert "[DONE]" in resp.text

    @patch("backend.api.openai.ChatHandler")
    def test_stream_exception_during_processing(self, MockHandler, no_auth_client, mock_state):
        """If the handler raises, the stream should emit an error chunk and [DONE]."""
        async def _explode(req):
            raise RuntimeError("kaboom")
            yield  # pragma: no cover -- makes this an async generator

        handler_instance = MockHandler.return_value
        handler_instance.process = MagicMock(return_value=_explode(None))

        resp = no_auth_client.post("/v1/chat/completions", json={
            "messages": [{"role": "user", "content": "explode"}],
            "stream": True,
        })
        assert resp.status_code == 200
        assert "kaboom" in resp.text
        assert "[DONE]" in resp.text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _async_iter(items):
    """Turn a list into an async generator."""
    for item in items:
        yield item
