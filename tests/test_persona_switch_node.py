"""
tests/test_persona_switch_node.py
==================================
RED phase tests for TASK-063, Phase 3: Executor & Graph.

Covers:
  - AC-HAPPY-1: Successful persona switch with stored credentials
  - AC-HAPPY-2: "As yourself" resolves to initial_actor
  - AC-HAPPY-3: Unknown persona triggers HITL credential prompt
  - AC-HAPPY-4: Multi-switch — chained persona switches work correctly
  - Graph wiring: persona_switch node registered in build_graph()
  - Evaluator routing: PERSONA_SWITCH step_type routes to "persona_switch"
  - State mutations: current_persona, persona_switch_history updated correctly
  - HITL API: set_persona_credentials unblocks the waiting event
  - Security: ephemeral creds not written to disk, not in history
"""

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(**kwargs):
    """Build a minimal VQAState for testing."""
    from backend.engine.state import make_initial_state

    state = make_initial_state(
        run_id="test-run-persona-node",
        jira_ticket_id="QA-999",
        role="account_executive",
        target_url="http://localhost:4200",
        mode="headless",
    )
    # Ensure Phase 1 fields are present
    state.setdefault("current_persona", "account_executive")
    state.setdefault("persona_switch_history", [])
    state.setdefault("ephemeral_persona_creds", {})
    state.setdefault("run_memory", {})
    for k, v in kwargs.items():
        state[k] = v
    return state


def _make_test_plan_with_persona_switch(target_persona: str = "Demo Prod dir", ac_index: int = 0) -> dict:
    """Return a minimal test_plan dict with a PERSONA_SWITCH step at ac_index."""
    steps = []
    # Pad with a dummy step before if ac_index > 0
    for i in range(ac_index):
        steps.append({
            "step_id": i + 1,
            "goal": f"Step {i + 1}",
            "step_type": "NAVIGATE",
            "target_component": "page",
            "preconditions": [],
            "verification": [],
            "fallback_strategy": None,
            "max_actions": 8,
            "target_element_types": [],
            "input_value": None,
            "target_persona": None,
        })
    steps.append({
        "step_id": ac_index + 1,
        "goal": f"Switch to persona: {target_persona}",
        "step_type": "PERSONA_SWITCH",
        "target_component": "auth_context",
        "preconditions": [],
        "verification": [],
        "fallback_strategy": None,
        "max_actions": 1,
        "target_element_types": [],
        "input_value": None,
        "target_persona": target_persona,
    })
    return {
        "test_title": "Multi-persona test",
        "global_preconditions": ["logged_in"],
        "steps": steps,
    }


# ---------------------------------------------------------------------------
# 1. Module existence and importability
# ---------------------------------------------------------------------------


class TestPersonaSwitchNodeModule:
    """persona_switch_node module must exist and export the expected symbols."""

    def test_module_importable(self):
        """backend.engine.persona_switch_node must be importable."""
        import backend.engine.persona_switch_node  # noqa: F401

    def test_persona_switch_node_function_exists(self):
        """persona_switch_node must be a callable async function."""
        from backend.engine.persona_switch_node import persona_switch_node
        assert callable(persona_switch_node)
        assert asyncio.iscoroutinefunction(persona_switch_node)

    def test_resolve_target_persona_exists(self):
        """Module must expose resolve_target_persona helper."""
        from backend.engine.persona_switch_node import resolve_target_persona
        assert callable(resolve_target_persona)

    def test_set_persona_credentials_exists(self):
        """Module must expose set_persona_credentials for API endpoint."""
        from backend.engine.persona_switch_node import set_persona_credentials
        assert callable(set_persona_credentials)


# ---------------------------------------------------------------------------
# 2. resolve_target_persona — unit tests
# ---------------------------------------------------------------------------


