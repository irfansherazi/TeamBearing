"""
tests/engine/test_linear_bridge.py
=====================================
TASK-106: Unit tests for backend/engine/linear_bridge.py

Tests the pipeline orchestration logic in isolation using mocks for:
  - generator_node.generate_spec
  - validator_node.validate_spec
  - _run_playwright_spec (subprocess shim)
  - _run_analyze (LLM analysis)
  - asyncio.create_subprocess_exec (process-level)

All tests run in-process in < 100ms (no actual LLM or Playwright calls).

Coverage targets:
  - [x] Happy path: Generate OK → Validate OK → Execute OK → "completed"
  - [x] Generation failure → "failed" / GENERATION_FAILED
  - [x] Compile failure on attempt 1 + success on retry → "completed"
  - [x] Compile failure on both attempts → "failed" / COMPILE_FAILED
  - [x] Execute failure (non-collision) → "failed" / EXECUTE_FAILED + analyze called
  - [x] Execute failure (strict-mode collision) → retry → success → "completed"
  - [x] Execute failure (collision) → retry also fails → EXECUTE_FAILED + analyze
  - [x] Hard 5-minute timeout → "timeout" / PIPELINE_TIMEOUT
  - [x] broadcast_fn is called with log lines
  - [x] Unexpected exception → "error" / PIPELINE_ERROR
"""

import asyncio
from dataclasses import asdict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_CARD = {
    "ticket_id": "QA-170",
    "summary": "Search",
    "acceptance_criteria": "1. User can log in\n2. Search works",
    "expected_steps": [
        "Given the user is on the QA environment",
        "When the user clicks the Search button",
        "Then the Search form is displayed",
    ],
    "description": "Test the search functionality.",
}

COMPILE_OK_RESULT = {
    "ticket_id": "QA-170",
    "spec_path": "/fake/path/QA-170.spec.ts",
    "status": "COMPILE_OK",
    "attempts": 1,
    "compile_error": None,
}

COMPILE_FAILED_RESULT = {
    "ticket_id": "QA-170",
    "spec_path": "/fake/path/QA-170.spec.ts",
    "status": "COMPILE_FAILED",
    "attempts": 2,
    "compile_error": "TS2345: Argument type 'invalid_key' is not assignable...",
}

GEN_OK_RESULT = {
    "ticket_id": "QA-170",
    "spec_path": "/fake/path/QA-170.spec.ts",
    "spec_content": "import { test, expect } from '@playwright/test';\n\ntest('QA-170', async ({ page }) => {\n  await page.goto('/');\n});",
    "status": "generated",
    "selectors_used": ["search_button", "client_input"],
}

GEN_FAILED_RESULT = {
    "ticket_id": "QA-170",
    "spec_path": None,
    "spec_content": None,
    "status": "generation_failed",
    "error": "Bedrock connection refused",
}

PLAYWRIGHT_COLLISION_OUTPUT = (
    "Error: strict mode violation: locator('button') resolved to 3 elements\n"
    "  1) locator('button') — Search button\n"
    "  2) locator('button') — Cancel button\n"
    "  3) locator('button') — Login button\n"
)

PLAYWRIGHT_GENERIC_FAILURE_OUTPUT = (
    "Error: Timeout 30000ms exceeded\n"
    "  waiting for selector '#search-results'\n"
    "at QA-170.spec.ts:12\n"
)


# ---------------------------------------------------------------------------
# Helper: import module under test (avoid top-level import issues in CI)
# ---------------------------------------------------------------------------


def _import_bridge():
    from backend.engine import linear_bridge as bridge
    return bridge


# ---------------------------------------------------------------------------
# 1. Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_completes():
    """Generate OK → Validate OK → Execute OK → status='completed'."""
    bridge = _import_bridge()
    log_lines: list[str] = []

    async def _capture(line: str, stream: str = "stdout") -> None:
        log_lines.append(line)

    with (
        patch("backend.engine.generator_node.generate_spec", new=AsyncMock(return_value=GEN_OK_RESULT)),
        patch("backend.engine.validator_node.validate_spec", new=AsyncMock(return_value=COMPILE_OK_RESULT)),
        patch("backend.engine.linear_bridge._run_playwright_spec", new=AsyncMock(return_value=(True, "1 passed"))),
    ):
        result = await bridge.run_linear_pipeline(
            run_id="test-run-001",
            card=SAMPLE_CARD,
            tenant_id="vpromedia",
            broadcast_fn=_capture,
        )

    assert result.status == "completed"
    assert result.pipeline_status == "SUCCESS"
    assert result.ticket_id == "QA-170"
    assert result.elapsed_s >= 0
    assert result.error == ""
    assert result.analysis == ""
    # Broadcast must have been called with at least generate + validate + execute log lines
    assert any("Generate" in line or "generate" in line.lower() for line in log_lines)
    assert any("Validate" in line or "validate" in line.lower() for line in log_lines)
    assert any("Execute" in line or "execute" in line.lower() for line in log_lines)


