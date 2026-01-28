import logging
import os
import sys
import json
import functools
import inspect
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar, ParamSpec
from zoneinfo import ZoneInfo

P = ParamSpec('P')
T = TypeVar('T')

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

class SmartFormatter(logging.Formatter):

    HIGHLIGHT_KEYS = {
        "model": "MODEL",
        "tier": "MODEL",
        "provider": "MODEL",
        "tokens": "MEMORY",
        "memories": "MEMORY",
        "working": "MEMORY",
        "longterm": "MEMORY",
        "session": "SUCCESS",
        "latency": "WARNING",
        "error": "ERROR",
    }

    def __init__(self, use_colors: bool = True, compact: bool = False):
        super().__init__()
        self.use_colors = use_colors and Colors._enabled()
        self.compact = compact

    def _c(self, key: str) -> str:

        if not self.use_colors:
            return ""
        return _COLORS.get(key, "")

    def _format_value(self, value: Any, max_len: int = 60) -> str:

        if value is None:
            return "null"

        if isinstance(value, bool):
            return "yes" if value else "no"

        if isinstance(value, (int, float)):
            return str(value)

        if isinstance(value, (list, tuple)):
            if len(value) == 0:
                return "[]"
            if len(value) <= 3:
                return f"[{', '.join(str(v) for v in value)}]"
            return f"[{len(value)} items]"

        if isinstance(value, dict):
            if len(value) == 0:
                return "{}"
            return f"{{{len(value)} keys}}"

        s = str(value)
        if len(s) > max_len:
            return s[:max_len-3] + "..."
        return s

    def _get_module_color(self, name: str) -> str:

        if not self.use_colors:
            return ""

        prefix = name.split(".")[0].lower()
        return MODULE_COLORS.get(prefix, _COLORS.get("MODULE", ""))

    def _get_module_abbrev(self, name: str) -> str:

        prefix = name.split(".")[0].lower()
        return MODULE_ABBREV.get(prefix, prefix[:3].upper())

    def format(self, record: logging.LogRecord) -> str:
        level = record.levelname
        label, color_key = LEVEL_STYLES.get(level, (level[:5], "INFO"))

        c_reset = self._c("RESET")
        c_dim = self._c("DIM")
        c_time = self._c("TIME")
        c_level = self._c(color_key)
        c_module = self._get_module_color(record.name)
        c_sep = self._c("SEPARATOR")
        c_key = self._c("KEY")
        c_value = self._c("VALUE")

        now = datetime.now(VANCOUVER_TZ)
        timestamp = now.strftime("%H:%M:%S") + f".{now.microsecond // 1000:03d}"

        name_parts = record.name.split(".")
        mod_abbrev = self._get_module_abbrev(record.name)
        if len(name_parts) > 1:
            submod = ".".join(name_parts[1:])
            if len(submod) > 9:
                submod = submod[:8] + "…"
            module_display = f"{mod_abbrev}|{submod}"
        else:
            module_display = mod_abbrev

        if len(module_display) > 14:
            module_display = module_display[:13] + "…"

        req_part = ""
        elapsed_part = ""

        req_id = get_request_id()
        if req_id:
            req_part = f"{c_dim}{req_id[:8]}{c_reset}"

        try:
            from .request_tracker import get_tracker
            tracker = get_tracker()
            if tracker:
                if not req_id:
                    req_part = f"{c_dim}{tracker.request_id[:8]}{c_reset}"
                ms = tracker.elapsed_ms()
                if ms >= 1000:
                    elapsed_part = f" {c_dim}+{ms/1000:.1f}s{c_reset}"
                elif ms >= 100:
                    elapsed_part = f" {c_dim}+{ms:.0f}ms{c_reset}"
        except Exception:
            pass

        parts = [
            f"{c_time}{timestamp}{c_reset}",
            f"{c_level}{label}{c_reset}",
            f"[{c_module}{module_display:14}{c_reset}]",
            record.getMessage(),
        ]
        line = " ".join(parts)

        if hasattr(record, 'extra_data') and record.extra_data:
            extras = []
            for key, value in record.extra_data.items():

                highlight = self.HIGHLIGHT_KEYS.get(key.lower())
                if highlight and self.use_colors:
                    key_color = self._c(highlight)
                else:
                    key_color = c_key

                formatted_val = self._format_value(value)
                extras.append(f"{key_color}{key}{c_reset}={c_value}{formatted_val}{c_reset}")

            if extras:
                line += f" {c_sep}│{c_reset} " + " ".join(extras)

        line += elapsed_part

        if record.exc_info:
            line += f"\n{c_level}{self.formatException(record.exc_info)}{c_reset}"

        return line