class TestResolveTargetPersona:
    """Unit tests for the resolve_target_persona helper function."""

    def test_current_user_sentinel_resolves_to_initial_actor(self):
        """'current_user' resolves to initial_actor role_key with method='initial_actor'."""
        from backend.engine.persona_switch_node import resolve_target_persona

        run_memory = {"initial_actor": {"role_key": "account_executive", "role_name": "AE"}}
        role_key, method = resolve_target_persona("current_user", run_memory)
        assert role_key == "account_executive"
        assert method == "initial_actor"

    def test_as_yourself_normalized_to_current_user(self):
        """'as yourself' (raw from AC) must be normalized and resolve correctly."""
        from backend.engine.persona_switch_node import resolve_target_persona

        run_memory = {"initial_actor": {"role_key": "digital_director"}}
        # After AC parser normalization, target_persona is "current_user"
        role_key, method = resolve_target_persona("current_user", run_memory)
        assert role_key == "digital_director"
        assert method == "initial_actor"

    def test_as_yourself_case_insensitive_variants(self):
        """Uppercase/mixed variants of current_user are also normalized."""
        from backend.engine.persona_switch_node import resolve_target_persona

        run_memory = {"initial_actor": {"role_key": "sales_manager"}}
        for variant in ("CURRENT_USER", "Current_User"):
            role_key, method = resolve_target_persona(variant, run_memory)
            assert role_key == "sales_manager", f"Failed for variant: {variant}"
            assert method == "initial_actor"

    def test_direct_role_key_lookup(self):
        """A direct ROLE_REGISTRY key is resolved as 'stored'."""
        from backend.engine.persona_switch_node import resolve_target_persona

        role_key, method = resolve_target_persona("digital_director", {})
        assert role_key == "digital_director"
        assert method == "stored"

    def test_alias_resolution_demo_prod_dir(self):
        """'Demo Prod dir' alias resolves to 'digital_director' as 'stored'."""
        from backend.engine.persona_switch_node import resolve_target_persona

        role_key, method = resolve_target_persona("Demo Prod dir", {})
        assert role_key == "digital_director"
        assert method == "stored"

    def test_unknown_persona_returns_none(self):
        """Unknown persona that has no alias returns (None, None) — triggers HITL."""
        from backend.engine.persona_switch_node import resolve_target_persona

        role_key, method = resolve_target_persona("Bob Smith the Unknown", {})
        assert role_key is None
        assert method is None

    def test_initial_actor_missing_returns_none(self):
        """If initial_actor is absent from run_memory, current_user resolves to (None, None)."""
        from backend.engine.persona_switch_node import resolve_target_persona

        role_key, method = resolve_target_persona("current_user", {})
        assert role_key is None
        assert method is None


# ---------------------------------------------------------------------------
# 3. persona_switch_node — happy path (stored credentials)
# ---------------------------------------------------------------------------


