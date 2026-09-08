"""Tests for the AC parser Stage 1 / Stage 2 timeout guards.

These prevent silent hangs when Bedrock stalls on large enriched inputs
(e.g., a 180-step enriched AC for a vpromotions ticket). The hang symptom
observed in production was: Stage 1 logs completion, then no further log
output for the request. With the timeout wrapper in place, either stage
must fail fast with a clear ValueError instead of blocking the event loop.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from backend.engine.ac_parser import _stage_1_normalize, _stage_2_compile


@pytest.mark.anyio
async def test_stage_1_raises_value_error_on_timeout(monkeypatch):
    """Stage 1's llm.ainvoke() call must be guarded by asyncio.wait_for."""
    monkeypatch.setattr(
        "backend.engine.ac_parser.settings.ac_parser_llm_timeout_seconds", 0.05
    )

    class _HangingLLM:
        async def ainvoke(self, messages):
            await asyncio.sleep(5.0)
            return MagicMock(content="never returned", response_metadata={})

    with patch("backend.engine.ac_parser._get_parser_llm", return_value=_HangingLLM()):
        with pytest.raises(ValueError) as excinfo:
            await _stage_1_normalize(
                raw_ac="some AC text",
                summary="ticket summary",
                description="ticket desc",
                run_id="test-stage1-timeout",
            )

    assert "Stage 1" in str(excinfo.value)
    assert "timed out" in str(excinfo.value).lower()
    assert "AC_PARSER_LLM_TIMEOUT_SECONDS" in str(excinfo.value)


@pytest.mark.anyio
async def test_stage_2_raises_value_error_on_timeout(monkeypatch):
    """Stage 2's instructor+boto3 run_in_executor call must be guarded by asyncio.wait_for."""
    monkeypatch.setattr(
        "backend.engine.ac_parser.settings.ac_parser_llm_timeout_seconds", 0.05
    )

    class _HangingInstructor:
        class messages:
            @staticmethod
            def create_with_completion(*args, **kwargs):
                import time
                time.sleep(5.0)
                return MagicMock(), {}

    with patch("backend.engine.ac_parser.boto3.client", return_value=MagicMock()), \
         patch("backend.engine.ac_parser.instructor.from_bedrock", return_value=_HangingInstructor()):
        with pytest.raises(ValueError) as excinfo:
            await _stage_2_compile(
                bdd_text="Given the user is on the page\nWhen they click Save\nThen a toast appears",
                run_id="test-stage2-timeout",
            )

    assert "Stage 2" in str(excinfo.value)
    assert "timed out" in str(excinfo.value).lower()
    assert "AC_PARSER_LLM_TIMEOUT_SECONDS" in str(excinfo.value)