# ---------------------------------------------------------------------------
# 2. Generation failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generation_failure():
    """Generator returns 'generation_failed' → status='failed' / GENERATION_FAILED."""
    bridge = _import_bridge()

    with patch("backend.engine.generator_node.generate_spec", new=AsyncMock(return_value=GEN_FAILED_RESULT)):
        result = await bridge.run_linear_pipeline(
            run_id="test-run-002",
            card=SAMPLE_CARD,
            tenant_id="vpromedia",
        )

    assert result.status == "failed"
    assert result.pipeline_status == "GENERATION_FAILED"
    assert "Bedrock connection refused" in result.error


@pytest.mark.asyncio
async def test_generator_raises_exception():
    """Generator raises an unexpected exception → status='failed' / GENERATION_FAILED."""
    bridge = _import_bridge()

    with patch(
        "backend.engine.generator_node.generate_spec",
        new=AsyncMock(side_effect=RuntimeError("network timeout")),
    ):
        result = await bridge.run_linear_pipeline(
            run_id="test-run-002b",
            card=SAMPLE_CARD,
            tenant_id="vpromedia",
        )

    assert result.status == "failed"
    assert result.pipeline_status == "GENERATION_FAILED"
    assert "network timeout" in result.error


# ---------------------------------------------------------------------------
# 3. Compile fail → auto-fix → success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compile_retry_success():
    """Compile fails on attempt 1 but auto-fix succeeds on attempt 2 → 'completed'."""
    bridge = _import_bridge()
    # validator returns COMPILE_OK with attempts=2 (internally retried)
    compile_ok_attempt2 = {**COMPILE_OK_RESULT, "attempts": 2}

    with (
        patch("backend.engine.generator_node.generate_spec", new=AsyncMock(return_value=GEN_OK_RESULT)),
        patch("backend.engine.validator_node.validate_spec", new=AsyncMock(return_value=compile_ok_attempt2)),
        patch("backend.engine.linear_bridge._run_playwright_spec", new=AsyncMock(return_value=(True, "1 passed"))),
    ):
        result = await bridge.run_linear_pipeline(
            run_id="test-run-003",
            card=SAMPLE_CARD,
            tenant_id="vpromedia",
        )

    assert result.status == "completed"
    assert result.pipeline_status == "SUCCESS"
    assert result.compile_attempts == 2


# ---------------------------------------------------------------------------
# 4. Compile fails on both attempts → COMPILE_FAILED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compile_failed_both_attempts():
    """Validator returns COMPILE_FAILED after 2 attempts → status='failed' / COMPILE_FAILED."""
    bridge = _import_bridge()

    with (
        patch("backend.engine.generator_node.generate_spec", new=AsyncMock(return_value=GEN_OK_RESULT)),
        patch("backend.engine.validator_node.validate_spec", new=AsyncMock(return_value=COMPILE_FAILED_RESULT)),
    ):
        result = await bridge.run_linear_pipeline(
            run_id="test-run-004",
            card=SAMPLE_CARD,
            tenant_id="vpromedia",
        )

    assert result.status == "failed"
    assert result.pipeline_status == "COMPILE_FAILED"
    assert result.compile_attempts == 2
    assert "TS2345" in result.error


# ---------------------------------------------------------------------------
# 5. Execute failure (non-collision) → Analyze called → EXECUTE_FAILED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_non_collision_failure_triggers_analyze():
    """Generic Playwright failure → _run_analyze called → status='failed' / EXECUTE_FAILED."""
    bridge = _import_bridge()

    with (
        patch("backend.engine.generator_node.generate_spec", new=AsyncMock(return_value=GEN_OK_RESULT)),
        patch("backend.engine.validator_node.validate_spec", new=AsyncMock(return_value=COMPILE_OK_RESULT)),
        patch(
            "backend.engine.linear_bridge._run_playwright_spec",
            new=AsyncMock(return_value=(False, PLAYWRIGHT_GENERIC_FAILURE_OUTPUT)),
        ),
        patch(
            "backend.engine.linear_bridge._run_analyze",
            new=AsyncMock(return_value="AC step 2 failed: #search-results not found within 30s."),
        ),
    ):
        result = await bridge.run_linear_pipeline(
            run_id="test-run-005",
            card=SAMPLE_CARD,
            tenant_id="vpromedia",
        )

    assert result.status == "failed"
    assert result.pipeline_status == "EXECUTE_FAILED"
    assert "AC step 2 failed" in result.analysis