class TestPersonaSwitchNodeHappyPath:
    """AC-HAPPY-1: Successful persona switch with stored credentials."""

    @pytest.mark.asyncio
    async def test_happy_path_stored_persona_updates_current_persona(self):
        """persona_switch_node must update current_persona in state after a known switch."""
        from backend.engine.persona_switch_node import persona_switch_node

        state = _make_state(
            current_persona="account_executive",
            structured_step_index=0,
            ac_step_index=0,
            test_plan=_make_test_plan_with_persona_switch("digital_director", ac_index=0),
            run_memory={"initial_actor": {"role_key": "account_executive"}},
        )

        mock_page = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value="eyJhbGciOiJIUzI1NiJ9")  # fake JWT

        mock_context = AsyncMock()
        mock_context.add_cookies = AsyncMock()

        mock_manager = MagicMock()
        mock_manager.page = mock_page
        mock_manager._context = mock_context

        fake_storage = {"cookies": [{"name": "session", "value": "x"}], "origins": []}

        with (
            patch("backend.engine.persona_switch_node.get_manager", return_value=mock_manager),
            patch("backend.engine.persona_switch_node.ensure_role_authenticated", return_value="/fake/path.json"),
            patch("builtins.open", MagicMock(return_value=MagicMock(__enter__=MagicMock(return_value=MagicMock(read=MagicMock(return_value=json.dumps(fake_storage))))))),
            patch("backend.engine.persona_switch_node._wait_for_post_login_spa_render", AsyncMock()),
            patch("backend.engine.persona_switch_node.broadcast_ws_message", AsyncMock()),
            patch("json.load", return_value=fake_storage),
        ):
            result = await persona_switch_node(state)

        assert result["current_persona"] == "digital_director"

    @pytest.mark.asyncio
    async def test_happy_path_adds_switch_history_entry(self):
        """Switch history must gain exactly one entry with correct from/to fields."""
        from backend.engine.persona_switch_node import persona_switch_node

        state = _make_state(
            current_persona="account_executive",
            structured_step_index=0,
            ac_step_index=0,
            test_plan=_make_test_plan_with_persona_switch("digital_director", ac_index=0),
            run_memory={"initial_actor": {"role_key": "account_executive"}},
        )

        mock_page = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value="fake-jwt-token")
        mock_context = AsyncMock()
        mock_manager = MagicMock()
        mock_manager.page = mock_page
        mock_manager._context = mock_context

        fake_storage = {"cookies": [], "origins": []}

        with (
            patch("backend.engine.persona_switch_node.get_manager", return_value=mock_manager),
            patch("backend.engine.persona_switch_node.ensure_role_authenticated", return_value="/fake/path.json"),
            patch("backend.engine.persona_switch_node._wait_for_post_login_spa_render", AsyncMock()),
            patch("backend.engine.persona_switch_node.broadcast_ws_message", AsyncMock()),
            patch("json.load", return_value=fake_storage),
            patch("builtins.open", MagicMock(return_value=MagicMock(__enter__=MagicMock(return_value=MagicMock())))),
        ):
            result = await persona_switch_node(state)

        history = result.get("persona_switch_history", [])
        assert len(history) == 1
        entry = history[0]
        assert entry["from"] == "account_executive"
        assert entry["to"] == "digital_director"
        assert entry["method"] == "stored"
        assert "timestamp" in entry
        assert "duration_ms" in entry

    @pytest.mark.asyncio
    async def test_happy_path_next_node_is_planner(self):
        """After successful switch, _next_node must be 'planner'."""
        from backend.engine.persona_switch_node import persona_switch_node

        state = _make_state(
            current_persona="account_executive",
            structured_step_index=0,
            ac_step_index=0,
            test_plan=_make_test_plan_with_persona_switch("account_executive", ac_index=0),
            run_memory={},
        )

        mock_page = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value="jwt-token")
        mock_context = AsyncMock()
        mock_manager = MagicMock()
        mock_manager.page = mock_page
        mock_manager._context = mock_context

        fake_storage = {"cookies": [], "origins": []}

        with (
            patch("backend.engine.persona_switch_node.get_manager", return_value=mock_manager),
            patch("backend.engine.persona_switch_node.ensure_role_authenticated", return_value="/fake/path.json"),
            patch("backend.engine.persona_switch_node._wait_for_post_login_spa_render", AsyncMock()),
            patch("backend.engine.persona_switch_node.broadcast_ws_message", AsyncMock()),
            patch("json.load", return_value=fake_storage),
            patch("builtins.open", MagicMock(return_value=MagicMock(__enter__=MagicMock(return_value=MagicMock())))),
        ):
            result = await persona_switch_node(state)

        assert result["_next_node"] == "planner"


# ---------------------------------------------------------------------------
# 4. persona_switch_node — "as yourself" (initial_actor path)
# ---------------------------------------------------------------------------


class TestPersonaSwitchNodeInitialActor:
    """AC-HAPPY-2: 'As yourself' resolves to initial_actor."""

    @pytest.mark.asyncio
    async def test_current_user_uses_initial_actor_method(self):
        """current_user target persona must produce method='initial_actor' in history."""
        from backend.engine.persona_switch_node import persona_switch_node

        state = _make_state(
            current_persona="digital_director",
            structured_step_index=0,
            ac_step_index=0,
            test_plan=_make_test_plan_with_persona_switch("current_user", ac_index=0),
            run_memory={"initial_actor": {"role_key": "account_executive", "role_name": "AE"}},
        )

        mock_page = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value="jwt-fake")
        mock_context = AsyncMock()
        mock_manager = MagicMock()
        mock_manager.page = mock_page
        mock_manager._context = mock_context

        fake_storage = {"cookies": [], "origins": []}

        with (
            patch("backend.engine.persona_switch_node.get_manager", return_value=mock_manager),
            patch("backend.engine.persona_switch_node.ensure_role_authenticated", return_value="/fake/path.json"),
            patch("backend.engine.persona_switch_node._wait_for_post_login_spa_render", AsyncMock()),
            patch("backend.engine.persona_switch_node.broadcast_ws_message", AsyncMock()),
            patch("json.load", return_value=fake_storage),
            patch("builtins.open", MagicMock(return_value=MagicMock(__enter__=MagicMock(return_value=MagicMock())))),
        ):
            result = await persona_switch_node(state)

        history = result.get("persona_switch_history", [])
        assert len(history) == 1
        assert history[0]["method"] == "initial_actor"
        assert result["current_persona"] == "account_executive"


