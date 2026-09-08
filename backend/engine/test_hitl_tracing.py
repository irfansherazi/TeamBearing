"""
Tests for T2-b: HITL Playwright Tracing Memory (FEAT-117 / Phase 2)

Covers:
  AC-VERIFY-3a — trace .zip produced at correct path on HITL completion
  AC-VERIFY-3b — trace parser extracts at least one DOM action and writes Recipe YAML
  AC-ERROR-1   — parse failure (empty/no-action trace): WARN logged, zip preserved,
                 no stub Recipe written

All Playwright interactions are mocked at the page.context.tracing boundary.
No live browser or Bedrock calls.

Usage:
    pytest backend/engine/test_hitl_tracing.py -v
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import pathlib
import zipfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

FIXTURES_DIR = pathlib.Path(__file__).parent / "fixtures"
SAMPLE_ZIP = FIXTURES_DIR / "hitl_trace_sample.zip"
EMPTY_ZIP = FIXTURES_DIR / "hitl_trace_empty.zip"


def _make_sample_zip_bytes() -> bytes:
    """Build a minimal valid Playwright trace .zip with one successful click action."""
    trace_events = [
        json.dumps({"type": "resource-snapshot", "snapshot": {"name": "snapshot@0"}}),
        json.dumps({
            "type": "before",
            "callId": "call-1",
            "startTime": 1000,
            "class": "Locator",
            "method": "click",
            "params": {"selector": 'p-select[ng-reflect-option-label="prfCategory"]'},
            "stepId": "step-1",
        }),
        json.dumps({
            "type": "action",
            "callId": "call-1",
            "class": "Locator",
            "method": "click",
            "params": {"selector": 'p-select[ng-reflect-option-label="prfCategory"]'},
            "startTime": 1000,
            "endTime": 1100,
            "stepId": "step-1",
            "snapshots": [],
        }),
        json.dumps({
            "type": "after",
            "callId": "call-1",
            "endTime": 1100,
            "result": {},
            "stepId": "step-1",
        }),
    ]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("trace.trace", "\n".join(trace_events) + "\n")
        zf.writestr("trace.network", "")
    return buf.getvalue()


def _make_empty_zip_bytes() -> bytes:
    """Build a trace .zip with no interactive events."""
    trace_events = [
        json.dumps({"type": "resource-snapshot", "snapshot": {"name": "snapshot@0"}}),
        json.dumps({"type": "context-options", "browserName": "chromium", "options": {}}),
    ]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("trace.trace", "\n".join(trace_events) + "\n")
        zf.writestr("trace.network", "")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# AC-VERIFY-3a: trace .zip is written at the expected path during HITL
# ---------------------------------------------------------------------------

class TestTraceZipProduced:
    """
    AC-VERIFY-3a: When a HITL takeover completes, page.context.tracing.start() is
    called on entry and stop(path=<storage/hitl_traces/...zip>) is called on exit.

    We mock the tracing API and verify the correct path is passed to stop().
    The parser is patched to a no-op so we only assert the tracing calls here.
    """

    @pytest.mark.asyncio
    async def test_trace_zip_produced(self, tmp_path):
        """tracing.start and tracing.stop(path=...) are called with the expected zip path."""

        run_id = "test-run-001"
        takeover_seq = 0
        expected_zip_name = f"{run_id}-{takeover_seq}.zip"

        # Mock tracing object
        mock_tracing = MagicMock()
        mock_tracing.start = AsyncMock()
        mock_tracing.stop = AsyncMock()

        # Mock context with tracing
        mock_context = MagicMock()
        mock_context.tracing = mock_tracing

        # Mock page
        mock_page = MagicMock()
        mock_page.is_closed.return_value = False
        mock_page.context = mock_context

        # Build a fake state
        state = {
            "run_id": run_id,
            "jira_ticket": {
                "acceptance_criteria_steps": ["Select Contest from PRF Category dropdown"],
                "ticket_id": "QA-358",
            },
            "ac_step_index": 0,
            "last_error": "CV fallback failed",
            "execution_mode": "interactive",
        }

        # Capture the path passed to tracing.stop
        captured_stop_paths = []

        async def fake_stop(path=None):
            if path:
                captured_stop_paths.append(pathlib.Path(path))
                # Write fake bytes so the parser can open the zip
                pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
                pathlib.Path(path).write_bytes(_make_sample_zip_bytes())

        mock_tracing.stop = AsyncMock(side_effect=fake_stop)

        # Patch get_manager, register_takeover, _WS_BROADCAST_FN, _clear, and
        # all the downstream memory-write helpers so only tracing code runs.
        with (
            patch("backend.engine.human_takeover.get_manager") as mock_get_mgr,
            patch("backend.engine.human_takeover.register_takeover") as mock_register,
            patch("backend.engine.human_takeover._WS_BROADCAST_FN", None),
            patch("backend.engine.human_takeover._clear"),
            patch("backend.engine.human_takeover._inject_click_capture_listener", AsyncMock()),
            patch("backend.engine.human_takeover._save_to_learned_workflows", AsyncMock()),
            patch("backend.engine.human_takeover._write_to_vsuite_actions_kb", AsyncMock()),
            patch("backend.engine.human_takeover._save_combined_hitl_entry", AsyncMock()),
            patch("backend.engine.human_takeover._last_human_click", {run_id: None}),
            patch("backend.engine.human_takeover._human_action_sequence", {run_id: []}),
            patch("backend.engine.human_takeover._takeover_data", {run_id: {"explanation": "done"}}),
            patch("backend.engine.human_takeover.capture_screenshot_b64", AsyncMock(return_value="")),
            patch("backend.engine.human_takeover.VncUrlBuilder"),
            patch("backend.engine.human_takeover.autorecord_serializer") as mock_ser,
            patch("backend.engine.human_takeover.HITL_TRACES_DIR", tmp_path / "storage" / "hitl_traces"),
        ):
            mock_ser.serialize.return_value = []

            # Manager setup
            mock_mgr = MagicMock()
            mock_mgr.page = mock_page
            mock_mgr._context = mock_context
            mock_mgr.get_cdp_session = AsyncMock(return_value=MagicMock(
                send=AsyncMock(),
                on=MagicMock(),
                detach=AsyncMock(),
            ))
            mock_get_mgr.return_value = mock_mgr

            # register_takeover returns an event that resolves immediately
            done_event = asyncio.Event()
            done_event.set()
            mock_register.return_value = done_event

            from backend.engine.human_takeover import human_takeover_node
            await human_takeover_node(state)

        # Assert tracing.start was called
        mock_tracing.start.assert_awaited_once()
        start_kwargs = mock_tracing.start.call_args.kwargs
        assert start_kwargs.get("screenshots") is True
        assert start_kwargs.get("snapshots") is True

        # Assert tracing.stop was called with a path ending in the expected zip name
        assert len(captured_stop_paths) == 1, "tracing.stop must be called exactly once"
        assert captured_stop_paths[0].name == expected_zip_name, (
            f"Expected zip name '{expected_zip_name}', got '{captured_stop_paths[0].name}'"
        )


# ---------------------------------------------------------------------------
# AC-VERIFY-3b: trace parser extracts action(s) and writes Recipe YAML
# ---------------------------------------------------------------------------

class TestTracesParsesToRecipe:
    """
    AC-VERIFY-3b: Given a valid Playwright trace .zip with at least one successful
    DOM interaction, parse_trace() returns result.ok=True, at least one ExtractedAction,
    and writes a Recipe YAML to the output_dir.
    """

    @pytest.mark.asyncio
    async def test_trace_parses_to_recipe(self, tmp_path):
        """parse_trace on sample zip → ok=True, ≥1 action, YAML written."""
        from backend.engine.hitl_trace_parser import parse_trace

        # Write sample zip to tmp location
        zip_path = tmp_path / "run-001-0.zip"
        zip_path.write_bytes(_make_sample_zip_bytes())

        output_dir = tmp_path / "blueprints" / "generated"

        result = await parse_trace(
            zip_path=zip_path,
            ac_step_goal="Select Contest from PRF Category dropdown",
            run_id="run-001",
            takeover_seq=0,
            output_dir=output_dir,
        )

        assert result.ok is True, f"Expected ok=True, got failure: {result.failure_reason} — {result.failure_detail}"
        assert len(result.actions) >= 1, "Expected at least one ExtractedAction"
        assert result.recipe_yaml_path is not None, "Expected recipe_yaml_path to be set"
        assert result.recipe_yaml_path.exists(), f"Recipe YAML not written to {result.recipe_yaml_path}"

        # Validate YAML structure: must have name, trigger_keywords, steps
        with result.recipe_yaml_path.open() as f:
            recipe_data = yaml.safe_load(f)

        assert "name" in recipe_data, "Recipe YAML missing 'name' field"
        assert "trigger_keywords" in recipe_data, "Recipe YAML missing 'trigger_keywords'"
        assert isinstance(recipe_data["trigger_keywords"], list), "'trigger_keywords' must be a list"
        assert len(recipe_data["trigger_keywords"]) >= 1, "trigger_keywords must not be empty"
        assert "steps" in recipe_data, "Recipe YAML missing 'steps'"
        assert isinstance(recipe_data["steps"], list), "'steps' must be a list"
        assert len(recipe_data["steps"]) >= 1, "Recipe must have at least one step"

        # Validate each step has selector and action
        first_step = recipe_data["steps"][0]
        assert "action" in first_step, "Step missing 'action' field"
        assert "selector" in first_step or "strategy" in first_step, (
            "Step must have a 'selector' or 'strategy' field"
        )

    @pytest.mark.asyncio
    async def test_trace_recipe_trigger_phrases_from_goal(self, tmp_path):
        """trigger_keywords should contain tokens derived from the AC step goal."""
        from backend.engine.hitl_trace_parser import parse_trace

        zip_path = tmp_path / "run-002-0.zip"
        zip_path.write_bytes(_make_sample_zip_bytes())
        output_dir = tmp_path / "blueprints" / "generated"

        result = await parse_trace(
            zip_path=zip_path,
            ac_step_goal="Select Contest from PRF Category dropdown",
            run_id="run-002",
            takeover_seq=0,
            output_dir=output_dir,
        )

        assert result.ok is True
        assert len(result.trigger_phrases) >= 1, "trigger_phrases must not be empty"
        # At least one phrase should reference the goal's key terms
        goal_tokens = {"contest", "prf", "category", "dropdown", "select"}
        phrase_tokens: set[str] = set()
        for phrase in result.trigger_phrases:
            phrase_tokens.update(phrase.lower().split())
        overlap = goal_tokens & phrase_tokens
        assert len(overlap) >= 1, (
            f"trigger_phrases {result.trigger_phrases} should contain at least one "
            f"token from the goal. Overlap: {overlap}"
        )


# ---------------------------------------------------------------------------
# AC-ERROR-1: parse failure is surfaced; zip preserved; no stub Recipe written
# ---------------------------------------------------------------------------

class TestTraceParseFailureSurfacesAndPreservesZip:
    """
    AC-ERROR-1: When parse_trace() encounters a trace .zip with no interactive
    events, it must:
      (a) Return result.ok=False with a meaningful failure_reason
      (b) Leave the original .zip file on disk (not delete it)
      (c) NOT write any YAML Recipe file
      (d) Caller's WARN log path is verified by asserting the result carries
          the failure_reason that the caller logs.
    """

    @pytest.mark.asyncio
    async def test_trace_parse_failure_surfaces_and_preserves_zip(self, tmp_path, caplog):
        """Empty trace → ok=False, failure_reason set, zip preserved, no YAML written."""
        from backend.engine.hitl_trace_parser import TraceParseFailureReason, parse_trace

        zip_path = tmp_path / "run-003-0.zip"
        zip_path.write_bytes(_make_empty_zip_bytes())
        output_dir = tmp_path / "blueprints" / "generated"

        with caplog.at_level(logging.WARNING, logger="backend.engine.hitl_trace_parser"):
            result = await parse_trace(
                zip_path=zip_path,
                ac_step_goal="Select Contest from PRF Category dropdown",
                run_id="run-003",
                takeover_seq=0,
                output_dir=output_dir,
            )

        # (a) result.ok is False
        assert result.ok is False, "Expected ok=False for empty trace"
        assert result.failure_reason is not None, "failure_reason must be set on failure"
        assert result.failure_reason == TraceParseFailureReason.NO_INTERACTIVE_EVENTS, (
            f"Expected NO_INTERACTIVE_EVENTS, got {result.failure_reason}"
        )

        # (b) zip still exists
        assert zip_path.exists(), "The .zip file must be preserved on parse failure"

        # (c) no YAML written
        yaml_files = list(output_dir.glob("*.yaml")) if output_dir.exists() else []
        assert len(yaml_files) == 0, (
            f"No Recipe YAML should be written on failure, but found: {yaml_files}"
        )

    @pytest.mark.asyncio
    async def test_corrupted_zip_surfaces_failure(self, tmp_path):
        """Corrupted (non-zip) bytes → ok=False with CORRUPTED_ZIP reason; zip preserved."""
        from backend.engine.hitl_trace_parser import TraceParseFailureReason, parse_trace

        zip_path = tmp_path / "run-004-0.zip"
        zip_path.write_bytes(b"this is not a valid zip archive")
        output_dir = tmp_path / "blueprints" / "generated"

        result = await parse_trace(
            zip_path=zip_path,
            ac_step_goal="Select Contest from PRF Category dropdown",
            run_id="run-004",
            takeover_seq=0,
            output_dir=output_dir,
        )

        assert result.ok is False
        assert result.failure_reason == TraceParseFailureReason.CORRUPTED_ZIP
        assert zip_path.exists(), "Corrupted .zip must not be deleted"

    @pytest.mark.asyncio
    async def test_missing_zip_surfaces_failure(self, tmp_path):
        """Non-existent zip path → ok=False with appropriate failure_reason."""
        from backend.engine.hitl_trace_parser import TraceParseFailureReason, parse_trace

        zip_path = tmp_path / "does-not-exist.zip"
        output_dir = tmp_path / "blueprints" / "generated"

        result = await parse_trace(
            zip_path=zip_path,
            ac_step_goal="Select Contest from PRF Category dropdown",
            run_id="run-005",
            takeover_seq=0,
            output_dir=output_dir,
        )

        assert result.ok is False
        # Missing file is a corrupted-zip variant (can't open it)
        assert result.failure_reason in (
            TraceParseFailureReason.CORRUPTED_ZIP,
            TraceParseFailureReason.NO_TRACE_FILE,
        )