# ---------------------------------------------------------------------------
# 6. Strict-mode collision → retry → success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_strict_mode_collision_retry_succeeds():
    """Collision on first execute → corrected spec → second execute passes → 'completed'."""
    bridge = _import_bridge()

    # First Playwright call: collision. Second call: success.
    mock_play = AsyncMock(side_effect=[
        (False, PLAYWRIGHT_COLLISION_OUTPUT),
        (True, "1 passed"),
    ])

    with (
        patch("backend.engine.generator_node.generate_spec", new=AsyncMock(return_value=GEN_OK_RESULT)),
        patch("backend.engine.validator_node.validate_spec", new=AsyncMock(return_value=COMPILE_OK_RESULT)),
        patch("backend.engine.linear_bridge._run_playwright_spec", new=mock_play),
        patch(
            "backend.engine.linear_bridge._request_strict_mode_fix",
            new=AsyncMock(return_value="import { test, expect } from '@playwright/test';\n// fixed"),
        ),
        # patch spec file write so we don't need a real filesystem
        patch("pathlib.Path.write_text", return_value=None),
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.read_text", return_value=GEN_OK_RESULT["spec_content"]),
    ):
        result = await bridge.run_linear_pipeline(
            run_id="test-run-006",
            card=SAMPLE_CARD,
            tenant_id="vpromedia",
        )

    assert result.status == "completed"
    assert result.pipeline_status == "SUCCESS"
    assert mock_play.call_count == 2


# ---------------------------------------------------------------------------
# 7. Collision retry also fails → EXECUTE_FAILED + analyze
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_strict_mode_collision_retry_also_fails():
    """Collision on attempt 1 + attempt 2 also fails → EXECUTE_FAILED."""
    bridge = _import_bridge()

    mock_play = AsyncMock(side_effect=[
        (False, PLAYWRIGHT_COLLISION_OUTPUT),
        (False, PLAYWRIGHT_COLLISION_OUTPUT),
        (False, PLAYWRIGHT_COLLISION_OUTPUT),
    ])

    with (
        patch("backend.engine.generator_node.generate_spec", new=AsyncMock(return_value=GEN_OK_RESULT)),
        patch("backend.engine.validator_node.validate_spec", new=AsyncMock(return_value=COMPILE_OK_RESULT)),
        patch("backend.engine.linear_bridge._run_playwright_spec", new=mock_play),
        patch(
            "backend.engine.linear_bridge._request_strict_mode_fix",
            new=AsyncMock(return_value="// corrected spec"),
        ),
        patch(
            "backend.engine.linear_bridge._run_analyze",
            new=AsyncMock(return_value="Persistent strict-mode collision on 'button'."),
        ),
        patch("pathlib.Path.write_text", return_value=None),
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.read_text", return_value=GEN_OK_RESULT["spec_content"]),
    ):
        result = await bridge.run_linear_pipeline(
            run_id="test-run-007",
            card=SAMPLE_CARD,
            tenant_id="vpromedia",
        )

    assert result.status == "failed"
    assert result.pipeline_status == "EXECUTE_FAILED"
    assert "strict-mode" in result.analysis.lower() or "collision" in result.analysis.lower()


# ---------------------------------------------------------------------------
# 8. Hard timeout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hard_timeout():
    """Pipeline exceeds timeout_s → status='timeout' / PIPELINE_TIMEOUT."""
    bridge = _import_bridge()

    async def _slow_generate(*args, **kwargs):
        await asyncio.sleep(10)  # far exceeds 0.01s timeout
        return GEN_OK_RESULT

    with patch("backend.engine.generator_node.generate_spec", new=AsyncMock(side_effect=_slow_generate)):
        result = await bridge.run_linear_pipeline(
            run_id="test-run-008",
            card=SAMPLE_CARD,
            tenant_id="vpromedia",
            timeout_s=0.01,  # 10ms — will time out immediately
        )

    assert result.status == "timeout"
    assert result.pipeline_status == "PIPELINE_TIMEOUT"
    assert "exceeded" in result.error


# ---------------------------------------------------------------------------
# 9. Unexpected exception in inner pipeline → "error" / PIPELINE_ERROR
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_node_exception_returns_failed():
    """Exception raised inside generate_spec node → caught by generate handler → 'failed'."""
    bridge = _import_bridge()

    with patch(
        "backend.engine.generator_node.generate_spec",
        new=AsyncMock(side_effect=MemoryError("OOM")),
    ):
        result = await bridge.run_linear_pipeline(
            run_id="test-run-009",
            card=SAMPLE_CARD,
            tenant_id="vpromedia",
        )

    # MemoryError in generate_spec is caught by the generate-node try/except
    # and returned as a structured failed result — NOT as an outer pipeline error.
    assert result.status == "failed"
    assert result.pipeline_status == "GENERATION_FAILED"
    assert "OOM" in result.error


