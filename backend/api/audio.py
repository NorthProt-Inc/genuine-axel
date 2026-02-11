from fastapi import APIRouter, HTTPException, Depends, Request, UploadFile, File, Form
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Optional
import asyncio
from backend.core.logging import get_logger
from backend.config import MAX_AUDIO_BYTES
from backend.api.deps import require_api_key
from backend.api.utils import read_upload_file
from backend.media.tts_utils import clean_text_for_tts, convert_wav_to_mp3

_log = get_logger("api.audio")


from backend.core.utils.lazy import Lazy


def _create_tts() -> "Qwen3TTS":
    """Create Qwen3TTS instance."""
    from backend.media.qwen_tts import Qwen3TTS

    return Qwen3TTS()


_lazy_tts: Lazy = Lazy(_create_tts)


def _get_tts() -> "Qwen3TTS":
    """Return a module-level Qwen3TTS singleton (thread-safe lazy init)."""
    return _lazy_tts.get()


router = APIRouter(tags=["Audio"], dependencies=[Depends(require_api_key)])


class SpeechRequest(BaseModel):
    model: str = "qwen3-tts"
    input: str
    voice: str = "axel"  # 무시됨, 호환성용
    response_format: Optional[str] = "mp3"  # Open WebUI 호환
    message_id: Optional[str] = None  # ICL chain용 — 동일 message 내 문장 간 톤 일관성


@router.post("/v1/audio/speech", summary="Generate speech (Qwen3-TTS)")
async def create_speech(request: SpeechRequest, raw_request: Request):
    # TTS disabled — use OpenAI TTS directly from Open WebUI
    raise HTTPException(status_code=501, detail="TTS disabled on backend")


async def _synthesize_in_process(request: SpeechRequest, raw_request: Request) -> Response:
    """Synthesize TTS in-process with queue/timeout/disconnect protection."""
    from backend.media.qwen_tts import QueueFullError

    try:
        # Check if client already disconnected
        if await raw_request.is_disconnected():
            _log.info("TTS client disconnected before synthesis")
            raise HTTPException(status_code=499, detail="Client disconnected")

        cleaned_text = clean_text_for_tts(request.input)

        loop = asyncio.get_event_loop()
        tts = await loop.run_in_executor(None, _get_tts)
        audio_bytes, sr = await tts.synthesize(cleaned_text, message_id=request.message_id)

        if not audio_bytes:
            raise HTTPException(status_code=500, detail="TTS synthesis failed")

        # Check disconnect again before expensive mp3 conversion
        if await raw_request.is_disconnected():
            _log.info("TTS client disconnected after synthesis")
            raise HTTPException(status_code=499, detail="Client disconnected")

        # mp3 변환
        if request.response_format == "mp3":
            audio_bytes = await convert_wav_to_mp3(audio_bytes)
            media_type = "audio/mpeg"
            filename = "speech.mp3"
        else:
            media_type = "audio/wav"
            filename = "speech.wav"

        return Response(
            content=audio_bytes,
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    except QueueFullError:
        raise HTTPException(status_code=429, detail="TTS queue full, try again later")
    except asyncio.TimeoutError:
        _log.warning("TTS synthesis timeout")
        raise HTTPException(status_code=504, detail="TTS synthesis timed out")
    except HTTPException:
        raise
    except Exception as e:
        _log.error("TTS error", error=str(e))
        raise HTTPException(status_code=500, detail=f"TTS error: {str(e)}")


async def _proxy_to_tts_service(request: SpeechRequest, raw_request: Request) -> Response:
    """Forward TTS request to the external TTS microservice."""
    from backend.config import TTS_SERVICE_URL, TTS_SYNTHESIS_TIMEOUT
    from backend.core.utils.http_pool import get_client

    try:
        if await raw_request.is_disconnected():
            raise HTTPException(status_code=499, detail="Client disconnected")

        client = await get_client(
            "tts",
            base_url=TTS_SERVICE_URL,
            timeout=TTS_SYNTHESIS_TIMEOUT + 5.0,
        )

        resp = await client.post(
            "/v1/audio/speech",
            json={
                "input": request.input,
                "voice": request.voice,
                "response_format": request.response_format,
                "message_id": request.message_id,
            },
        )

        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)

        return Response(
            content=resp.content,
            media_type=resp.headers.get("content-type", "audio/mpeg"),
            headers={"Content-Disposition": resp.headers.get("content-disposition", "")},
        )

    except HTTPException:
        raise
    except Exception as e:
        _log.error("TTS proxy error", error=str(e))
        raise HTTPException(status_code=502, detail=f"TTS service error: {str(e)}")


@router.get("/v1/audio/voices")
async def list_voices():
    return {"voices": [{"id": "axel", "name": "Axel", "gender": "male"}]}


class TranscriptionResponse(BaseModel):
    text: str


@router.post("/v1/audio/transcriptions")
async def create_transcription(
    file: UploadFile = File(...),
    model: str = Form("nova-3"),
    response_format: str = Form("json"),
):
    try:
        audio_data = await read_upload_file(file, MAX_AUDIO_BYTES)
        filename = file.filename or "audio.webm"

        _log.info("STT request", model=model, filename=filename, size=len(audio_data))

        from backend.media import transcribe_audio
        result = await transcribe_audio(audio_data)

        if not result:
            raise HTTPException(status_code=500, detail="Transcription failed")

        _log.info("STT complete", chars=len(result))

        if response_format == "text":
            return Response(content=result, media_type="text/plain")
        elif response_format == "verbose_json":
            return {"text": result, "language": "auto", "duration": None}
        else:
            return {"text": result}

    except HTTPException:
        raise
    except Exception as e:
        _log.error("STT error", error=str(e))
        raise HTTPException(status_code=500, detail=f"STT error: {str(e)}")