class PlainFormatter(logging.Formatter):

    def _get_module_display(self, name: str) -> str:

        name_parts = name.split(".")
        prefix = name_parts[0].lower()
        mod_abbrev = MODULE_ABBREV.get(prefix, prefix[:3].upper())

        if len(name_parts) > 1:
            submod = ".".join(name_parts[1:])
            if len(submod) > 9:
                submod = submod[:8] + "…"
            module_display = f"{mod_abbrev}|{submod}"
        else:
            module_display = mod_abbrev

        if len(module_display) > 14:
            module_display = module_display[:13] + "…"
        return module_display

    def format(self, record: logging.LogRecord) -> str:
        now = datetime.now(VANCOUVER_TZ)
        timestamp = now.strftime("%Y-%m-%d %H:%M:%S.") + f"{now.microsecond // 1000:03d}"

        module = self._get_module_display(record.name)

        req_id = get_request_id()
        req_prefix = f"{req_id[:8]}│" if req_id else ""

        line = f"{timestamp} {record.levelname:7} [{req_prefix}{module:14}] {record.getMessage()}"

        if hasattr(record, 'extra_data') and record.extra_data:
            extras = []
            for k, v in record.extra_data.items():
                if isinstance(v, (list, tuple)) and len(v) > 3:
                    v = f"[{len(v)} items]"
                elif isinstance(v, dict) and len(v) > 0:
                    v = f"{{{len(v)} keys}}"
                extras.append(f"{k}={v}")
            if extras:
                line += " │ " + " ".join(extras)

        if record.exc_info:
            line += f"\n{self.formatException(record.exc_info)}"

        return line

class JsonFormatter(logging.Formatter):

    def format(self, record: logging.LogRecord) -> str:
        now = datetime.now(VANCOUVER_TZ).isoformat()
        payload = {
            "ts": now,
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }

        req_id = get_request_id()
        if req_id:
            payload["req"] = req_id

        if hasattr(record, 'extra_data') and record.extra_data:
            payload.update(record.extra_data)

        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, default=str)

def _configure_root_logger():

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    if not root.handlers:
        root.addHandler(logging.NullHandler())

_configure_root_logger()

