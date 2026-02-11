import logging
import os
import sys
from contextvars import ContextVar
from typing import Optional
from zoneinfo import ZoneInfo

P_SENTINEL = None  # ParamSpec/TypeVar are in decorator.py

VANCOUVER_TZ = ZoneInfo("America/Vancouver")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}
DEFAULT_LEVEL = LOG_LEVEL_MAP.get(LOG_LEVEL, logging.INFO)
LOG_JSON = os.getenv("LOG_JSON", "").lower() in ("1", "true", "yes")

_request_id: ContextVar[Optional[str]] = ContextVar("request_id", default=None)


def set_request_id(request_id: str):
    return _request_id.set(request_id)


def reset_request_id(token) -> None:
    _request_id.reset(token)


def get_request_id() -> Optional[str]:
    return _request_id.get()


MODULE_COLORS = {
    "api":       "\033[94m",
    "core":      "\033[96m",
    "memory":    "\033[95m",
    "llm":       "\033[92m",
    "mcp":       "\033[93m",
    "protocols": "\033[93m",
    "media":     "\033[38;5;208m",
    "wake":      "\033[91m",
    "tools":     "\033[97m",
}

MODULE_ABBREV = {
    "api": "API",
    "core": "COR",
    "memory": "MEM",
    "llm": "LLM",
    "mcp": "MCP",
    "protocols": "MCP",
    "media": "MED",
    "wake": "WAK",
    "tools": "TOL",
}

ABBREV = {

    "request": "req",
    "response": "res",
    "message": "msg",
    "error": "err",
    "config": "cfg",
    "connection": "conn",
    "timeout": "tout",
    "memory": "mem",
    "context": "ctx",
    "tokens": "tok",
    "function": "fn",
    "parameter": "param",
    "execution": "exec",
    "initialization": "init",
    "milliseconds": "ms",
    "seconds": "sec",
    "count": "cnt",
    "length": "len",
    "session": "sess",
    "entity": "ent",
    "device": "dev",
    "assistant": "asst",
    "received": "recv",
    "sent": "sent",
    "success": "ok",
    "failure": "fail",
    "building": "build",
    "processing": "proc",
    "completed": "done",
    "started": "start",
    "finished": "fin",
    "database": "db",
    "query": "qry",
    "result": "res",
    "input": "in",
    "output": "out",
    "latency": "lat",
    "duration": "dur",
    "provider": "prov",
    "model": "mdl",
}


def abbreviate(text: str) -> str:

    result = text
    for full, abbr in ABBREV.items():

        result = result.replace(full.capitalize(), abbr.upper())
        result = result.replace(full, abbr)
    return result


class Colors:

    @staticmethod
    def _enabled() -> bool:

        if os.getenv("NO_COLOR"):
            return False
        return sys.stdout.isatty()

    @classmethod
    def get(cls, color_code: str) -> str:
        return color_code if cls._enabled() else ""


_COLORS = {
    "RESET": "\033[0m",
    "BOLD": "\033[1m",
    "DIM": "\033[2m",
    "DEBUG": "\033[36m",
    "INFO": "\033[32m",
    "WARNING": "\033[33m",
    "ERROR": "\033[31m",
    "CRITICAL": "\033[35m",
    "TIME": "\033[90m",
    "MODULE": "\033[34m",
    "KEY": "\033[90m",
    "VALUE": "\033[37m",
    "MODEL": "\033[95m",
    "MEMORY": "\033[96m",
    "SUCCESS": "\033[92m",
    "SEPARATOR": "\033[90m",
}

LEVEL_STYLES = {
    "DEBUG": ("DEBUG", "DEBUG"),
    "INFO": (" INFO", "INFO"),
    "WARNING": (" WARN", "WARNING"),
    "ERROR": ("ERROR", "ERROR"),
    "CRITICAL": ("CRIT!", "CRITICAL"),
}
