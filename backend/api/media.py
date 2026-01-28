import os
import base64
import re
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from pydantic import BaseModel
import aiofiles
from backend.core.logging import get_logger
from backend.media import transcribe_audio
from backend.config import (
    ALLOWED_TEXT_EXTENSIONS,
    ALLOWED_IMAGE_EXTENSIONS,
    MAX_UPLOAD_BYTES,
    MAX_AUDIO_BYTES,
)
from backend.api.deps import require_api_key
from backend.api.utils import read_upload_file

_logger = get_logger("api.media")

router = APIRouter(tags=["Media"], dependencies=[Depends(require_api_key)])

ALLOWED_UPLOAD_EXTENSIONS = set(ALLOWED_TEXT_EXTENSIONS + ALLOWED_IMAGE_EXTENSIONS + [".pdf"])

def _sanitize_filename(filename: str) -> str:
    if not filename:
        return "upload.bin"
    safe_name = Path(filename).name
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", safe_name).strip("._")
    return safe_name[:200] or "upload.bin"

@router.post("/transcribe")
async def transcribe_audio_endpoint(
    audio: UploadFile = File(...),
    language: str = Form(None)
):

    _logger.info("REQ recv", path="/transcribe", filename=audio.filename, language=language)
    content = await read_upload_file(audio, MAX_AUDIO_BYTES)
    filename = audio.filename or "audio.webm"

    from backend.media import transcribe_audio as do_transcribe
    result = await do_transcribe(content, language)

    if result:
        _logger.info("RES sent", status=200, text_len=len(result))
        return {"text": result, "success": True}
    else:
        _logger.error("Transcription failed", filename=audio.filename)
        return {"text": "", "success": False, "error": "Transcription failed"}

@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):

    _logger.info("REQ recv", path="/upload", filename=file.filename, content_type=file.content_type)
    safe_name = _sanitize_filename(file.filename or "upload.bin")
    file_extension = Path(safe_name).suffix.lower()
    if file_extension not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported file type")

    content = await read_upload_file(file, MAX_UPLOAD_BYTES)
    new_filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_name}"
    file_path = f"/tmp/{new_filename}"

    async with aiofiles.open(file_path, "wb") as buffer:
        await buffer.write(content)

    result = {
        "filename": new_filename,
        "path": file_path,
        "size": len(content),
        "type": file.content_type,
    }

    if file_extension == ".pdf":
        result["data"] = base64.b64encode(content).decode()
        result["data_type"] = file.content_type
        _logger.info("PDF uploaded", filename=file.filename, size_kb=len(content) // 1024)

    elif file_extension in [".png", ".jpg", ".jpeg", ".gif", ".webp"]:
        result["data"] = base64.b64encode(content).decode()
        result["data_type"] = file.content_type

    elif file_extension in [".txt", ".md", ".json", ".py", ".js", ".ts", ".html", ".css"]:
        result["content"] = content.decode("utf-8", errors="ignore")

    try:
        os.remove(file_path)
        _logger.debug("Uploaded file deleted", path=file_path)
    except Exception as e:
        _logger.warning("Failed to delete uploaded file", path=file_path, error=str(e))

    _logger.info("RES sent", status=200, filename=new_filename, size=len(content))
    return result
