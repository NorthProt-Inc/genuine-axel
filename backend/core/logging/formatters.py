import json
import logging
from datetime import datetime
from typing import Any

from .constants import (
    LEVEL_STYLES,
    MODULE_ABBREV,
    MODULE_COLORS,
    VANCOUVER_TZ,
    Colors,
    _COLORS,
    get_request_id,
)


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

        elapsed_part = ""

        try:
            from .request_tracker import get_tracker
            tracker = get_tracker()
            if tracker:
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