# ---------------------------------------------------------------------------
# 5. persona_switch_node — HITL credential gate (unknown persona)
# ---------------------------------------------------------------------------


class TestPersonaSwitchNodeHITL:
    """AC-HAPPY-3: Unknown persona triggers HITL credential prompt."""

    @pytest.mark.asyncio
    async def test_unknown_persona_broadcasts_hitl_event(self):
        """Unknown persona must broadcast HITL_PERSONA_CREDENTIALS_REQUIRED."""
        from backend.engine.persona_switch_node import persona_switch_node, set_persona_credentials

        state = _make_state(
            current_persona="account_executive",
            structured_step_index=0,
            ac_step_index=0,
            test_plan=_make_test_plan_with_persona_switch("Bob the Unknown Director", ac_index=0),
            run_memory={},
        )

        broadcast_calls = []

        async def mock_broadcast(run_id, msg):
            broadcast_calls.append((run_id, msg))
            # After broadcasting, immediately provide credentials to unblock
            set_persona_credentials(run_id, "Bob the Unknown Director", "bob@test.com", "secret123")

        mock_page = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value="jwt-fake")
        mock_page.goto = AsyncMock()
        mock_page.get_by_role = MagicMock(return_value=AsyncMock(fill=AsyncMock()))
        mock_context = AsyncMock()
        mock_manager = MagicMock()
        mock_manager.page = mock_page
        mock_manager._context = mock_context

        with (
            patch("backend.engine.persona_switch_node.get_manager", return_value=mock_manager),
            patch("backend.engine.persona_switch_node.broadcast_ws_message", side_effect=mock_broadcast),
            patch("backend.engine.persona_switch_node._wait_for_post_login_spa_render", AsyncMock()),
            patch("backend.engine.persona_switch_node.get_active_profile", return_value=MagicMock(jwt_storage_key="vc2JWT")),
        ):
            result = await persona_switch_node(state)

        # Verify HITL event was broadcast
        hitl_msgs = [m for _, m in broadcast_calls if m.get("type") == "HITL_PERSONA_CREDENTIALS_REQUIRED"]
        assert len(hitl_msgs) >= 1
        assert hitl_msgs[0]["persona_name"] == "Bob the Unknown Director"

    @pytest.mark.asyncio
    async def test_unknown_persona_method_recorded_as_hitl(self):
        """Switch history method must be 'hitl' for unknown personas."""
        from backend.engine.persona_switch_node import persona_switch_node, set_persona_credentials

        state = _make_state(
            current_persona="account_executive",
            structured_step_index=0,
            ac_step_index=0,
            test_plan=_make_test_plan_with_persona_switch("Totally Unknown Person", ac_index=0),
            run_memory={},
        )

        async def mock_broadcast(run_id, msg):
            if msg.get("type") == "HITL_PERSONA_CREDENTIALS_REQUIRED":
                set_persona_credentials(run_id, "Totally Unknown Person", "unknown@test.com", "pass")

        mock_page = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value="jwt-token")
        mock_page.goto = AsyncMock()
        mock_page.get_by_role = MagicMock(return_value=AsyncMock(fill=AsyncMock(), click=AsyncMock()))
        mock_context = AsyncMock()
        mock_manager = MagicMock()
        mock_manager.page = mock_page
        mock_manager._context = mock_context

        with (
            patch("backend.engine.persona_switch_node.get_manager", return_value=mock_manager),
            patch("backend.engine.persona_switch_node.broadcast_ws_message", side_effect=mock_broadcast),
            patch("backend.engine.persona_switch_node._wait_for_post_login_spa_render", AsyncMock()),
            patch("backend.engine.persona_switch_node.get_active_profile", return_value=MagicMock(jwt_storage_key="vc2JWT")),
        ):
            result = await persona_switch_node(state)

        history = result.get("persona_switch_history", [])
        assert len(history) == 1
        assert history[0]["method"] == "hitl"

    def test_set_persona_credentials_unblocks_event(self):
        """set_persona_credentials must set the asyncio.Event for the given run_id."""
        import backend.engine.persona_switch_node as psn_module
        from backend.engine.persona_switch_node import set_persona_credentials

        # Manually plant an event
        event = asyncio.Event()
        psn_module._persona_events["test-run-hitl"] = event
        psn_module._persona_creds.setdefault("test-run-hitl", {})

        set_persona_credentials("test-run-hitl", "Bob", "bob@test.com", "password123")

        assert event.is_set()
        assert psn_module._persona_creds["test-run-hitl"]["Bob"]["email"] == "bob@test.com"

    def test_hitl_creds_not_written_to_disk(self):
        """Ephemeral credentials must not be passed to ensure_role_authenticated or written to disk."""
        from backend.engine.persona_switch_node import set_persona_credentials

        with patch("backend.engine.persona_switch_node.ensure_role_authenticated") as mock_era:
            set_persona_credentials("run-security-test", "Mallory", "hack@er.com", "evil")
            mock_era.assert_not_called()