@pytest.mark.asyncio
async def test_outer_pipeline_exception_returns_error():
    """Exception that escapes _run_pipeline_inner (e.g. from asyncio internals) → 'error'."""
    bridge = _import_bridge()

    # Patch the entire inner pipeline function to raise directly (simulates
    # an exception that bypasses all node-level try/except blocks).
    with patch(
        "backend.engine.linear_bridge._run_pipeline_inner",
        new=AsyncMock(side_effect=RuntimeError("unexpected internal crash")),
    ):
        result = await bridge.run_linear_pipeline(
            run_id="test-run-009b",
            card=SAMPLE_CARD,
            tenant_id="vpromedia",
        )

    assert result.status == "error"
    assert result.pipeline_status == "PIPELINE_ERROR"
    assert "unexpected internal crash" in result.error


# ---------------------------------------------------------------------------
# 10. broadcast_fn receives expected log line patterns
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_broadcast_fn_receives_all_node_logs():
    """Verify all 4 node names appear in broadcast output on happy path."""
    bridge = _import_bridge()
    received: list[str] = []

    async def _collect(line: str, stream: str = "stdout") -> None:
        received.append(line)

    with (
        patch("backend.engine.generator_node.generate_spec", new=AsyncMock(return_value=GEN_OK_RESULT)),
        patch("backend.engine.validator_node.validate_spec", new=AsyncMock(return_value=COMPILE_OK_RESULT)),
        patch("backend.engine.linear_bridge._run_playwright_spec", new=AsyncMock(return_value=(True, "1 passed"))),
    ):
        await bridge.run_linear_pipeline(
            run_id="test-run-010",
            card=SAMPLE_CARD,
            tenant_id="vpromedia",
            broadcast_fn=_collect,
        )

    combined = "\n".join(received)
    assert "Generate" in combined, "Generate node log missing"
    assert "Validate" in combined, "Validate node log missing"
    assert "Execute" in combined, "Execute node log missing"
    # On success, Analyze is NOT called — verify it's absent
    assert "Analyze" not in combined, "Analyze should not run on success"


# ---------------------------------------------------------------------------
# 11. detect_strict_mode_collision patterns
# ---------------------------------------------------------------------------


def test_detect_collision_standard_violation():
    """Verify strict-mode collision parser catches the standard Playwright pattern."""
    bridge = _import_bridge()
    locator = bridge._detect_strict_mode_collision(PLAYWRIGHT_COLLISION_OUTPUT)
    assert locator == "button"


def test_detect_collision_returns_none_for_generic_error():
    """Non-collision errors return None."""
    bridge = _import_bridge()
    locator = bridge._detect_strict_mode_collision(PLAYWRIGHT_GENERIC_FAILURE_OUTPUT)
    assert locator is None


def test_detect_collision_returns_none_for_empty_output():
    """Empty output returns None without raising."""
    bridge = _import_bridge()
    assert bridge._detect_strict_mode_collision("") is None


# ---------------------------------------------------------------------------
# 12. LinearRunResult dataclass defaults
# ---------------------------------------------------------------------------


def test_linear_run_result_defaults():
    """LinearRunResult has sensible defaults."""
    bridge = _import_bridge()
    result = bridge.LinearRunResult()
    assert result.status == "error"
    assert result.pipeline_status == "PIPELINE_ERROR"
    assert result.ticket_id == "UNKNOWN"
    assert result.spec_path is None
    assert result.analysis == ""
    assert result.compile_attempts == 0
    assert result.elapsed_s == 0.0
    assert result.error == ""


@pytest.mark.anyio
async def test_smart_replay_bypass():
    """Verify that if an accepted test is found and replays successfully, the generation pipeline is bypassed."""
    bridge = _import_bridge()
    
    mock_store = MagicMock()
    mock_store.load.return_value = {"replay_actions": [{"action_type": "click"}]}
    
    mock_engine = MagicMock()
    mock_engine.replay = AsyncMock(return_value={"replay_succeeded": True})
    
    # We patch generator_node to verify it's never called
    mock_generate = AsyncMock()
    
    with patch("backend.storage.accepted_test_store.get_accepted_test_store", return_value=mock_store), \
         patch("backend.engine.replay_engine.ReplayEngine", return_value=mock_engine), \
         patch("backend.engine.generator_node.generate_spec", mock_generate):
         
        result = await bridge._run_pipeline_inner(
            run_id="run-replay-bypass",
            card=SAMPLE_CARD,
            tenant_id="vpromedia",
            ticket_id="QA-170",
            emit=AsyncMock(),
        )
        
        assert result.status == "completed"
        assert result.pipeline_status == "SUCCESS"
        assert result.ticket_id == "QA-170"
        mock_generate.assert_not_called()

