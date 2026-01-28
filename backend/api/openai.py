import time
import uuid
import json
import base64
from typing import List, Any
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from backend.core.logging import get_logger
from backend.core.chat_handler import ChatHandler, ChatRequest as HandlerRequest, EventType
from backend.api.deps import get_state
from backend.api.deps import require_api_key
from backend.config import MAX_ATTACHMENT_BYTES

_logger = get_logger("api.openai")

router = APIRouter(tags=["OpenAI Compatible"], dependencies=[Depends(require_api_key)])

class OpenAIMessage(BaseModel):
    role: str
    content: Any

    class Config:
        extra = "allow"

class OpenAIChatRequest(BaseModel):
    model: str = "axnmihn"
    messages: List[OpenAIMessage]
    temperature: float = 0.7
    max_tokens: int = 16384
    stream: bool = False

    class Config:
        extra = "allow"

MODEL_TIER_MAP = {
    "axel-auto": "axel",
    "axel-mini": "axel",
    "axel": "axel",
    "axel-pro": "axel",
}

@router.get("/v1/models")
async def openai_list_models():

    return {
        "object": "list",
        "data": [
            {
                "id": "axel",
                "object": "model",
                "created": 1703462400,
                "owned_by": "axnmihn",
                "permission": [],
                "root": "axel",
                "parent": None,
            },
        ]
    }

@router.post("/v1/chat/completions")
async def openai_chat_completions(request_body: OpenAIChatRequest):

    user_messages = [m for m in request_body.messages if m.role == "user"]
    if not user_messages:
        raise HTTPException(status_code=400, detail="No user message found")

    user_input, multimodal_images = _parse_multimodal_content(user_messages[-1].content)

    selected_model = request_body.model.lower() if request_body.model else "axel-auto"
    tier = MODEL_TIER_MAP.get(selected_model, "auto")

    model_choice = "gemini"

    _logger.info(
        "OpenAI API req",
        model=selected_model,
        tier=tier,
        stream=request_body.stream,
        user_input=user_input[:50] if isinstance(user_input, str) else "[multimodal]"
    )

    handler_request = HandlerRequest(
        user_input=user_input,
        model_choice=model_choice,
        tier=tier,
        multimodal_images=multimodal_images,
        temperature=request_body.temperature,
        max_tokens=request_body.max_tokens,
    )

    handler = ChatHandler(get_state())

    if request_body.stream:
        return StreamingResponse(
            _stream_openai_response(handler, handler_request),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no"}
        )
    else:
        return await _non_stream_openai_response(handler, handler_request)

def _b64_length_to_bytes(length: int) -> int:
    return (length * 3) // 4

def _is_b64_too_large(b64_data: str, max_bytes: int) -> bool:
    return _b64_length_to_bytes(len(b64_data)) > max_bytes

def _parse_multimodal_content(content: Any) -> tuple[str, list]:

    if isinstance(content, str):
        return content, []

    if not isinstance(content, list):
        return str(content), []

    text_parts = []
    multimodal_images = []

    for part in content:
        if not isinstance(part, dict):
            continue

        part_type = part.get("type", "")

        if part_type == "text":
            text_parts.append(part.get("text", ""))

        elif part_type == "image_url":
            image_url_obj = part.get("image_url", {})
            url = image_url_obj.get("url", "") if isinstance(image_url_obj, dict) else str(image_url_obj)
            if url.startswith("data:"):
                if ";base64," in url:
                    mime_type = url.split(";base64,")[0].replace("data:", "")
                    b64_data = url.split(";base64,")[1]
                    if _is_b64_too_large(b64_data, MAX_ATTACHMENT_BYTES):
                        _logger.warning("Image skip (size limit)", mime=mime_type)
                        text_parts.append("[Image skipped: size limit]")
                        continue
                    multimodal_images.append({"mime_type": mime_type, "data": b64_data})
                    _logger.debug("Image parsed from data URL", mime=mime_type)
            text_parts.append("[Image attached]")

        elif part_type in ["file_url", "document", "file", "file_citation"]:
            file_obj = part.get("file", {})
            extracted_content, images = _parse_file_attachment(file_obj, part)
            if extracted_content:
                text_parts.append(extracted_content)
            multimodal_images.extend(images)

    user_input = " ".join(text_parts) if text_parts else "[Attachment]"
    return user_input, multimodal_images

