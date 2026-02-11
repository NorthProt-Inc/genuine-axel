import logging
import sys
from pathlib import Path
from typing import Any, Optional

from .constants import DEFAULT_LEVEL, LOG_JSON, LOG_LEVEL_MAP
from .formatters import JsonFormatter, PlainFormatter, SmartFormatter


def _configure_root_logger():

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    if not root.handlers:
        root.addHandler(logging.NullHandler())


_configure_root_logger()


class StructuredLogger:

    def __init__(self, name: str, level: Optional[int] = None):
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
        if level >= logging.WARNING:
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
