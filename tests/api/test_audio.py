"""Tests for backend.api.audio -- Audio upload / TTS / STT endpoints."""

import io
import asyncio
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi import HTTPException

from backend.api.audio import SpeechRequest


# ---------------------------------------------------------------------------
# POST /v1/audio/speech
# ---------------------------------------------------------------------------


class TestCreateSpeech:

    def test_tts_disabled_returns_501(self, no_auth_client):
        """The endpoint currently returns 501 (TTS disabled)."""
        resp = no_auth_client.post("/v1/audio/speech", json={
            "input": "Hello world",
        })
        assert resp.status_code == 501
        body = resp.json()
        assert "disabled" in body["detail"].lower()

    def test_tts_disabled_with_options(self, no_auth_client):
        resp = no_auth_client.post("/v1/audio/speech", json={
            "model": "qwen3-tts",
            "input": "Some text",
            "voice": "axel",
            "response_format": "mp3",
        })
        assert resp.status_code == 501


# ---------------------------------------------------------------------------
# GET /v1/audio/voices
# ---------------------------------------------------------------------------


class TestListVoices:

    def test_returns_voices(self, no_auth_client):
        resp = no_auth_client.get("/v1/audio/voices")
        assert resp.status_code == 200
        body = resp.json()
        assert "voices" in body
        assert len(body["voices"]) >= 1
        assert body["voices"][0]["id"] == "axel"
        assert body["voices"][0]["gender"] == "male"


# ---------------------------------------------------------------------------
# POST /v1/audio/transcriptions
# ---------------------------------------------------------------------------


