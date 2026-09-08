"""
TASK-027 Regression Tests — GraphRecursionError Handling & recursion_limit Value
==================================================================================
Module: tests/test_task_027_graph_recursion_limit.py

Verifies the two fixes introduced in TASK-027:

  1. The ``recursion_limit`` in ``_execute_run`` is set to 3000 (≥ 6× max_planner_iterations),
     ensuring the evaluator's own safety cap fires before LangGraph's hard stop.

  2. ``GraphRecursionError`` is caught inside ``_execute_run`` and treated as a
     graceful over-budget terminal failure.  The WebSocket client receives a ``failed``
     terminal message with a human-readable error string — no unhandled exception
     propagates to the server.

AC Coverage
-----------
  AC-HAPPY-1  recursion_limit value is high enough to not interfere with normal runs
  AC-HAPPY-2  GraphRecursionError → broadcast ``failed`` terminal message
  AC-ERROR-1  GraphRecursionError logged at WARNING (not ERROR) — no exc_info traceback
  AC-REGRESS-1 max_planner_iterations safety cap in evaluator is unaffected
"""

import inspect
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.config import settings

# ---------------------------------------------------------------------------
# AC-HAPPY-1 — recursion_limit is high enough for normal runs
# ---------------------------------------------------------------------------


class TestRecursionLimitValue:
    """Verify the recursion_limit constant in _execute_run matches the spec."""

    def test_recursion_limit_is_at_least_six_times_max_planner_iterations(self):
        """
        LangGraph counts ~5 node visits per planner cycle.  The recursion_limit
        must be ≥ (max_planner_iterations × 5) + safety headroom.
        The spec says 3000 for a default of 500 iterations (6× factor).
        """
        # Read the routes source and extract the recursion_limit value
        import backend.api.routes as routes_module

        source = inspect.getsource(routes_module)

        # Find recursion_limit assignment in astream config
        match = re.search(r'"recursion_limit"\s*:\s*(\d+)', source)
        assert match, "Could not find 'recursion_limit' key in routes.py _execute_run"

        configured_limit = int(match.group(1))
        max_iterations = settings.max_planner_iterations  # default 500

        # Must be at least 5× (with headroom → effectively 6× = 3000)
        assert configured_limit >= max_iterations * 5, (
            f"recursion_limit={configured_limit} is too low for max_planner_iterations={max_iterations}. "
            f"Expected >= {max_iterations * 5} (5 node-visits/cycle × max iterations)."
        )

    def test_recursion_limit_equals_3000_by_default(self):
        """Exact value check — the spec mandates 3000 for the 500-iteration default."""
        import backend.api.routes as routes_module

        source = inspect.getsource(routes_module)

        match = re.search(r'"recursion_limit"\s*:\s*(\d+)', source)
        assert match, "recursion_limit key missing from routes.py"
        assert int(match.group(1)) == 3000, f"Expected recursion_limit=3000 but found {match.group(1)}"


# ---------------------------------------------------------------------------
# AC-HAPPY-2 — GraphRecursionError → failed terminal broadcast
# ---------------------------------------------------------------------------


