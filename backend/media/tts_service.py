"""Standalone TTS microservice.

Runs as an independent process to isolate PyTorch/CUDA memory from the
main backend. Includes queue limiting, synthesis timeout, and idle unload.

Usage:
    python -m backend.media.tts_service [host] [port]
    python -m backend.media.tts_service 127.0.0.1 8002
"""

import asyncio
import sys
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from backend.config import TTS_IDLE_TIMEOUT, TTS_SYNTHESIS_TIMEOUT
from backend.core.logging import get_logger
from backend.core.utils.lazy import Lazy
from backend.media.tts_utils import clean_text_for_tts, convert_wav_to_mp3

_logger = get_logger("media.tts_service")

_tts_manager = None


def _create_tts() -> "Qwen3TTS":
    """Create Qwen3TTS instance for the service process."""
    from backend.media.qwen_tts import Qwen3TTS

    return Qwen3TTS()


_lazy_tts: Lazy = Lazy(_create_tts)


def _get_tts() -> "Qwen3TTS":
    """Return the TTS singleton for this service process."""
    return _lazy_tts.get()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage TTS manager lifecycle."""
    from backend.media.tts_manager import TTSManager

    global _tts_manager
    _tts_manager = TTSManager(idle_timeout=TTS_IDLE_TIMEOUT)
    _logger.info("TTS service starting", idle_timeout=TTS_IDLE_TIMEOUT)

    yield

    _logger.info("TTS service shutting down")
    if _tts_manager:
        await asyncio.wait_for(_tts_manager.shutdown(), timeout=10.0)


app = FastAPI(title="axnmihn TTS Service", lifespan=lifespan)


class SpeechRequest(BaseModel):
    input: str
    voice: str = "axel"
    response_format: Optional[str] = "mp3"
    message_id: Optional[str] = None


@app.post("/v1/audio/speech")
async def synthesize_speech(request: SpeechRequest, raw_request: Request):
    """Synthesize speech with queue/timeout/disconnect protection."""
    from backend.media.qwen_tts import QueueFullError

    if not request.input or not request.input.strip():
        raise HTTPException(status_code=400, detail="Input text is required")

    try:
        if await raw_request.is_disconnected():
            raise HTTPException(status_code=499, detail="Client disconnected")

        cleaned_text = clean_text_for_tts(request.input)

        loop = asyncio.get_event_loop()
        tts = await loop.run_in_executor(None, _get_tts)
        audio_bytes, sr = await tts.synthesize(
            cleaned_text, message_id=request.message_id
        )

        if not audio_bytes:
            raise HTTPException(status_code=500, detail="TTS synthesis failed")

        if await raw_request.is_disconnected():
            raise HTTPException(status_code=499, detail="Client disconnected")

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
        _logger.warning("TTS synthesis timeout", timeout=TTS_SYNTHESIS_TIMEOUT)
        raise HTTPException(status_code=504, detail="TTS synthesis timed out")
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("TTS synthesis error", error=str(e))
        raise HTTPException(status_code=500, detail=f"TTS error: {str(e)}")


@app.get("/health")
async def health():
    """Health check for systemd watchdog."""
    return JSONResponse({"status": "ok"})


if __name__ == "__main__":
    host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8002

    _logger.info("TTS service launching", host=host, port=port)

    uvicorn.run(
        "backend.media.tts_service:app",
        host=host,
        port=port,
        log_level="warning",
        reload=False,
    )
