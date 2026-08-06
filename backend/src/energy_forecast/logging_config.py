"""Structured JSON logging and correlation context."""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from typing import Any

from energy_forecast.config import Settings

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def bind_request_id(request_id: str) -> Token[str | None]:
    """Bind a request ID for logs emitted in the current async context."""
    return _request_id.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    """Restore the previous correlation context."""
    _request_id.reset(token)


class JsonFormatter(logging.Formatter):
    """Render one stable JSON object per log record."""

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._service = settings.service.value
        self._environment = settings.environment.value
        self._code_commit = settings.code_commit

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "service": self._service,
            "environment": self._environment,
            "code_commit": self._code_commit,
            "event": getattr(record, "event", record.getMessage()),
            "request_id": getattr(record, "request_id", _request_id.get()),
            "job_id": getattr(record, "job_id", None),
            "duration_ms": getattr(record, "duration_ms", None),
            "error_code": getattr(record, "error_code", None),
        }
        for field in ("method", "path", "status_code"):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)


def configure_logging(settings: Settings) -> None:
    """Configure the process root logger exactly once per settings application."""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter(settings))

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(settings.log_level)

    for logger_name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(logger_name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
