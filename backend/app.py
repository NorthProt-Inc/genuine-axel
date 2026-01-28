import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from typing import Optional
import asyncio
import os
from uuid import uuid4
from datetime import datetime
from backend.core.utils.gemini_wrapper import GenerativeModelWrapper
from backend.config import (
    HOST,
    PORT,
    get_cors_origins,
    APP_VERSION,
    PERSONA_PATH,
    ensure_data_directories,
)
from backend.core import IdentityManager
from backend.memory import MemoryManager
from backend.llm import get_llm_client, get_all_providers
from backend.llm.router import get_model
from backend.core.logging import get_logger, set_request_id, reset_request_id, get_request_id
_log = get_logger("app")
from backend.api import (
    init_state,
    get_state,
    status_router,
    chat_router,
    memory_router,
    mcp_router,
    media_router,
    openai_router,
    audio_router,
)

_shutdown_event: Optional[asyncio.Event] = None
_background_tasks: list = []

@asynccontextmanager
async def lifespan(app: FastAPI):

    global _shutdown_event, _background_tasks, gemini_model, memory_manager, long_term_memory
    _shutdown_event = asyncio.Event()
    _background_tasks = []
    state = get_state()
    state.background_tasks = _background_tasks
    state.shutdown_event = _shutdown_event

    app.state.shutting_down = False

    try:
        model_config = get_model()
        model_name = model_config.model
        gemini_model = GenerativeModelWrapper(client_or_model=model_name)
        memory_manager = MemoryManager(model=gemini_model)
        long_term_memory = memory_manager.long_term
    except Exception as e:
        _log.warning("APP MemoryManager init failed", error=str(e))
        memory_manager = None
        long_term_memory = None

    from pathlib import Path
    from backend.core.utils.file_utils import startup_cleanup
    data_dirs = [Path("data")]
    await startup_cleanup(data_dirs)

    working_restored = False
    restored_turns = 0
    if memory_manager and memory_manager.working.load_from_disk():
        working_restored = True
        restored_turns = memory_manager.working.get_turn_count()
        _log.info(
            "APP working memory restored",
            turns=restored_turns,
            session_id=memory_manager.working.session_id[:8]
        )

    state.memory_manager = memory_manager
    state.long_term_memory = long_term_memory
    state.gemini_model = gemini_model

    available_llms = [p['name'] for p in get_all_providers() if p['available']]
    env = os.getenv("ENV", "dev")
    _log.info(
        "APP starting",
        version=APP_VERSION,
        env=env,
        pid=os.getpid(),
        llm=available_llms[0] if available_llms else "none",
        memory="on" if memory_manager else "off",
    )
    if memory_manager:
        _log.info(
            "APP memory status",
            working=f"{restored_turns if working_restored else 0}/{memory_manager.working.MAX_TURNS}",
            longterm=long_term_memory.get_stats().get('total_memories', 0) if long_term_memory else 0,
        )
    _log.info("APP ready", host=HOST, port=PORT)

    yield

    _log.info("APP shutdown", reason="lifespan_end")

    app.state.shutting_down = True
    _shutdown_event.set()

    active_streams = getattr(state, 'active_streams', [])
    if active_streams:
        _log.info("APP waiting for active streams", count=len(active_streams))
        await asyncio.sleep(min(10, len(active_streams) * 2))

    task_list = state.background_tasks if getattr(state, "background_tasks", None) is not None else _background_tasks
    for task in list(task_list):
        if not task.done():
            task.cancel()
            try:
                await asyncio.wait_for(task, timeout=3.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
    _log.info("APP background tasks cleaned", count=len(task_list))

    if memory_manager:

        if memory_manager.working.save_to_disk():
            _log.info("APP working memory persisted", turns=memory_manager.working.get_turn_count())

        try:
            await asyncio.wait_for(
                memory_manager.end_session(
                    allow_llm_summary=False,
                    allow_fallback_summary=True
                ),
                timeout=3.0
            )
        except Exception as e:
            _log.warning("APP session save failed", error=str(e))

    if long_term_memory:
        try:
            flushed = long_term_memory.flush_access_updates()
            if flushed > 0:
                _log.info("APP access updates flushed", count=flushed)
        except Exception as e:
            _log.warning("APP access update flush failed", error=str(e))

    try:
        from backend.core.utils.http_pool import close_all
        await asyncio.wait_for(close_all(), timeout=2.0)
    except Exception as e:
        _log.warning("APP HTTP pool close failed", error=str(e))

    _log.info("APP shutdown complete")

app = FastAPI(title="axnmihn API", version=APP_VERSION, lifespan=lifespan)

@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    req_id = (
        request.headers.get("X-Request-ID")
        or request.headers.get("X-Request-Id")
        or uuid4().hex[:12]
    )
    request.state.request_id = req_id
    token = set_request_id(req_id)
    try:
        response = await call_next(request)
    finally:
        reset_request_id(token)
    response.headers["X-Request-ID"] = req_id
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
_log.debug("APP middleware setup", middlewares=["request_id", "cors"])

app.include_router(status_router)
app.include_router(chat_router)
app.include_router(memory_router)
app.include_router(mcp_router)
app.include_router(media_router)
app.include_router(openai_router)
app.include_router(audio_router)
_log.debug(
    "APP routers mounted",
    routers=["status", "chat", "memory", "mcp", "media", "openai", "audio"]
)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):

    import traceback
    req_id = getattr(request.state, "request_id", None) or get_request_id()

    tb = traceback.format_exc()
    _log.error(
        "APP unhandled exception",
        path=str(request.url.path),
        error_type=type(exc).__name__,
        error=str(exc),
        traceback=tb,
        request_id=req_id
    )

    headers = {"X-Request-ID": req_id} if req_id else None
    return JSONResponse(
        status_code=500,
        headers=headers,
        content={
            "error": "Internal Server Error",
            "message": str(exc) if str(exc) else "Unknown error",
            "type": type(exc).__name__,
            "path": str(request.url.path),
            "request_id": req_id,
        }
    )

ensure_data_directories()

identity_manager = IdentityManager(persona_path=str(PERSONA_PATH))

gemini_model = None
memory_manager = None
long_term_memory = None

_log.debug(
    "APP module loaded",
    version=APP_VERSION,
    available_llms=[p['name'] for p in get_all_providers() if p['available']]
)

init_state(
    memory_manager=memory_manager,
    long_term_memory=long_term_memory,
    identity_manager=identity_manager,
    gemini_model=gemini_model,
)
app.state.axnmihn_state = get_state()

if __name__ == "__main__":
    import logging

    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    uvicorn.run(
        "backend.app:app",
        host=HOST,
        port=PORT,
        log_level="warning",
        reload=False,
    )
