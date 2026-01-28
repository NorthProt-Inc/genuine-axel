import os
import time

import httpx

from backend.core.logging import get_logger

_log = get_logger("media.transcribe")

DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "")

async def transcribe_audio_deepgram(audio_data: bytes, language: str = None) -> str:

    if not DEEPGRAM_API_KEY:
        _log.error("stt failed", reason="DEEPGRAM_API_KEY not set")
        raise ValueError("DEEPGRAM_API_KEY not set")

    size_kb = len(audio_data) / 1024
    _log.info("stt start", file_size_kb=round(size_kb, 2), format="webm", provider="deepgram")

    url = "https://api.deepgram.com/v1/listen"
    params = {
        "model": "nova-3",
        "smart_format": "true",
    }

    params["detect_language"] = "true"

    headers = {
        "Authorization": f"Token {DEEPGRAM_API_KEY}",
        "Content-Type": "audio/webm",
    }

    start_time = time.perf_counter()
    _log.debug("stt api call", provider="deepgram", model="nova-3")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, params=params, headers=headers, content=audio_data)
            response.raise_for_status()
            result = response.json()
    except httpx.HTTPStatusError as e:
        dur_ms = int((time.perf_counter() - start_time) * 1000)
        _log.error("stt api error", provider="deepgram", status=e.response.status_code, dur_ms=dur_ms)
        raise
    except httpx.TimeoutException:
        dur_ms = int((time.perf_counter() - start_time) * 1000)
        _log.error("stt timeout", provider="deepgram", dur_ms=dur_ms)
        raise
    except Exception as e:
        dur_ms = int((time.perf_counter() - start_time) * 1000)
        _log.error("stt failed", provider="deepgram", error=str(e), dur_ms=dur_ms)
        raise

    dur_ms = int((time.perf_counter() - start_time) * 1000)

    channels = result.get("results", {}).get("channels", [])
    if channels:
        alternatives = channels[0].get("alternatives", [])
        if alternatives:
            transcript = alternatives[0].get("transcript", "")
            _log.info("stt done", dur_ms=dur_ms, text_len=len(transcript))
            return transcript

    _log.info("stt done", dur_ms=dur_ms, text_len=0)
    return ""

async def transcribe_audio(audio_data: bytes, language: str = "ko") -> str:

    if not DEEPGRAM_API_KEY:
        _log.error("stt failed", reason="DEEPGRAM_API_KEY not set")
        raise ValueError("DEEPGRAM_API_KEY not set")

    return await transcribe_audio_deepgram(audio_data, language)

async def transcribe_audio_file(file_path: str, language: str = "ko") -> str:

    file_ext = os.path.splitext(file_path)[1].lstrip(".") or "unknown"

    try:
        with open(file_path, "rb") as f:
            audio_data = f.read()
    except FileNotFoundError:
        _log.error("stt file not found", file_path=file_path)
        raise
    except Exception as e:
        _log.error("stt file read error", file_path=file_path, error=str(e))
        raise

    size_kb = len(audio_data) / 1024
    _log.info("stt file loaded", file_path=file_path, file_size_kb=round(size_kb, 2), format=file_ext)

    return await transcribe_audio(audio_data, language)