class StructuredLogger:

    def __init__(self, name: str, level: int = None):
        self._logger = logging.getLogger(name)
        effective_level = level or DEFAULT_LEVEL
        self._logger.setLevel(effective_level)

        if not self._logger.handlers:

            console = logging.StreamHandler(sys.stdout)
            console.setFormatter(SmartFormatter(use_colors=True))
            console.setLevel(effective_level)
            self._logger.addHandler(console)

            log_dir = Path(__file__).parent.parent.parent.parent / "logs"
            if log_dir.exists():
                try:
                    from logging.handlers import RotatingFileHandler
                    fh = RotatingFileHandler(
                        log_dir / "axnmihn.log",
                        encoding="utf-8",
                        maxBytes=10 * 1024 * 1024,
                        backupCount=5
                    )
                    fh.setFormatter(PlainFormatter())
                    fh.setLevel(logging.DEBUG)
                    self._logger.addHandler(fh)
                except Exception:
                    pass

            if LOG_JSON and log_dir.exists():
                try:
                    jh = logging.FileHandler(log_dir / "axnmihn.jsonl", encoding="utf-8")
                    jh.setFormatter(JsonFormatter())
                    jh.setLevel(logging.INFO)
                    self._logger.addHandler(jh)
                except Exception:
                    pass

            self._logger.propagate = False

    def _log(self, level: int, msg: str, **kwargs: Any) -> None:
        record = self._logger.makeRecord(
            self._logger.name, level, "", 0, msg, (), None
        )
        record.extra_data = kwargs
        self._logger.handle(record)
        for h in self._logger.handlers:
            h.flush()

    def debug(self, msg: str, **kwargs) -> None:
        self._log(logging.DEBUG, msg, **kwargs)

    def info(self, msg: str, **kwargs) -> None:
        self._log(logging.INFO, msg, **kwargs)

    def warning(self, msg: str, **kwargs) -> None:
        self._log(logging.WARNING, msg, **kwargs)

    def error(self, msg: str, **kwargs) -> None:
        self._log(logging.ERROR, msg, **kwargs)

    def critical(self, msg: str, **kwargs) -> None:
        self._log(logging.CRITICAL, msg, **kwargs)

    def exception(self, msg: str, **kwargs) -> None:

        record = self._logger.makeRecord(
            self._logger.name, logging.ERROR, "", 0, msg, (), sys.exc_info()
        )
        record.extra_data = kwargs
        self._logger.handle(record)

def logged(
    entry: bool = True,
    exit: bool = True,
    level: int = logging.DEBUG,
    log_args: bool = False,
    log_result: bool = False,
):

    def decorator(func: Callable[P, T]) -> Callable[P, T]:

        module = func.__module__
        if module.startswith("backend."):
            module = module[8:]
        logger_name = module

        @functools.wraps(func)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            _log = get_logger(logger_name)
            fn_name = func.__name__

            if entry:
                if log_args:

                    sig = inspect.signature(func)
                    bound = sig.bind(*args, **kwargs)
                    bound.apply_defaults()

                    arg_info = {
                        k: v for k, v in bound.arguments.items()
                        if k != 'self' and not k.startswith('_')
                    }
                    _log._log(level, f"→ {fn_name}", **arg_info)
                else:
                    _log._log(level, f"→ {fn_name}")

            try:
                result = await func(*args, **kwargs)
                if exit:
                    if log_result and result is not None:
                        _log._log(level, f"← {fn_name}", result=result)
                    else:
                        _log._log(level, f"← {fn_name}")
                return result
            except Exception as e:
                _log.error(f"✗ {fn_name}", error=str(e)[:100])
                raise

        @functools.wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            _log = get_logger(logger_name)
            fn_name = func.__name__

            if entry:
                if log_args:
                    sig = inspect.signature(func)
                    bound = sig.bind(*args, **kwargs)
                    bound.apply_defaults()
                    arg_info = {
                        k: v for k, v in bound.arguments.items()
                        if k != 'self' and not k.startswith('_')
                    }
                    _log._log(level, f"→ {fn_name}", **arg_info)
                else:
                    _log._log(level, f"→ {fn_name}")

            try:
                result = func(*args, **kwargs)
                if exit:
                    if log_result and result is not None:
                        _log._log(level, f"← {fn_name}", result=result)
                    else:
                        _log._log(level, f"← {fn_name}")
                return result
            except Exception as e:
                _log.error(f"✗ {fn_name}", error=str(e)[:100])
                raise

        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator

_loggers: dict[str, StructuredLogger] = {}

def get_logger(name: str = "axnmihn") -> StructuredLogger:

    if name not in _loggers:
        _loggers[name] = StructuredLogger(name)
    return _loggers[name]

def set_log_level(level: str) -> None:

    numeric = LOG_LEVEL_MAP.get(level.upper(), logging.DEBUG)
    for logger in _loggers.values():
        logger._logger.setLevel(numeric)
        for h in logger._logger.handlers:
            if isinstance(h, logging.StreamHandler):
                h.setLevel(numeric)
