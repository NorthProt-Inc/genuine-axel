import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import asyncio
import os
from uuid import uuid4
from backend.core.utils.gemini_client import get_gemini_client
from backend.config import (
    HOST,
    PORT,
    SHUTDOWN_HTTP_POOL_TIMEOUT,
    SHUTDOWN_SESSION_TIMEOUT,
    SHUTDOWN_TASK_TIMEOUT,
    get_cors_origins,
    APP_VERSION,
    PERSONA_PATH,
    DEFAULT_GEMINI_MODEL,
    ensure_data_directories,
)
from backend.core import IdentityManager
from backend.memory import MemoryManager
from backend.llm import get_all_providers
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


@asynccontextmanager
async def lifespan(app: FastAPI):

    state = get_state()
    state.shutdown_event = asyncio.Event()
    state.background_tasks = []

    app.state.shutting_down = False

    mm = None
    ltm = None
    try:
        # Use Gemini for utility tasks (memory, graphrag, summarization)
        # Chat model is now Anthropic, handled separately by llm.router
        gem_client = get_gemini_client()
        mm = MemoryManager(client=gem_client, model_name=DEFAULT_GEMINI_MODEL)
        ltm = mm.long_term
        state.gemini_client = gem_client
    except Exception as e:
        _log.warning("APP MemoryManager init failed", error=str(e))

    from pathlib import Path
    from backend.core.utils.file_utils import startup_cleanup
    data_dirs = [Path("data")]
    await startup_cleanup(data_dirs)

    working_restored = False
    restored_turns = 0
    if mm:
        try:
            loaded = await asyncio.wait_for(
                asyncio.to_thread(mm.working.load_from_disk),
                timeout=10.0,
            )
            if loaded:
                working_restored = True
                restored_turns = mm.working.get_turn_count()
                _log.info(
                    "APP working memory restored",
                    turns=restored_turns,
                    session_id=mm.working.session_id[:8]
                )
        except asyncio.TimeoutError:
            _log.warning("APP working memory restore timed out")
        except Exception as e:
            _log.warning("APP working memory restore failed", error=str(e))

    state.memory_manager = mm
    state.long_term_memory = ltm

    available_llms = [p['name'] for p in get_all_providers() if p['available']]
    env = os.getenv("ENV", "dev")
    _log.info(
        "APP starting",
        version=APP_VERSION,
        env=env,
        pid=os.getpid(),
        llm=available_llms[0] if available_llms else "none",
        memory="on" if mm else "off",
    )
    if mm:
        _log.info(
            "APP memory status",
            working=f"{restored_turns if working_restored else 0}/{mm.working.MAX_TURNS}",
            longterm=ltm.get_stats().get('total_memories', 0) if ltm else 0,
        )
    _log.info("APP ready", host=HOST, port=PORT)

    yield

    _log.info("APP shutdown", reason="lifespan_end")

    app.state.shutting_down = True
    state.shutdown_event.set()

    active_streams = state.active_streams
    if active_streams:
        _log.info("APP waiting for active streams", count=len(active_streams))
        await asyncio.sleep(min(10, len(active_streams) * 2))

    for task in list(state.background_tasks):
        if not task.done():
            task.cancel()
            try:
                await asyncio.wait_for(task, timeout=SHUTDOWN_TASK_TIMEOUT)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
    _log.info("APP background tasks cleaned", count=len(state.background_tasks))

    if state.memory_manager:

        if state.memory_manager.working.save_to_disk():
            _log.info("APP working memory persisted", turns=state.memory_manager.working.get_turn_count())

        try:
            await asyncio.wait_for(
                state.memory_manager.end_session(
                    allow_llm_summary=False,
                    allow_fallback_summary=True
                ),
                timeout=SHUTDOWN_SESSION_TIMEOUT,
            )
        except Exception as e:
            _log.warning("APP session save failed", error=str(e))

    if state.long_term_memory:
        try:
            flushed = state.long_term_memory.flush_access_updates()
            if flushed > 0:
                _log.info("APP access updates flushed", count=flushed)
        except Exception as e:
            _log.warning("APP access update flush failed", error=str(e))

    # TTS manager shutdown (skip if never initialized)
    try:
        from backend.media.tts_manager import _lazy_tts_manager

        if _lazy_tts_manager._instance is not None:
            await asyncio.wait_for(
                _lazy_tts_manager._instance.shutdown(),
                timeout=SHUTDOWN_TASK_TIMEOUT,
            )
            _log.info("APP TTS manager shut down")
    except Exception as e:
        _log.warning("APP TTS shutdown failed", error=str(e))

    try:
        from backend.core.utils.http_pool import close_all
        await asyncio.wait_for(close_all(), timeout=SHUTDOWN_HTTP_POOL_TIMEOUT)
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

_log.debug(
    "APP module loaded",
    version=APP_VERSION,
    available_llms=[p['name'] for p in get_all_providers() if p['available']]
)

init_state(identity_manager=identity_manager)
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