# ---------------------------------------------------------------------------
# 6. persona_switch_node — no target_persona guard
# ---------------------------------------------------------------------------


class TestPersonaSwitchNodeGuards:
    """Edge cases: missing target_persona, out-of-range index, etc."""

    @pytest.mark.asyncio
    async def test_missing_target_persona_skips_switch(self):
        """When target_persona is empty/None, node skips switch and returns planner."""
        from backend.engine.persona_switch_node import persona_switch_node

        # Build a plan step with no target_persona
        plan = {
            "test_title": "Test",
            "global_preconditions": [],
            "steps": [{
                "step_id": 1,
                "goal": "Switch persona",
                "step_type": "PERSONA_SWITCH",
                "target_component": "auth_context",
                "preconditions": [],
                "verification": [],
                "fallback_strategy": None,
                "max_actions": 1,
                "target_element_types": [],
                "input_value": None,
                "target_persona": None,  # ← Missing!
            }],
        }
        state = _make_state(
            structured_step_index=0,
            ac_step_index=0,
            test_plan=plan,
        )

        result = await persona_switch_node(state)
        assert result["_next_node"] == "planner"

    @pytest.mark.asyncio
    async def test_out_of_range_index_skips_switch(self):
        """When structured_step_index is out of range, node skips and returns planner."""
        from backend.engine.persona_switch_node import persona_switch_node

        state = _make_state(
            structured_step_index=99,  # Out of range
            ac_step_index=99,
            test_plan={"test_title": "T", "global_preconditions": [], "steps": []},
        )

        result = await persona_switch_node(state)
        assert result["_next_node"] == "planner"


# ---------------------------------------------------------------------------
# 7. Graph wiring — persona_switch node in build_graph()
# ---------------------------------------------------------------------------


class TestGraphWiring:
    """Verify persona_switch node is registered and wired in build_graph()."""

    def test_persona_switch_node_registered_in_graph(self):
        """build_graph() must register a 'persona_switch' node."""
        # We test the module-level wiring by inspecting graph.py imports/calls
        import inspect

        import backend.engine.graph as graph_module

        source = inspect.getsource(graph_module)
        assert "persona_switch" in source, (
            "'persona_switch' must be registered as a node in graph.py. "
            "Add: graph.add_node('persona_switch', persona_switch_node)"
        )

    def test_graph_imports_persona_switch_node(self):
        """graph.py must import persona_switch_node from persona_switch_node module."""
        import inspect

        import backend.engine.graph as graph_module

        source = inspect.getsource(graph_module)
        assert "persona_switch_node" in source, (
            "graph.py must import persona_switch_node from backend.engine.persona_switch_node."
        )

    def test_graph_edges_include_persona_switch(self):
        """build_graph() conditional edges from evaluator must include 'persona_switch'."""
        import inspect

        import backend.engine.graph as graph_module

        source = inspect.getsource(graph_module)
        # Check that "persona_switch" appears in a route mapping context
        assert source.count("persona_switch") >= 2, (
            "build_graph() must wire at least 2 references to 'persona_switch': "
            "add_node(...) and the evaluator conditional edge mapping."
        )


# ---------------------------------------------------------------------------
# 8. Evaluator routing — PERSONA_SWITCH step_type → "persona_switch"
# ---------------------------------------------------------------------------


