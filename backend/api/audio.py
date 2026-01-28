from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Optional, Literal
import base64
import re
import uuid
import time
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

router = APIRouter(tags=["Audio"], dependencies=[Depends(require_api_key)])

OPENAI_VOICES = ["alloy", "ash", "ballad", "cedar", "coral", "echo", "fable", "marin", "nova", "onyx", "sage", "shimmer", "verse"]
LOCAL_VOICES = ["axel-voice", "axel"]
ALL_VOICES = OPENAI_VOICES + LOCAL_VOICES
DEFAULT_VOICE = "axel"

class SpeechRequest(BaseModel):

    model: str = "northprot-tts"
    input: str
    voice: str = DEFAULT_VOICE
    instructions: Optional[str] = None
    speed: float = 1.0
    response_format: Optional[str] = "mp3"

@router.post("/v1/audio/speech", summary="Generate speech from text (NorthProt-TTS)")
async def create_speech(request: SpeechRequest):

    start_time = time.time()
    request_id = str(uuid.uuid4())

    if not request.input or not request.input.strip():
        raise HTTPException(status_code=400, detail="Input text is required")

    voice = request.voice.lower()

    _logger.info(
        f"TTS request (NorthProt-TTS Active)",
        voice=voice,
        model=request.model,
        chars=len(request.input)
    )

    try:

        output_format = request.response_format or "mp3"
        content_type_map = {
            "mp3": "audio/mpeg",
            "opus": "audio/opus",
            "aac": "audio/aac",
            "flac": "audio/flac",
            "wav": "audio/wav",
            "pcm": "audio/pcm"
        }
        content_type = content_type_map.get(output_format, "audio/mpeg")

        cleaned_text = clean_text_for_tts(request.input)

        from media.rvc_tts import RVCTTS
        tts = RVCTTS(
            voice="axel",
            speed=request.speed or 1.0
        )
        audio_b64, _ = await tts.synthesize(
            text=cleaned_text,
            output_format=output_format
        )

        if not audio_b64:
            raise HTTPException(status_code=500, detail="TTS synthesis failed")

        audio_bytes = base64.b64decode(audio_b64)

        return Response(
            content=audio_bytes,
            media_type=content_type,
            headers={
                "Content-Disposition": f"attachment; filename=speech.{output_format}"
            }
        )

    except Exception as e:
        _logger.error("TTS error", error=str(e))
        raise HTTPException(status_code=500, detail=f"TTS error: {str(e)}")

VOICE_MAP = {v: v.title() for v in ALL_VOICES}

@router.get("/v1/audio/voices")
async def list_voices():

    return {
        "voices": [
            {
                "id": k,
                "name": v,
                "gender": "male" if k in ["alloy", "echo", "fable", "onyx", "imp", "axel", "axel-voice"] else "female"
            }
            for k, v in VOICE_MAP.items()
        ]
    }

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

        _logger.info(
            "STT request",
            model=model,
            filename=filename,
            size=len(audio_data),
            language=language
        )

        from media import transcribe_audio

        result = await transcribe_audio(audio_data, language)

        if not result:
            raise HTTPException(status_code=500, detail="Transcription failed")

        _logger.info("STT complete", chars=len(result))

        if response_format == "text":
            return Response(content=result, media_type="text/plain")
        elif response_format == "verbose_json":
            return {
                "text": result,
                "language": "auto",
                "duration": None,
            }
        else:
            return {"text": result}

    except HTTPException:
        raise
    except Exception as e:
        _logger.error("STT error", error=str(e))
        raise HTTPException(status_code=500, detail=f"STT error: {str(e)}")