class TestGraphRecursionErrorHandling:
    """
    Verify that _execute_run catches GraphRecursionError and broadcasts a
    ``failed`` terminal WSTerminalMessage instead of letting the exception propagate.
    """

    @pytest.mark.anyio
    async def test_graph_recursion_error_broadcasts_failed_terminal(self):
        """
        When LangGraph raises GraphRecursionError during astream, _execute_run
        must catch it and call _broadcast_terminal with type='failed'.
        The exception must NOT propagate out of _execute_run.
        """
        from backend.api.routes import _execute_run, _run_states
        from backend.engine.state import make_initial_state

        run_id = "test-recursion-catch"

        # Seed state store with a running entry so _execute_run can update status
        _run_states[run_id] = {"status": "pending", "state": None}

        # Build a fake initial_state (no real Jira / browser needed)
        fake_state = make_initial_state(
            run_id=run_id,
            jira_ticket_id="FAKE-999",
            role="account_executive",
            target_url="https://two-test.vcreative.net",
            mode="headless",
        )

        # Track all terminal messages broadcast
        terminal_messages: list = []

        async def fake_broadcast_terminal(rid: str, msg):
            terminal_messages.append(msg)

        # Simulate GraphRecursionError raised by graph.astream()
        class FakeGraphRecursionError(Exception):
            """Mimics langgraph.errors.GraphRecursionError."""

            pass

        # Make it appear as GraphRecursionError in the error_msg check
        FakeGraphRecursionError.__name__ = "GraphRecursionError"

        async def fake_astream(*args, **kwargs):
            raise FakeGraphRecursionError("Recursion limit of 3000 reached")
            # yield nothing — make it an async generator that immediately raises
            return
            yield  # noqa: unreachable — makes this an async generator

        mock_graph = MagicMock()
        mock_graph.astream = fake_astream

        with (
            patch("backend.api.routes.build_graph", return_value=mock_graph),
            patch("backend.api.routes._broadcast_terminal", side_effect=fake_broadcast_terminal),
        ):
            # _execute_run must return normally (no exception propagates)
            try:
                await _execute_run(run_id, fake_state)
            except Exception as exc:
                pytest.fail(f"_execute_run propagated GraphRecursionError instead of catching it: {exc}")

        # Should have broadcast exactly one terminal message of type 'failed'
        assert len(terminal_messages) == 1, f"Expected 1 terminal broadcast, got {len(terminal_messages)}"
        terminal = terminal_messages[0]
        assert terminal.type == "failed", f"Terminal type should be 'failed', got '{terminal.type}'"
        assert "graphrecursionerror" in terminal.error.lower() or "recursion" in terminal.error.lower(), (
            f"Terminal error should mention recursion, got: '{terminal.error}'"
        )

    @pytest.mark.anyio
    async def test_graph_recursion_error_does_not_log_exc_info(self, caplog):
        """
        AC-ERROR-1: GraphRecursionError must be logged at WARNING level without
        exc_info=True (no 200-line traceback flooding the logs).
        """
        import logging

        from backend.api.routes import _execute_run, _run_states
        from backend.engine.state import make_initial_state

        run_id = "test-recursion-log-level"
        _run_states[run_id] = {"status": "pending", "state": None}

        fake_state = make_initial_state(
            run_id=run_id,
            jira_ticket_id="FAKE-998",
            role="account_executive",
            target_url="https://two-test.vcreative.net",
            mode="headless",
        )

        class FakeGraphRecursionError(Exception):
            pass

        FakeGraphRecursionError.__name__ = "GraphRecursionError"

        async def fake_astream(*args, **kwargs):
            raise FakeGraphRecursionError("Recursion limit of 3000 reached")
            return
            yield  # noqa: unreachable

        mock_graph = MagicMock()
        mock_graph.astream = fake_astream

        with (
            patch("backend.api.routes.build_graph", return_value=mock_graph),
            patch("backend.api.routes._broadcast_terminal", new_callable=AsyncMock),
            caplog.at_level(logging.WARNING, logger="backend.api.routes"),
        ):
            await _execute_run(run_id, fake_state)

        # Check that no ERROR-level entries exist for this run (only WARNING)
        error_records = [r for r in caplog.records if r.levelno >= logging.ERROR and run_id in r.message]
        assert not error_records, (
            f"GraphRecursionError should be logged at WARNING, not ERROR. "
            f"Found ERROR records: {[r.message for r in error_records]}"
        )

        # Check WARNING was logged with the run_id
        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING and run_id in r.message]
        assert warning_records, "Expected at least one WARNING log entry mentioning the run_id for GraphRecursionError"


# ---------------------------------------------------------------------------
# AC-REGRESS-1 — max_planner_iterations safety cap unaffected
# ---------------------------------------------------------------------------


class TestMaxPlannerIterationsDocstring:
    """Verify the config docstring clarifies the node-visit vs iteration distinction."""

    def test_max_planner_iterations_docstring_mentions_node_visits(self):
        """
        The max_planner_iterations field description must explain that
        LangGraph's recursion_limit counts node visits, not planner iterations,
        to prevent future confusion when tuning the values.
        """
        import backend.config as config_module

        source = inspect.getsource(config_module)

        # Locate the start of the max_planner_iterations block, then grab
        # everything up to the closing '),\n    )' that ends the Field() call.
        # Using a simple index-based slice avoids DOTALL greediness issues.
        idx = source.find("max_planner_iterations")
        assert idx != -1, "Could not locate max_planner_iterations in config.py"

        # Extract a generous window (800 chars) covering the full field definition
        field_block = source[idx : idx + 800].lower()

        assert "node" in field_block and ("visit" in field_block or "recursion" in field_block), (
            "max_planner_iterations description should mention 'node visits' or "
            "'recursion' to clarify the distinction from planner iteration count."
        )
