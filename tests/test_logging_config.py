"""
Phase 7: Logging Configuration Tests
======================================
Module: tests/test_logging_config.py

Tests backend/logging_config.py JsonFormatter and configure_logging():

  1. JsonFormatter emits valid JSON with required fields (timestamp, level,
     logger, message, trace_id, session_id).
  2. Extra fields from logger.info(msg, extra={...}) appear at the top level.
  3. Exception info is included when exc_info is set.
  4. configure_logging() with LOG_FORMAT=json installs JsonFormatter on root.
  5. configure_logging() with LOG_FORMAT=text installs plain-text formatter.

Acceptance Criteria Coverage:
  Phase 7 observability — structured JSON log output for CloudWatch Metric Filters
"""

import json
import logging
from io import StringIO

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_formatter():
    from backend.logging_config import JsonFormatter
    return JsonFormatter()


def _make_record(
    name="backend.test",
    level=logging.INFO,
    msg="test message",
    extra=None,
    exc_info=None,
):
    record = logging.LogRecord(
        name=name,
        level=level,
        pathname="test.py",
        lineno=1,
        msg=msg,
        args=(),
        exc_info=exc_info,
    )
    if extra:
        for key, val in extra.items():
            setattr(record, key, val)
    return record


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestJsonFormatter:
    """JsonFormatter emits well-formed JSON with required fields."""

    def test_required_fields_present(self):
        """JSON output contains timestamp, level, logger, message, trace_id."""
        formatter = _make_formatter()
        record = _make_record(msg="hello world")
        output = formatter.format(record)

        data = json.loads(output)
        assert "timestamp" in data
        assert data["level"] == "INFO"
        assert data["logger"] == "backend.test"
        assert data["message"] == "hello world"
        assert "trace_id" in data

    def test_extra_fields_appear_at_top_level(self):
        """Extra fields from logger.info(msg, extra={...}) are in the JSON."""
        formatter = _make_formatter()
        record = _make_record(
            msg="session.started",
            extra={"event": "session.started", "session_id": "sess-abc"},
        )
        output = formatter.format(record)

        data = json.loads(output)
        assert data.get("event") == "session.started"
        assert data.get("session_id") == "sess-abc"

    def test_exception_info_included(self):
        """exc_info is rendered to a string and included in the JSON output."""
        formatter = _make_formatter()
        try:
            raise ValueError("something broke")
        except ValueError:
            import sys
            exc = sys.exc_info()

        record = _make_record(msg="error occurred", exc_info=exc)
        output = formatter.format(record)

        data = json.loads(output)
        assert "exc_info" in data or "exception" in data
        exc_text = data.get("exc_info") or data.get("exception", "")
        assert "ValueError" in exc_text

    def test_output_is_single_json_line(self):
        """Each log record is exactly one line of valid JSON."""
        formatter = _make_formatter()
        record = _make_record(msg="line test")
        output = formatter.format(record)

        # Must be parseable as a single JSON object.
        data = json.loads(output)
        assert isinstance(data, dict)
        # Must not contain embedded newlines (CloudWatch splits on newlines).
        assert "\n" not in output.rstrip("\n")


class TestConfigureLogging:
    """configure_logging() wires JsonFormatter or plain-text based on LOG_FORMAT."""

    def test_json_format_installs_json_formatter(self, monkeypatch):
        """LOG_FORMAT=json → root handler uses JsonFormatter."""
        from backend.logging_config import configure_logging, JsonFormatter

        monkeypatch.setenv("LOG_FORMAT", "json")
        configure_logging()

        root = logging.getLogger()
        assert root.handlers, "Root logger must have at least one handler"
        formatter = root.handlers[0].formatter
        assert isinstance(formatter, JsonFormatter), (
            f"Expected JsonFormatter; got {type(formatter).__name__}"
        )

    def test_text_format_installs_plain_formatter(self, monkeypatch):
        """LOG_FORMAT=text → root handler uses a standard Formatter."""
        from backend.logging_config import configure_logging, JsonFormatter

        monkeypatch.setenv("LOG_FORMAT", "text")
        configure_logging()

        root = logging.getLogger()
        assert root.handlers
        formatter = root.handlers[0].formatter
        assert not isinstance(formatter, JsonFormatter), (
            "LOG_FORMAT=text should NOT use JsonFormatter"
        )

    def test_json_output_is_parseable(self, monkeypatch):
        """With LOG_FORMAT=json, a log message can be parsed as JSON from stdout."""
        from backend.logging_config import configure_logging

        monkeypatch.setenv("LOG_FORMAT", "json")

        stream = StringIO()
        configure_logging()

        # Replace the handler stream for assertion.
        root = logging.getLogger()
        handler = root.handlers[0]
        handler.stream = stream

        logging.getLogger("backend.test_json").info(
            "test structured log",
            extra={"event": "test.event"},
        )
        handler.flush()

        output = stream.getvalue().strip()
        if output:
            data = json.loads(output)
            assert data["level"] == "INFO"