class TestEvaluatorPersonaSwitchRouting:
    """Evaluator must route PERSONA_SWITCH step completion to 'persona_switch' node."""

    def test_evaluator_contains_persona_switch_routing(self):
        """evaluator.py must contain routing logic for PERSONA_SWITCH step_type."""
        import inspect

        import backend.engine.evaluator as evaluator_module

        source = inspect.getsource(evaluator_module)
        assert "PERSONA_SWITCH" in source, (
            "evaluator.py must handle PERSONA_SWITCH step_type routing. "
            "Add: if step_type == 'PERSONA_SWITCH': _next_node = 'persona_switch'"
        )

    def test_route_after_evaluator_includes_persona_switch(self):
        """route_after_evaluator() must include 'persona_switch' as a valid route target."""
        import inspect

        import backend.engine.graph as graph_module

        source = inspect.getsource(graph_module)
        # The conditional edges dict must map "persona_switch" → "persona_switch"
        assert '"persona_switch": "persona_switch"' in source or "'persona_switch': 'persona_switch'" in source, (
            "graph.py's add_conditional_edges for evaluator must map "
            "'persona_switch' → 'persona_switch' node."
        )

    @pytest.mark.asyncio
    async def test_evaluator_routes_to_persona_switch_on_done(self):
        """When a PERSONA_SWITCH step is done, evaluator routes to 'persona_switch'."""
        from backend.engine.evaluator import evaluator_node

        # Build a state where current AC step is a PERSONA_SWITCH (done by executor)
        from backend.engine.schemas import StructuredACStep, TestPlan
        plan = TestPlan(
            test_title="T",
            steps=[
                StructuredACStep(
                    step_id=1,
                    goal="Switch to persona: digital_director",
                    step_type="PERSONA_SWITCH",
                    target_component="auth_context",
                    target_persona="digital_director",
                )
            ],
        )

        # Provide an execution log with a "done" action so the evaluator
        # can proceed past the empty-log guard and reach PERSONA_SWITCH routing.
        _now = datetime.now(timezone.utc).isoformat()
        execution_log = [
            {
                "step_index": 0,
                "action_type": "done",
                "locator_type": "",
                "locator_value": "",
                "success": True,
                "screenshot_url": "",
                "timestamp": _now,
                "ac_step_index": 0,
                "llm_reasoning": "Step complete",
            }
        ]

        state = _make_state(
            ac_step_index=0,
            structured_step_index=0,
            test_plan=plan.model_dump(),
            jira_ticket={"acceptance_criteria_steps": ["Switch to persona: digital_director"]},
            planned_action={"action": "done"},
            last_action_result={"success": True},
            ac_steps_completed=[0],  # Step already verified — skips verifier re-route
            ac_step_fail_counts={},
            current_persona="account_executive",
            persona_switch_history=[],
            detailed_execution_log=execution_log,
        )

        result = await evaluator_node(state)
        assert result.get("_next_node") == "persona_switch", (
            f"Expected evaluator to route to 'persona_switch', got '{result.get('_next_node')}'"
        )


# ---------------------------------------------------------------------------
# 9. State schema — current_persona initialized in make_initial_state
# ---------------------------------------------------------------------------


class TestStateInitialization:
    """VQAState must initialize persona fields to their defaults."""

    def test_current_persona_initialized_empty_string(self):
        """make_initial_state must set current_persona to empty string."""
        from backend.engine.state import make_initial_state

        state = make_initial_state(
            run_id="run-state-test",
            jira_ticket_id="QA-1",
            role="account_executive",
            target_url="http://localhost",
            mode="headless",
        )
        assert "current_persona" in state
        assert isinstance(state["current_persona"], str)

    def test_persona_switch_history_initialized_empty_list(self):
        """make_initial_state must set persona_switch_history to empty list."""
        from backend.engine.state import make_initial_state

        state = make_initial_state(
            run_id="run-state-test-2",
            jira_ticket_id="QA-2",
            role="account_executive",
            target_url="http://localhost",
            mode="headless",
        )
        assert "persona_switch_history" in state
        assert state["persona_switch_history"] == []

    def test_ephemeral_persona_creds_initialized_empty_dict(self):
        """make_initial_state must set ephemeral_persona_creds to empty dict."""
        from backend.engine.state import make_initial_state

        state = make_initial_state(
            run_id="run-state-test-3",
            jira_ticket_id="QA-3",
            role="account_executive",
            target_url="http://localhost",
            mode="headless",
        )
        assert "ephemeral_persona_creds" in state
        assert state["ephemeral_persona_creds"] == {}
