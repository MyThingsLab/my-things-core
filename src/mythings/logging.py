from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from logging import CRITICAL, DEBUG, ERROR, INFO, WARNING, Logger
from pathlib import Path
from typing import Any

# Runtime logging, not a contract: every My[X] tool wires one logger through
# `configure()` and gets two independent sinks for free - JSONL for a machine
# (or a later Engine call) to grep, colorized text for a human at a terminal.

__all__ = ["CRITICAL", "DEBUG", "ERROR", "INFO", "WARNING", "configure", "log"]

_LEVEL_COLORS = {
    DEBUG: "\033[2m",
    INFO: "\033[36m",
    WARNING: "\033[33m",
    ERROR: "\033[31m",
    CRITICAL: "\033[41m",
}
_RESET = "\033[0m"


class JSONLFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "tool": record.name,
            "level": record.levelname.lower(),
            "msg": record.getMessage(),
        }
        data = getattr(record, "data", None)
        if data:
            payload["data"] = data
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, separators=(",", ":"), sort_keys=True)


class HumanFormatter(logging.Formatter):
    def __init__(self, *, color: bool = True) -> None:
        super().__init__()
        self._color = color

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, UTC).strftime("%H:%M:%S")
        line = f"{ts} {record.levelname:<8} [{record.name}] {record.getMessage()}"
        data = getattr(record, "data", None)
        if data:
            line += " " + " ".join(f"{k}={v}" for k, v in data.items())
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        color = _LEVEL_COLORS.get(record.levelno, "") if self._color else ""
        return f"{color}{line}{_RESET}" if color else line


def configure(
    tool: str,
    *,
    level: int = INFO,
    json_path: str | Path | None = None,
    console: bool = True,
) -> Logger:
    logger = logging.getLogger(tool)
    logger.setLevel(level)
    logger.propagate = False
    logger.handlers.clear()

    if console:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(HumanFormatter(color=sys.stderr.isatty()))
        logger.addHandler(handler)

    if json_path is not None:
        path = Path(json_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(path, encoding="utf-8")
        file_handler.setFormatter(JSONLFormatter())
        logger.addHandler(file_handler)

    return logger


def log(logger: Logger, level: int, msg: str, /, **data: Any) -> None:
    logger.log(level, msg, extra={"data": data})
