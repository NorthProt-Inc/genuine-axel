import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import asyncio
import os
import time
import traceback  # PERF-041: Import at module level instead of in exception handler
from typing import Optional
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
    DEFAULT_GEMINI_MODEL,
    ensure_data_directories,
    DATABASE_URL,
    PG_POOL_MIN,
    PG_POOL_MAX,
)
from backend.memory import MemoryManager
from backend.llm import get_all_providers
from backend.core.logging import get_logger, set_request_id, reset_request_id, get_request_id
from backend.core.telemetry.metrics import MetricsRegistry
from backend.core.errors import AxnmihnError
from backend.core.health.health_check import HealthChecker, HealthResult, HealthState
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
    websocket_router,
)
_log = get_logger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle handler for application startup and shutdown."""
    # PERF-037: Call ensure_data_directories in lifespan only
    ensure_data_directories()

    state = get_state()
    state.shutdown_event = asyncio.Event()
    state.background_tasks = []

    # Periodic consolidation task handle
    consolidation_task: Optional[asyncio.Task] = None

    app.state.shutting_down = False

    mm = None
    ltm = None
    pg_conn_mgr = None

    # PostgreSQL connection pool (if DATABASE_URL is configured)
    if DATABASE_URL:
        try:
            from backend.memory.pg import PgConnectionManager
            pg_conn_mgr = PgConnectionManager(
                dsn=DATABASE_URL,
                minconn=PG_POOL_MIN,
                maxconn=PG_POOL_MAX,
            )
            if pg_conn_mgr.health_check():
                _log.info("APP PG pool ready", dsn=DATABASE_URL[:40] + "...")
            else:
                _log.warning("APP PG health check failed, falling back to legacy backends")
                pg_conn_mgr.close()
                pg_conn_mgr = None
        except Exception as e:
            _log.warning("APP PG pool creation failed, falling back to legacy backends", error=str(e))
            pg_conn_mgr = None

    try:
        # Use Gemini for utility tasks (memory, graphrag, summarization)
        # Chat model is now Anthropic, handled separately by llm.router
        gem_client = get_gemini_client()
        mm = MemoryManager(
            client=gem_client,
            model_name=DEFAULT_GEMINI_MODEL,
            pg_conn_mgr=pg_conn_mgr,
        )
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

    # Initialize metrics registry
    _metrics = MetricsRegistry()
    _metrics.counter("http_requests_total", "Total HTTP requests")
    _metrics.histogram("http_request_duration_seconds", "HTTP request duration")
    _metrics.counter("http_errors_total", "Total HTTP errors")
    state.metrics = _metrics

    # Initialize health checker with component checks
    _checker = HealthChecker()

    async def _check_memory() -> HealthResult:
        if state.memory_manager:
            return HealthResult(HealthState.HEALTHY, 0.0, "memory ok")
        return HealthResult(HealthState.UNHEALTHY, 0.0, "memory not initialized")

    async def _check_llm() -> HealthResult:
        avail = [p for p in get_all_providers() if p.get("available")]
        if avail:
            return HealthResult(HealthState.HEALTHY, 0.0, f"{len(avail)} providers")
        return HealthResult(HealthState.UNHEALTHY, 0.0, "no providers")

    async def _check_pg() -> HealthResult:
        if pg_conn_mgr and pg_conn_mgr.health_check():
            return HealthResult(HealthState.HEALTHY, 0.0, "pg ok")
        if pg_conn_mgr:
            return HealthResult(HealthState.UNHEALTHY, 0.0, "pg health check failed")
        return HealthResult(HealthState.DEGRADED, 0.0, "pg not configured")

    _checker.register("memory", _check_memory)
    _checker.register("llm", _check_llm)
    _checker.register("postgresql", _check_pg)
    state.health_checker = _checker

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

    # Start periodic consolidation background task
    async def _periodic_consolidation() -> None:
        """Run memory consolidation every 6 hours."""
        while True:
            await asyncio.sleep(6 * 3600)
            if ltm:
                try:
                    result = await asyncio.to_thread(ltm.consolidate_memories)
                    _log.info("APP consolidation done", result=result)
                except Exception as e:
                    _log.warning("APP consolidation failed", error=str(e))

    if ltm:
        consolidation_task = asyncio.create_task(_periodic_consolidation())

    yield

    # Cancel consolidation task
    if consolidation_task and not consolidation_task.done():
        consolidation_task.cancel()
        try:
            await asyncio.wait_for(consolidation_task, timeout=1.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

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
                    allow_llm_summary=True,
                    allow_fallback_summary=True,
                    summary_timeout_seconds=30.0,
                ),
                timeout=SHUTDOWN_SESSION_TIMEOUT + 10.0,
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

    # Close PG connection pool
    if pg_conn_mgr is not None:
        try:
            pg_conn_mgr.close()
            _log.info("APP PG pool closed")
        except Exception as e:
            _log.warning("APP PG pool close failed", error=str(e))

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
    t0 = time.perf_counter()
    try:
        response = await call_next(request)
    finally:
        reset_request_id(token)
        elapsed = time.perf_counter() - t0
        _state = get_state()
        if _state.metrics:
            req_counter = _state.metrics._metrics.get("http_requests_total")
            if req_counter:
                req_counter.inc()
            dur_hist = _state.metrics._metrics.get("http_request_duration_seconds")
            if dur_hist:
                dur_hist.observe(elapsed)
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
app.include_router(websocket_router)
_log.debug(
    "APP routers mounted",
    routers=["status", "chat", "memory", "mcp", "media", "openai", "audio", "websocket"]
)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handle all unhandled exceptions with structured error hierarchy."""
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

    # Record error metric
    _state = get_state()
    if _state.metrics:
        err_counter = _state.metrics._metrics.get("http_errors_total")
        if err_counter:
            err_counter.inc()

    headers = {"X-Request-ID": req_id} if req_id else None

    if isinstance(exc, AxnmihnError):
        return JSONResponse(
            status_code=exc.http_status,
            headers=headers,
            content={
                "error": type(exc).__name__,
                "code": exc.code,
                "message": exc.message,
                "is_retryable": exc.is_retryable,
                "path": str(request.url.path),
                "request_id": req_id,
            }
        )

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

# PERF-037: Module-level initialization - IdentityManager created in lifespan
init_state(identity_manager=None)
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
