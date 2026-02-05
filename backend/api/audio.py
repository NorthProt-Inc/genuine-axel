from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Optional
import re
import subprocess
import tempfile
import os
from backend.core.logging import get_logger
from backend.config import MAX_AUDIO_BYTES
from backend.api.deps import require_api_key
from backend.api.utils import read_upload_file

_logger = get_logger("api.audio")


def clean_text_for_tts(text: str) -> str:
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'`(.+?)`', r'\1', text)
    text = re.sub(r'#{1,6}\s*', '', text)
    text = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', text)
    text = re.sub(r'```[\s\S]*?```', '', text)
    text = re.sub(r'[^\w\s가-힣ㄱ-ㅎㅏ-ㅣ,.!?;:\'\"()~\-]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def convert_wav_to_mp3(wav_bytes: bytes) -> bytes:
    """Convert WAV audio to MP3 using ffmpeg.

    Args:
        wav_bytes: Raw WAV audio data

    Returns:
        MP3 encoded audio bytes
    """
    wav_path = tempfile.mktemp(suffix=".wav")
    mp3_path = wav_path.replace(".wav", ".mp3")

    try:
        with open(wav_path, "wb") as f:
            f.write(wav_bytes)

        subprocess.run([
            "ffmpeg", "-y", "-i", wav_path,
            "-codec:a", "libmp3lame", "-qscale:a", "2",
            mp3_path
        ], check=True, capture_output=True)

        with open(mp3_path, "rb") as f:
            return f.read()
    finally:
        if os.path.exists(wav_path):
            os.unlink(wav_path)
        if os.path.exists(mp3_path):
            os.unlink(mp3_path)


router = APIRouter(tags=["Audio"], dependencies=[Depends(require_api_key)])


class SpeechRequest(BaseModel):
    model: str = "qwen3-tts"
    input: str
    voice: str = "axel"  # 무시됨, 호환성용
    response_format: Optional[str] = "mp3"  # Open WebUI 호환


@router.post("/v1/audio/speech", summary="Generate speech (Qwen3-TTS)")
async def create_speech(request: SpeechRequest):
    if not request.input or not request.input.strip():
        raise HTTPException(status_code=400, detail="Input text is required")

    _logger.info("TTS request", chars=len(request.input))

    try:
        cleaned_text = clean_text_for_tts(request.input)

        from backend.media.qwen_tts import Qwen3TTS
        tts = Qwen3TTS()
        audio_bytes, sr = await tts.synthesize(cleaned_text)

        if not audio_bytes:
            raise HTTPException(status_code=500, detail="TTS synthesis failed")

        # mp3 변환
        if request.response_format == "mp3":
            audio_bytes = convert_wav_to_mp3(audio_bytes)
            media_type = "audio/mpeg"
            filename = "speech.mp3"
        else:
            media_type = "audio/wav"
            filename = "speech.wav"

        return Response(
            content=audio_bytes,
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )

    except Exception as e:
        _logger.error("TTS error", error=str(e))
        raise HTTPException(status_code=500, detail=f"TTS error: {str(e)}")


@router.get("/v1/audio/voices")
async def list_voices():
    return {"voices": [{"id": "axel", "name": "Axel", "gender": "male"}]}


class TranscriptionResponse(BaseModel):
    text: str


@router.post("/v1/audio/transcriptions")
async def create_transcription(
    file: UploadFile = File(...),
    model: str = Form("nova-3"),
    language: str = Form(None),
    response_format: str = Form("json"),
):
    try:
        audio_data = await read_upload_file(file, MAX_AUDIO_BYTES)
        filename = file.filename or "audio.webm"

        _logger.info("STT request", model=model, filename=filename, size=len(audio_data))

        from backend.media import transcribe_audio
        result = await transcribe_audio(audio_data, language)

        if not result:
            raise HTTPException(status_code=500, detail="Transcription failed")

        _logger.info("STT complete", chars=len(result))

        if response_format == "text":
            return Response(content=result, media_type="text/plain")
        elif response_format == "verbose_json":
            return {"text": result, "language": "auto", "duration": None}
        else:
            return {"text": result}

    except HTTPException:
        raise
    except Exception as e:
        _logger.error("STT error", error=str(e))
        raise HTTPException(status_code=500, detail=f"STT error: {str(e)}")
