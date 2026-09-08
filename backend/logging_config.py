"""
vQA — Structured Logging Configuration
========================================
Module: backend/logging_config.py

Implements the JsonFormatter and request-scoped trace_id infrastructure
for the per-user-session-isolation feature (Phase 1, ADR-8).

Architecture Notes (ADR-8)
---------------------------
Full OpenTelemetry SDK bootstrap is future work (CLAUDE.md §"OpenTelemetry First"
is aspirational; current codebase has zero OTel deps).  This module ships
structured JSON logs to stdout (CloudWatch awslogs driver captures them).
CloudWatch Metric Filters aggregate the ``event`` field into metrics.

Log format:
  {
    "timestamp": "2026-08-06T12:34:56.789Z",
    "level": "INFO",
    "logger": "backend.session.manager",
    "event": "session.started",       ← structured key (used by Metric Filters)
    "trace_id": "abc123...",           ← X-Request-Id header value
    "message": "...",
    "session_id": "...",               ← optional, present in session events
    ...
  }

When LOG_FORMAT=text (local dev), the formatter falls back to a human-readable
plain-text format identical to the previous basicConfig output.

Usage
-----
    from backend.logging_config import configure_logging
    configure_logging()  # call once at startup, before any logger.info()

The trace_id ContextVar is populated by the request middleware (added to
backend/main.py in Phase 1).  Import it for use in other modules::

    from backend.logging_config import current_trace_id
    trace_id = current_trace_id.get("")
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from contextvars import ContextVar
from typing import Optional

#: Request-scoped trace ID (X-Request-Id header value).
#: Set by the HTTP middleware on every incoming request.
#: Default is "" (no trace context — e.g., in background tasks).
current_trace_id: ContextVar[str] = ContextVar("current_trace_id", default="")

#: Request-scoped session ID (from vqa_session cookie).
current_session_id: ContextVar[str] = ContextVar("current_session_id", default="")


class JsonFormatter(logging.Formatter):
    """
    A stdlib-only JSON log formatter.

    Emits one JSON object per log record to stdout so the CloudWatch awslogs
    driver captures and indexes it for Metric Filters + Logs Insights queries.

    Fields emitted:
      timestamp  ISO-8601 UTC timestamp with millisecond precision.
      level      Log level name (INFO, WARNING, ERROR, …).
      logger     Logger name (module path).
      message    Formatted log message.
      trace_id   Current X-Request-Id (from ContextVar, "" if not set).
      session_id Current session (from ContextVar, "" if not set).
      exc_info   Exception traceback string (only when exc_info is set).

    Any extra keyword arguments passed to logger.info(msg, extra={...}) are
    included as top-level fields.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "timestamp": self._isotime(record.created),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "trace_id": current_trace_id.get(""),
            "session_id": current_session_id.get(""),
        }

        # Include any extra fields added via logger.info(msg, extra={...})
        _STANDARD_ATTRS = frozenset(logging.LogRecord(
            "", 0, "", 0, "", (), None
        ).__dict__.keys())
        for key, val in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                payload[key] = val

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)

    @staticmethod
    def _isotime(created: float) -> str:
        """Convert a Unix timestamp to an ISO-8601 UTC string."""
        t = time.gmtime(created)
        ms = int((created % 1) * 1000)
        return (
            f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d}T"
            f"{t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d}.{ms:03d}Z"
        )


def configure_logging() -> None:
    """
    Configure structured logging for the vQA application.

    Reads LOG_FORMAT from the environment:
      ``json`` (default in production) — uses JsonFormatter.
      ``text`` (local dev)             — uses a human-readable plain-text format.

    Also reads LOG_LEVEL (DEBUG, INFO, WARNING, ERROR).

    Call once at application startup (before any logger.info() calls).
    """
    log_format = os.environ.get("LOG_FORMAT", "json").strip().lower()
    log_level_name = os.environ.get("LOG_LEVEL", "INFO").strip().upper()
    log_level = getattr(logging, log_level_name, logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Remove all existing handlers to avoid duplicate output
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)

    if log_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        # Human-readable text format for local development
        text_fmt = "%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s"
        handler.setFormatter(logging.Formatter(fmt=text_fmt, datefmt="%Y-%m-%d %H:%M:%S"))

    root_logger.addHandler(handler)

    # Quiet noisy third-party loggers (same as before in main.py)
    for noisy in ("httpx", "httpcore", "botocore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    logging.getLogger(__name__).info(
        '{"event": "logging.configured", "format": "%s", "level": "%s"}',
        log_format, log_level_name,
    )