class TestCreateTranscription:

    @patch("backend.media.transcribe_audio", new_callable=AsyncMock)
    def test_json_format(self, mock_transcribe, no_auth_client):
        mock_transcribe.return_value = "Hello world"

        audio_data = io.BytesIO(b"\x00" * 100)
        audio_data.name = "test.webm"

        resp = no_auth_client.post(
            "/v1/audio/transcriptions",
            files={"file": ("test.webm", audio_data, "audio/webm")},
            data={"model": "nova-3", "response_format": "json"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["text"] == "Hello world"

    @patch("backend.media.transcribe_audio", new_callable=AsyncMock)
    def test_text_format(self, mock_transcribe, no_auth_client):
        mock_transcribe.return_value = "Plain text result"

        audio_data = io.BytesIO(b"\x00" * 100)
        resp = no_auth_client.post(
            "/v1/audio/transcriptions",
            files={"file": ("test.webm", audio_data, "audio/webm")},
            data={"response_format": "text"},
        )
        assert resp.status_code == 200
        assert resp.text == "Plain text result"

    @patch("backend.media.transcribe_audio", new_callable=AsyncMock)
    def test_verbose_json_format(self, mock_transcribe, no_auth_client):
        mock_transcribe.return_value = "verbose result"

        audio_data = io.BytesIO(b"\x00" * 100)
        resp = no_auth_client.post(
            "/v1/audio/transcriptions",
            files={"file": ("test.webm", audio_data, "audio/webm")},
            data={"response_format": "verbose_json"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["text"] == "verbose result"
        assert "language" in body

    @patch("backend.media.transcribe_audio", new_callable=AsyncMock)
    def test_transcription_failed(self, mock_transcribe, no_auth_client):
        mock_transcribe.return_value = None

        audio_data = io.BytesIO(b"\x00" * 100)
        resp = no_auth_client.post(
            "/v1/audio/transcriptions",
            files={"file": ("test.webm", audio_data, "audio/webm")},
        )
        assert resp.status_code == 500

    @patch("backend.media.transcribe_audio", new_callable=AsyncMock)
    def test_transcription_exception(self, mock_transcribe, no_auth_client):
        mock_transcribe.side_effect = RuntimeError("STT backend down")

        audio_data = io.BytesIO(b"\x00" * 100)
        resp = no_auth_client.post(
            "/v1/audio/transcriptions",
            files={"file": ("test.webm", audio_data, "audio/webm")},
        )
        assert resp.status_code == 500
        body = resp.json()
        assert "STT error" in body["detail"]

    def test_missing_file_returns_422(self, no_auth_client):
        resp = no_auth_client.post("/v1/audio/transcriptions")
        assert resp.status_code == 422

    @patch("backend.media.transcribe_audio", new_callable=AsyncMock)
    def test_with_language_param(self, mock_transcribe, no_auth_client):
        """language form field is now ignored (auto-detect only)."""
        mock_transcribe.return_value = "Korean text"

        audio_data = io.BytesIO(b"\x00" * 100)
        resp = no_auth_client.post(
            "/v1/audio/transcriptions",
            files={"file": ("test.webm", audio_data, "audio/webm")},
            data={"language": "ko"},
        )
        assert resp.status_code == 200
        mock_transcribe.assert_called_once()


# ---------------------------------------------------------------------------
# SpeechRequest model
# ---------------------------------------------------------------------------


class TestSpeechRequestModel:

    def test_defaults(self):
        req = SpeechRequest(input="hello")
        assert req.model == "qwen3-tts"
        assert req.voice == "axel"
        assert req.response_format == "mp3"
        assert req.message_id is None

    def test_custom_values(self):
        req = SpeechRequest(
            input="test",
            model="custom-tts",
            voice="nova",
            response_format="wav",
            message_id="msg-123",
        )
        assert req.model == "custom-tts"
        assert req.voice == "nova"
        assert req.response_format == "wav"
        assert req.message_id == "msg-123"


# ---------------------------------------------------------------------------
# _synthesize_in_process (unit test -- currently unreachable from endpoint)
# ---------------------------------------------------------------------------


class _QueueFullError(Exception):
    """Sentinel exception injected into backend.media.qwen_tts for tests."""
    pass


@pytest.fixture(autouse=False)
def _inject_queue_full_error():
    """Inject QueueFullError into the qwen_tts module so _synthesize_in_process can import it."""
    import backend.media.qwen_tts as qwen_mod
    qwen_mod.QueueFullError = _QueueFullError
    yield _QueueFullError
    if hasattr(qwen_mod, "QueueFullError"):
        del qwen_mod.QueueFullError


class TestSynthesizeInProcess:

    @patch("backend.api.audio._get_tts")
    @patch("backend.api.audio.convert_wav_to_mp3", new_callable=AsyncMock)
    @patch("backend.api.audio.clean_text_for_tts")
    async def test_success_mp3(self, mock_clean, mock_convert, mock_get_tts, _inject_queue_full_error):
        from backend.api.audio import _synthesize_in_process

        mock_clean.return_value = "cleaned text"
        mock_tts = MagicMock()
        mock_tts.synthesize = AsyncMock(return_value=(b"wav-bytes", 22050))
        mock_get_tts.return_value = mock_tts
        mock_convert.return_value = b"mp3-bytes"

        request = SpeechRequest(input="hello", response_format="mp3")
        raw_request = MagicMock()
        raw_request.is_disconnected = AsyncMock(return_value=False)

        response = await _synthesize_in_process(request, raw_request)
        assert response.body == b"mp3-bytes"
        assert response.media_type == "audio/mpeg"

    @patch("backend.api.audio._get_tts")
    @patch("backend.api.audio.clean_text_for_tts")
    async def test_success_wav(self, mock_clean, mock_get_tts, _inject_queue_full_error):
        from backend.api.audio import _synthesize_in_process

        mock_clean.return_value = "cleaned text"
        mock_tts = MagicMock()
        mock_tts.synthesize = AsyncMock(return_value=(b"wav-bytes", 22050))
        mock_get_tts.return_value = mock_tts

        request = SpeechRequest(input="hello", response_format="wav")
        raw_request = MagicMock()
        raw_request.is_disconnected = AsyncMock(return_value=False)

        response = await _synthesize_in_process(request, raw_request)
        assert response.body == b"wav-bytes"
        assert response.media_type == "audio/wav"

    @patch("backend.api.audio._get_tts")
    @patch("backend.api.audio.clean_text_for_tts")
    async def test_client_disconnected_before_synthesis(self, mock_clean, mock_get_tts, _inject_queue_full_error):
        from backend.api.audio import _synthesize_in_process

        request = SpeechRequest(input="hello")
        raw_request = MagicMock()
        raw_request.is_disconnected = AsyncMock(return_value=True)

        with pytest.raises(HTTPException) as exc_info:
            await _synthesize_in_process(request, raw_request)
        assert exc_info.value.status_code == 499

    @patch("backend.api.audio._get_tts")
    @patch("backend.api.audio.clean_text_for_tts")
    async def test_synthesis_returns_empty(self, mock_clean, mock_get_tts, _inject_queue_full_error):
        from backend.api.audio import _synthesize_in_process

        mock_clean.return_value = "cleaned"
        mock_tts = MagicMock()
        mock_tts.synthesize = AsyncMock(return_value=(None, None))
        mock_get_tts.return_value = mock_tts

        request = SpeechRequest(input="hello")
        raw_request = MagicMock()
        raw_request.is_disconnected = AsyncMock(return_value=False)

        with pytest.raises(HTTPException) as exc_info:
            await _synthesize_in_process(request, raw_request)
        assert exc_info.value.status_code == 500

    @patch("backend.api.audio._get_tts")
    @patch("backend.api.audio.convert_wav_to_mp3", new_callable=AsyncMock)
    @patch("backend.api.audio.clean_text_for_tts")
    async def test_client_disconnected_after_synthesis(
        self, mock_clean, mock_convert, mock_get_tts, _inject_queue_full_error
    ):
        from backend.api.audio import _synthesize_in_process

        mock_clean.return_value = "cleaned"
        mock_tts = MagicMock()
        mock_tts.synthesize = AsyncMock(return_value=(b"wav", 22050))
        mock_get_tts.return_value = mock_tts

        request = SpeechRequest(input="hello", response_format="mp3")
        raw_request = MagicMock()
        # Not disconnected on first call, disconnected on second
        raw_request.is_disconnected = AsyncMock(side_effect=[False, True])

        with pytest.raises(HTTPException) as exc_info:
            await _synthesize_in_process(request, raw_request)
        assert exc_info.value.status_code == 499

    @patch("backend.api.audio._get_tts")
    @patch("backend.api.audio.clean_text_for_tts")
    async def test_queue_full_error(self, mock_clean, mock_get_tts, _inject_queue_full_error):
        from backend.api.audio import _synthesize_in_process

        mock_clean.return_value = "cleaned"
        mock_tts = MagicMock()
        mock_tts.synthesize = AsyncMock(side_effect=_inject_queue_full_error("queue full"))
        mock_get_tts.return_value = mock_tts

        request = SpeechRequest(input="hello")
        raw_request = MagicMock()
        raw_request.is_disconnected = AsyncMock(return_value=False)

        with pytest.raises(HTTPException) as exc_info:
            await _synthesize_in_process(request, raw_request)
        assert exc_info.value.status_code == 429

    @patch("backend.api.audio._get_tts")
    @patch("backend.api.audio.clean_text_for_tts")
    async def test_timeout_error(self, mock_clean, mock_get_tts, _inject_queue_full_error):
        from backend.api.audio import _synthesize_in_process

        mock_clean.return_value = "cleaned"
        mock_tts = MagicMock()
        mock_tts.synthesize = AsyncMock(side_effect=asyncio.TimeoutError())
        mock_get_tts.return_value = mock_tts

        request = SpeechRequest(input="hello")
        raw_request = MagicMock()
        raw_request.is_disconnected = AsyncMock(return_value=False)

        with pytest.raises(HTTPException) as exc_info:
            await _synthesize_in_process(request, raw_request)
        assert exc_info.value.status_code == 504

    @patch("backend.api.audio._get_tts")
    @patch("backend.api.audio.clean_text_for_tts")
    async def test_generic_error(self, mock_clean, mock_get_tts, _inject_queue_full_error):
        from backend.api.audio import _synthesize_in_process

        mock_clean.return_value = "cleaned"
        mock_tts = MagicMock()
        mock_tts.synthesize = AsyncMock(side_effect=RuntimeError("unexpected"))
        mock_get_tts.return_value = mock_tts

        request = SpeechRequest(input="hello")
        raw_request = MagicMock()
        raw_request.is_disconnected = AsyncMock(return_value=False)

        with pytest.raises(HTTPException) as exc_info:
            await _synthesize_in_process(request, raw_request)
        assert exc_info.value.status_code == 500


# ---------------------------------------------------------------------------
# _proxy_to_tts_service (unit test)
# ---------------------------------------------------------------------------


class TestProxyToTTSService:

    @patch("backend.core.utils.http_pool.get_client", new_callable=AsyncMock)
    @patch("backend.config.TTS_SERVICE_URL", "http://tts:8080")
    @patch("backend.config.TTS_SYNTHESIS_TIMEOUT", 30.0)
    async def test_success(self, mock_get_client):
        from backend.api.audio import _proxy_to_tts_service

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"audio-bytes"
        mock_resp.headers = {"content-type": "audio/mpeg", "content-disposition": "attachment"}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_get_client.return_value = mock_client

        request = SpeechRequest(input="hello")
        raw_request = MagicMock()
        raw_request.is_disconnected = AsyncMock(return_value=False)

        response = await _proxy_to_tts_service(request, raw_request)
        assert response.body == b"audio-bytes"

    async def test_client_disconnected(self):
        from backend.api.audio import _proxy_to_tts_service

        request = SpeechRequest(input="hello")
        raw_request = MagicMock()
        raw_request.is_disconnected = AsyncMock(return_value=True)

        with pytest.raises(HTTPException) as exc_info:
            await _proxy_to_tts_service(request, raw_request)
        assert exc_info.value.status_code == 499

    @patch("backend.core.utils.http_pool.get_client", new_callable=AsyncMock)
    @patch("backend.config.TTS_SERVICE_URL", "http://tts:8080")
    @patch("backend.config.TTS_SYNTHESIS_TIMEOUT", 30.0)
    async def test_service_error(self, mock_get_client):
        from backend.api.audio import _proxy_to_tts_service

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal error"

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_get_client.return_value = mock_client

        request = SpeechRequest(input="hello")
        raw_request = MagicMock()
        raw_request.is_disconnected = AsyncMock(return_value=False)

        with pytest.raises(HTTPException) as exc_info:
            await _proxy_to_tts_service(request, raw_request)
        assert exc_info.value.status_code == 500

    @patch("backend.core.utils.http_pool.get_client", new_callable=AsyncMock)
    @patch("backend.config.TTS_SERVICE_URL", "http://tts:8080")
    @patch("backend.config.TTS_SYNTHESIS_TIMEOUT", 30.0)
    async def test_network_exception(self, mock_get_client):
        from backend.api.audio import _proxy_to_tts_service

        mock_get_client.side_effect = RuntimeError("connection refused")

        request = SpeechRequest(input="hello")
        raw_request = MagicMock()
        raw_request.is_disconnected = AsyncMock(return_value=False)

        with pytest.raises(HTTPException) as exc_info:
            await _proxy_to_tts_service(request, raw_request)
        assert exc_info.value.status_code == 502