def _parse_file_attachment(file_obj: dict, part: dict) -> tuple[str, list]:

    extracted_content = ""
    images = []

    if part.get("content"):
        return part.get("content"), []
    if isinstance(file_obj, dict) and file_obj.get("content"):
        return file_obj.get("content"), []
    if isinstance(file_obj, dict) and file_obj.get("text"):
        return file_obj.get("text"), []
    if part.get("text"):
        return part.get("text"), []

    if isinstance(file_obj, dict) and file_obj.get("file_data"):
        file_data = file_obj.get("file_data", "")
        filename = file_obj.get("filename", "unknown").lower()

        if ";base64," in file_data:
            mime_type = file_data.split(";base64,")[0].replace("data:", "")
            b64_data = file_data.split(";base64,")[1]
        else:
            mime_type = "application/octet-stream"
            b64_data = file_data

        if _is_b64_too_large(b64_data, MAX_ATTACHMENT_BYTES):
            _logger.warning("Attach skip (size limit)", filename=filename)
            extracted_content = f"\n\n[Attached File: {filename} skipped - size limit]"
            return extracted_content, []

        if "pdf" in mime_type or filename.endswith(".pdf"):
            try:
                from backend.core.utils.pdf import convert_pdf_to_images
                pdf_bytes = base64.b64decode(b64_data)
                pdf_images = convert_pdf_to_images(pdf_bytes)
                if pdf_images:
                    images.extend(pdf_images)
                    extracted_content = f"\n\n[Attached PDF: {filename} - {len(pdf_images)} pages as images]"
                    _logger.info("PDF converted to images", filename=filename, pages=len(pdf_images))
            except Exception as e:
                _logger.warning("PDF conversion failed", filename=filename, err=str(e))

        elif any(ext in mime_type or filename.endswith(ext) for ext in
                 ["image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp",
                  ".png", ".jpg", ".jpeg", ".gif", ".webp"]):
            images.append({
                "mime_type": mime_type if "/" in mime_type else f"image/{filename.split('.')[-1]}",
                "data": b64_data,
                "filename": filename
            })
            _logger.debug("Image stored for Vision", filename=filename)

        elif any(ext in mime_type or filename.endswith(ext) for ext in
                 ["text/", ".txt", ".md", ".json", ".csv", ".xml", ".yaml", ".yml",
                  ".py", ".js", ".ts", ".html", ".css", ".sh", ".log"]):
            try:
                text_bytes = base64.b64decode(b64_data)
                text_content = text_bytes.decode("utf-8", errors="replace")
                extracted_content = f"\n\n[Attached File: {filename}]\n{text_content}"
                _logger.info("Text file decoded", filename=filename, chars=len(text_content))
            except Exception as e:
                _logger.warning("Text decode failed", filename=filename, err=str(e))

    return extracted_content, images

async def _stream_openai_response(handler: ChatHandler, request: HandlerRequest):

    chat_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
    created = int(time.time())
    stream_id = uuid.uuid4().hex[:8]

    state = get_state()
    state.active_streams.append(stream_id)
    _logger.debug("stream started", stream_id=stream_id, active_count=len(state.active_streams))

    try:
        async for event in handler.process(request):
            if event.type == EventType.TEXT:
                data = {
                    "id": chat_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": "axnmihn",
                    "choices": [{"index": 0, "delta": {"content": event.content}, "finish_reason": None}]
                }
                yield f"data: {json.dumps(data)}\n\n"

            elif event.type == EventType.THINKING:

                thinking_content = f"*{event.content}*"
                data = {
                    "id": chat_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": "axnmihn",
                    "choices": [{"index": 0, "delta": {"content": thinking_content}, "finish_reason": None}]
                }
                yield f"data: {json.dumps(data)}\n\n"

            elif event.type == EventType.THINKING_START:

                thinking_start_content = "\n\n*Thinking...*\n\n"
                data = {
                    "id": chat_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": "axnmihn",
                    "choices": [{"index": 0, "delta": {"content": thinking_start_content}, "finish_reason": None}]
                }
                yield f"data: {json.dumps(data)}\n\n"

            elif event.type == EventType.THINKING_END:

                pass

            elif event.type == EventType.TOOL_START:

                tool_name = event.metadata.get("tool_name", "unknown")
                tool_start_content = f"\n\n*Tool: {tool_name}*\n\n"
                data = {
                    "id": chat_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": "axnmihn",
                    "choices": [{"index": 0, "delta": {"content": tool_start_content}, "finish_reason": None}]
                }
                yield f"data: {json.dumps(data)}\n\n"

            elif event.type == EventType.TOOL_END:

                tool_end_content = "\n\n*Done*\n\n"
                data = {
                    "id": chat_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": "axnmihn",
                    "choices": [{"index": 0, "delta": {"content": tool_end_content}, "finish_reason": None}]
                }
                yield f"data: {json.dumps(data)}\n\n"

            elif event.type == EventType.DONE:

                final_data = {
                    "id": chat_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": "axnmihn",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]
                }
                yield f"data: {json.dumps(final_data)}\n\n"
                yield "data: [DONE]\n\n"

            elif event.type == EventType.ERROR:
                error_data = {
                    "id": chat_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": "axnmihn",
                    "choices": [{"index": 0, "delta": {"content": f"Error: {event.content}"}, "finish_reason": "stop"}]
                }
                yield f"data: {json.dumps(error_data)}\n\n"
                yield "data: [DONE]\n\n"

    except Exception as e:

        _logger.error("stream error", stream_id=stream_id, error=str(e)[:200])
        error_data = {
            "id": chat_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": "axnmihn",
            "choices": [{"index": 0, "delta": {"content": f"Stream error: {str(e)[:100]}"}, "finish_reason": "stop"}]
        }
        yield f"data: {json.dumps(error_data)}\n\n"
        yield "data: [DONE]\n\n"

    finally:

        if stream_id in state.active_streams:
            state.active_streams.remove(stream_id)
        _logger.debug("stream ended", stream_id=stream_id, active_count=len(state.active_streams))

async def _non_stream_openai_response(handler: ChatHandler, request: HandlerRequest) -> dict:

    full_response = ""

    async for event in handler.process(request):
        if event.type == EventType.TEXT:
            full_response += event.content
        elif event.type == EventType.ERROR:
            full_response = f"Error: {event.content}"

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "axnmihn",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": full_response
                },
                "finish_reason": "stop"
            }
        ],
        "usage": {
            "prompt_tokens": len(request.user_input) // 4,
            "completion_tokens": len(full_response) // 4,
            "total_tokens": (len(request.user_input) + len(full_response)) // 4
        }
    }
