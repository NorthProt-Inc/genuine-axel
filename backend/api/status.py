import os
import time
from datetime import datetime
from typing import Dict, Any
from fastapi import APIRouter, Request, Depends
from fastapi.responses import PlainTextResponse
from backend.llm import get_all_providers, get_all_models, DEFAULT_PROVIDER
from backend.api.deps import is_request_authorized, is_api_key_configured, get_state, require_api_key
from backend.core import get_code_summary, list_source_files
from backend.core.logging import get_logger
from backend.config import APP_VERSION
from backend.core.utils.timezone import VANCOUVER_TZ
from backend.core.health.health_check import _START_TIME

_log = get_logger("api.status")

router = APIRouter(tags=["Status"])

@router.get("/auth/status")
async def auth_status(request: Request):
    authorized = is_request_authorized(request)
    return {
        "is_admin": authorized,
        "tier_limit": None,
        "char_limit": None,
        "auth_required": is_api_key_configured(),
    }

@router.get("/llm/providers")
def get_llm_providers():
    return {"providers": get_all_providers(), "default": DEFAULT_PROVIDER}

@router.get("/models")
def get_available_models():
    return {
        "models": get_all_models(),
        "default": "gemini",
    }

def _check_env_key(key: str) -> Dict[str, Any]:
    value = os.getenv(key, "")
    return {
        "configured": bool(value),
        "masked": f"{value[:4]}...{value[-4:]}" if len(value) > 8 else ("***" if value else None)
    }

def _check_module_health(name: str, obj: Any, extra_checks: Dict[str, Any] = None) -> Dict[str, Any]:
    result = {
        "status": "ok" if obj else "unavailable",
        "initialized": obj is not None,
    }
    if extra_checks:
        result.update(extra_checks)
    return result

@router.get("/health")
async def health_check():
    state = get_state()
    now = datetime.now(VANCOUVER_TZ)

    modules = {}
    issues = []

    if state.memory_manager:
        working = state.memory_manager.working
        long_term = state.memory_manager.long_term

        modules["memory"] = {
            "status": "ok",
            "working_memory": {
                "turns": working.get_turn_count() if working else 0,
                "max_turns": working.MAX_TURNS if working else 0,
                "session_id": working.session_id[:8] if working and working.session_id else None,
            },
            "long_term_memory": {
                "total": long_term.get_stats().get("total_memories", 0) if long_term else 0,
            },
            "session_archive": {
                "status": "ok" if state.memory_manager.session_archive else "unavailable",
            },
            "graph_rag": {
                "status": "ok" if state.memory_manager.graph_rag else "unavailable",
                "entities": len(state.memory_manager.knowledge_graph.entities) if state.memory_manager.knowledge_graph else 0,
            },
        }
    else:
        modules["memory"] = {"status": "unavailable"}
        issues.append("Memory system not initialized")

    providers = get_all_providers()
    available_llms = [p["name"] for p in providers if p.get("available")]
    modules["llm"] = {
        "status": "ok" if available_llms else "unavailable",
        "providers": [
            {"name": p["name"], "available": p.get("available", False)}
            for p in providers
        ],
        "default": DEFAULT_PROVIDER,
    }
    if not available_llms:
        issues.append("No LLM providers available")

    modules["identity"] = _check_module_health("identity_manager", state.identity_manager)

    modules["mcp_server"] = _check_module_health("mcp_server", state.mcp_server)

    api_keys = {
        "GEMINI_API_KEY": _check_env_key("GEMINI_API_KEY"),
        "DEEPGRAM_API_KEY": _check_env_key("DEEPGRAM_API_KEY"),
        "TAVILY_API_KEY": _check_env_key("TAVILY_API_KEY"),
    }

    critical_modules = ["memory", "llm"]
    critical_ok = all(
        modules.get(m, {}).get("status") == "ok"
        for m in critical_modules
    )

    if critical_ok and not issues:
        overall_status = "healthy"
    elif critical_ok:
        overall_status = "degraded"
    else:
        overall_status = "unhealthy"

    _log.info(
        "Health check",
        status=overall_status,
        issues=len(issues),
        memory="ok" if state.memory_manager else "off",
        llms=len(available_llms),
    )

    # Run health checker if available
    checker_results = {}
    if hasattr(state, "health_checker") and state.health_checker:
        try:
            checker_results = await state.health_checker.check_all()
        except Exception:
            pass

    return {
        "status": overall_status,
        "version": APP_VERSION,
        "timestamp": now.isoformat(),
        "uptime_seconds": round(time.time() - _START_TIME, 1),
        "uptime_info": {
            "working_session": state.memory_manager.working.session_id[:8] if state.memory_manager and state.memory_manager.working.session_id else None,
            "turn_count": state.turn_count,
        },
        "modules": modules,
        "component_checks": {
            name: {"state": r.state.value, "latency_ms": round(r.latency_ms, 2), "message": r.message}
            for name, r in checker_results.items()
        } if checker_results else None,
        "api_keys": api_keys,
        "issues": issues if issues else None,
    }

@router.get("/health/quick")
async def health_quick():
    state = get_state()

    memory_ok = state.memory_manager is not None
    llm_ok = any(p.get("available") for p in get_all_providers())

    status = "ok" if (memory_ok and llm_ok) else "degraded"

    return {
        "status": status,
        "version": APP_VERSION,
        "memory": "ok" if memory_ok else "off",
        "llm": "ok" if llm_ok else "off",
    }

@router.get("/metrics")
async def metrics_endpoint():
    state = get_state()
    if state.metrics:
        return PlainTextResponse(
            content=state.metrics.format_all(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )
    return PlainTextResponse(content="", media_type="text/plain")

@router.get("/code/summary", dependencies=[Depends(require_api_key)])
async def code_summary():
    return {"summary": get_code_summary()}

@router.get("/code/files", dependencies=[Depends(require_api_key)])
async def code_files():
    return {"files": list_source_files()}
