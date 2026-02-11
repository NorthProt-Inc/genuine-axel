import base64
import re
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from backend.core.logging import get_logger
from backend.config import (
    ALLOWED_TEXT_EXTENSIONS,
    ALLOWED_IMAGE_EXTENSIONS,
    MAX_UPLOAD_BYTES,
    MAX_AUDIO_BYTES,
)
from backend.api.deps import require_api_key
from backend.api.utils import read_upload_file

_log = get_logger("api.media")

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
):
    _log.info("REQ recv", path="/transcribe", filename=audio.filename)
    content = await read_upload_file(audio, MAX_AUDIO_BYTES)

    from backend.media import transcribe_audio as do_transcribe
    result = await do_transcribe(content)

    if result:
        _log.info("RES sent", status=200, text_len=len(result))
        return {"text": result, "success": True}
    else:
        _log.error("Transcription failed", filename=audio.filename)
        return {"text": "", "success": False, "error": "Transcription failed"}

@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    _log.info("REQ recv", path="/upload", filename=file.filename, content_type=file.content_type)
    safe_name = _sanitize_filename(file.filename or "upload.bin")
    file_extension = Path(safe_name).suffix.lower()
    if file_extension not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported file type")

    content = await read_upload_file(file, MAX_UPLOAD_BYTES)

    result = {
        "filename": safe_name,
        "size": len(content),
        "type": file.content_type,
    }

    if file_extension == ".pdf":
        result["data"] = base64.b64encode(content).decode()
        result["data_type"] = file.content_type
        _log.info("PDF uploaded", filename=file.filename, size_kb=len(content) // 1024)

    elif file_extension in [".png", ".jpg", ".jpeg", ".gif", ".webp"]:
        result["data"] = base64.b64encode(content).decode()
        result["data_type"] = file.content_type

    elif file_extension in [".txt", ".md", ".json", ".py", ".js", ".ts", ".html", ".css"]:
        result["content"] = content.decode("utf-8", errors="ignore")

    _log.info("RES sent", status=200, filename=safe_name, size=len(content))
    return result
