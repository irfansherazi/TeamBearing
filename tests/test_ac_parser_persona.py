"""
tests/test_ac_parser_persona.py
================================
RED phase tests for TASK-063, Phase 2: AC Parser Detection.

Covers:
  - AC-ENTRY-1: AC parser detects persona-switch directives and emits
    PERSONA_SWITCH steps with correct target_persona.
  - AC-ENTRY-2: Parser handles aliases and fuzzy matches correctly.
  - Prompt-level: BDD_NORMALIZER_PROMPT and JSON_COMPILER_PROMPT contain
    persona-switch instructions and the PERSONA_SWITCH step type hint.
  - Error-hint: Stage 2 retry hint message mentions "PERSONA_SWITCH".
  - End-to-end: ac_parser_node emits PERSONA_SWITCH steps when given
    persona-directive AC text (via mocked LLM responses).
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(**kwargs):
    """Build a minimal VQAState for testing."""
    from backend.engine.state import make_initial_state

    state = make_initial_state(
        run_id="test-run-persona",
        jira_ticket_id="QA-999",
        role="account_executive",
        target_url="http://localhost:4200",
        mode="headless",
    )
    for k, v in kwargs.items():
        state[k] = v
    return state


def _make_step_json(step_id: int, step_type: str, goal: str, target_persona: str | None = None) -> dict:
    """Return a minimal step JSON dict compatible with StructuredACStep."""
    step = {
        "step_id": step_id,
        "goal": goal,
        "step_type": step_type,
        "target_component": "auth_context" if step_type == "PERSONA_SWITCH" else "page",
        "preconditions": [],
        "verification": [{"type": "element_visible", "selector_hint": "body"}],
        "fallback_strategy": None,
        "max_actions": 8,
        "target_element_types": [],
        "input_value": None,
        "target_persona": target_persona,
    }
    return step


def _make_test_plan_json(*steps: dict) -> str:
    """Return a minimal TestPlan JSON with the given steps."""
    return json.dumps(
        {
            "test_title": "Persona Switch Test",
            "global_preconditions": ["logged_in"],
            "steps": list(steps),
        }
    )


# ---------------------------------------------------------------------------
# 1. Prompt-level tests: BDD_NORMALIZER_PROMPT
# ---------------------------------------------------------------------------


class TestBDDNormalizerPromptPersonaSupport:
    """BDD_NORMALIZER_PROMPT must include persona-switch detection rules."""

    def test_bdd_normalizer_prompt_mentions_persona_switch(self):
        """BDD_NORMALIZER_PROMPT must contain 'PERSONA_SWITCH' or persona-switch guidance."""
        from backend.engine.prompts import BDD_NORMALIZER_PROMPT

        lower = BDD_NORMALIZER_PROMPT.lower()
        assert "persona" in lower or "persona_switch" in lower, (
            "BDD_NORMALIZER_PROMPT must contain persona-switch detection guidance. "
            "Add a rule explaining how to emit PERSONA_SWITCH steps."
        )

    def test_bdd_normalizer_prompt_mentions_as_yourself(self):
        """BDD_NORMALIZER_PROMPT must mention 'as yourself' as a detectable directive."""
        from backend.engine.prompts import BDD_NORMALIZER_PROMPT

        lower = BDD_NORMALIZER_PROMPT.lower()
        assert "as yourself" in lower or "yourself" in lower, (
            "BDD_NORMALIZER_PROMPT must recognize 'as yourself' as a persona-switch directive. "
            "Add a rule or example for 'as yourself' → PERSONA_SWITCH."
        )

    def test_bdd_normalizer_prompt_explains_persona_directive_syntax(self):
        """BDD_NORMALIZER_PROMPT should explain 'as [Role]' / 'as [Name]' pattern."""
        from backend.engine.prompts import BDD_NORMALIZER_PROMPT

        lower = BDD_NORMALIZER_PROMPT.lower()
        # Must mention the AC pattern "as [role]" / "as [name]" / persona switching
        assert "as [role]" in lower or "as [name]" in lower or "persona switch" in lower or (
            "as " in lower and "switch" in lower
        ), (
            "BDD_NORMALIZER_PROMPT must explain the 'as [Role]' / 'as [Name]' pattern "
            "for persona-switch detection."
        )


# ---------------------------------------------------------------------------
# 2. Prompt-level tests: JSON_COMPILER_PROMPT
# ---------------------------------------------------------------------------


class TestJSONCompilerPromptPersonaSupport:
    """JSON_COMPILER_PROMPT must include PERSONA_SWITCH step type documentation."""

    def test_json_compiler_prompt_mentions_persona_switch_step_type(self):
        """JSON_COMPILER_PROMPT STEP TYPE GUIDE must include PERSONA_SWITCH."""
        from backend.engine.prompts import JSON_COMPILER_PROMPT

        assert "PERSONA_SWITCH" in JSON_COMPILER_PROMPT, (
            "JSON_COMPILER_PROMPT must include 'PERSONA_SWITCH' in the STEP TYPE GUIDE. "
            "Add: '- Switching to a different user persona (log out + re-auth) -> \"PERSONA_SWITCH\"'"
        )

    def test_json_compiler_prompt_mentions_target_persona_field(self):
        """JSON_COMPILER_PROMPT must instruct the LLM to populate target_persona."""
        from backend.engine.prompts import JSON_COMPILER_PROMPT

        assert "target_persona" in JSON_COMPILER_PROMPT, (
            "JSON_COMPILER_PROMPT must mention 'target_persona' field so the LLM populates it. "
            "Add: 'Set target_persona to the persona name exactly as written in the AC text.'"
        )

    def test_json_compiler_prompt_goal_format_for_persona_switch(self):
        """JSON_COMPILER_PROMPT should specify the goal format for PERSONA_SWITCH steps."""
        from backend.engine.prompts import JSON_COMPILER_PROMPT

        lower = JSON_COMPILER_PROMPT.lower()
        assert "switch to persona" in lower or "persona:" in lower, (
            "JSON_COMPILER_PROMPT should specify goal format for PERSONA_SWITCH steps, "
            "e.g. 'Switch to persona: <name>'."
        )

    def test_json_compiler_step_type_list_includes_persona_switch(self):
        """The step_type list in the error hint must include 'persona_switch'."""
        from backend.engine.prompts import JSON_COMPILER_PROMPT

        lower = JSON_COMPILER_PROMPT.lower()
        # Check either for the step_type itself or the hint comment
        assert "persona_switch" in lower, (
            "JSON_COMPILER_PROMPT must include 'PERSONA_SWITCH' (or 'persona_switch') "
            "in the allowed step_type list so Stage 2 retries include it."
        )


# ---------------------------------------------------------------------------
# 3. Stage 2 error hint includes PERSONA_SWITCH (AC parser retry logic)
# ---------------------------------------------------------------------------


class TestStage2ErrorHintIncludesPersonaSwitch:
    """
    FEAT-114: Stage 2 now uses Instructor (boto3) for deterministic JSON output.
    The old HumanMessage retry loop is replaced by Instructor's internal retry mechanism.
    This class verifies that Stage 2 uses the correct Instructor integration.
    """

    @pytest.mark.anyio
    async def test_stage2_uses_instructor_with_correct_model(self):
        """
        FEAT-114: _stage_2_compile must call instructor_client.messages.create
        (not _get_parser_llm) and use settings.bedrock_model_id_parser.
        """
        from unittest.mock import MagicMock, patch

        from backend.engine.ac_parser import _stage_2_compile
        from backend.engine.schemas import TestPlan

        # Build a mock plan to return
        valid_plan = TestPlan.model_validate(json.loads(_make_test_plan_json(
            _make_step_json(1, "NAVIGATE", "Navigate to app"),
            _make_step_json(2, "PERSONA_SWITCH", "Switch to persona: Demo Prod dir", "Demo Prod dir"),
        )))

        mock_instructor_client = MagicMock()
        mock_instructor_client.messages.create.return_value = valid_plan

        with (
            patch("backend.engine.ac_parser.boto3") as mock_boto3,
            patch("backend.engine.ac_parser.instructor") as mock_instructor_module,
            patch("backend.engine.ac_parser.get_run_metrics"),
        ):
            mock_boto3.client.return_value = MagicMock()
            mock_instructor_module.from_bedrock.return_value = mock_instructor_client
            mock_instructor_module.Mode.MD_JSON = "MD_JSON"

            result = await _stage_2_compile(
                "Given I am a user\nWhen I do something\nThen it works",
                "test-run",
            )

        # Verify Instructor was used (not the old LangChain path)
        assert mock_instructor_module.from_bedrock.called, (
            "FEAT-114: _stage_2_compile must use instructor.from_bedrock"
        )
        assert mock_instructor_client.messages.create.called, (
            "FEAT-114: _stage_2_compile must call instructor_client.messages.create"
        )

        # Verify correct model was requested
        call_kwargs = mock_instructor_client.messages.create.call_args
        assert call_kwargs is not None
        kwargs = call_kwargs.kwargs if call_kwargs.kwargs else call_kwargs[1]
        from backend.config import settings
        assert kwargs.get("model") == settings.bedrock_model_id_parser, (
            f"FEAT-114: Must use bedrock_model_id_parser, got {kwargs.get('model')}"
        )

        # Verify response_model is TestPlan
        assert kwargs.get("response_model") is TestPlan, (
            "FEAT-114: Instructor must be called with response_model=TestPlan"
        )

        # Verify result is a valid TestPlan
        assert isinstance(result, TestPlan), "Stage 2 must return a TestPlan instance"

    @pytest.mark.anyio
    async def test_stage2_plan_includes_persona_switch_step(self):
        """
        FEAT-114: When Instructor returns a plan with PERSONA_SWITCH step,
        _stage_2_compile must return it intact.
        """
        from unittest.mock import MagicMock, patch

        from backend.engine.ac_parser import _stage_2_compile
        from backend.engine.schemas import TestPlan

        plan_with_persona = TestPlan.model_validate(json.loads(_make_test_plan_json(
            _make_step_json(1, "NAVIGATE", "Login as Demo AE"),
            _make_step_json(2, "PERSONA_SWITCH", "Switch to persona: Demo Prod dir", "Demo Prod dir"),
            _make_step_json(3, "CLICK", "Do action Y"),
        )))

        mock_instructor_client = MagicMock()
        mock_instructor_client.messages.create.return_value = plan_with_persona

        with (
            patch("backend.engine.ac_parser.boto3") as mock_boto3,
            patch("backend.engine.ac_parser.instructor") as mock_instructor_module,
            patch("backend.engine.ac_parser.get_run_metrics"),
        ):
            mock_boto3.client.return_value = MagicMock()
            mock_instructor_module.from_bedrock.return_value = mock_instructor_client
            mock_instructor_module.Mode.MD_JSON = "MD_JSON"

            result = await _stage_2_compile(
                "Given I am logged in as Demo AE\nWhen I switch to Demo Prod dir",
                "test-run",
            )

        persona_steps = [s for s in result.steps if s.step_type == "PERSONA_SWITCH"]
        assert len(persona_steps) >= 1, (
            "Plan with PERSONA_SWITCH step must be preserved through Stage 2"
        )
        assert persona_steps[0].target_persona == "Demo Prod dir"


# ---------------------------------------------------------------------------
# 4. End-to-end: ac_parser_node emits PERSONA_SWITCH steps
# ---------------------------------------------------------------------------


class TestACParserNodePersonaSwitchEmission:
    """
    ac_parser_node should emit PERSONA_SWITCH StructuredACStep objects when
    the LLM (Stage 2) returns a PERSONA_SWITCH step in the compiled TestPlan.
    """

    @pytest.mark.anyio
    async def test_ac_parser_emits_persona_switch_step(self):
        """
        AC-ENTRY-1: When Stage 2 returns a PERSONA_SWITCH step, the resulting
        test_plan must contain a step with step_type='PERSONA_SWITCH' and
        correct target_persona.
        """
        state = _make_state()
        state["jira_ticket"]["acceptance_criteria"] = (
            "Log in as Demo AE. Do X. As Demo Prod dir, do Y."
        )
        state["jira_ticket"]["summary"] = "Multi-persona test"
        state["jira_ticket"]["attachments"] = []

        stage2_plan_json = _make_test_plan_json(
            _make_step_json(1, "NAVIGATE", "Login as Demo AE"),
            _make_step_json(2, "CLICK", "Do action X"),
            _make_step_json(3, "PERSONA_SWITCH", "Switch to persona: Demo Prod dir", "Demo Prod dir"),
            _make_step_json(4, "CLICK", "Do action Y"),
        )

        with (
            patch("backend.engine.ac_parser._stage_1_normalize", new_callable=AsyncMock) as mock_s1,
            patch("backend.engine.ac_parser._stage_2_compile", new_callable=AsyncMock) as mock_s2,
            patch("backend.engine.ac_parser.build_global_context", new_callable=AsyncMock) as mock_ctx,
            patch("backend.engine.ac_parser.score_ac_quality") as mock_quality,
        ):
            from backend.engine.schemas import TestPlan

            mock_s1.return_value = "BDD text with persona switch"
            mock_s2.return_value = TestPlan.model_validate(json.loads(stage2_plan_json))
            mock_ctx.return_value = ""
            mock_quality.return_value = MagicMock(score=8, to_dict=lambda: {"score": 8, "passed": True})

            from backend.engine.ac_parser import ac_parser_node
            result = await ac_parser_node(state)


        assert result is not None
        test_plan_dict = result.get("test_plan")
        assert test_plan_dict is not None, "test_plan should be populated in result"

        from backend.engine.schemas import TestPlan
        test_plan = TestPlan.model_validate(test_plan_dict)

        persona_steps = [s for s in test_plan.steps if s.step_type == "PERSONA_SWITCH"]
        assert len(persona_steps) == 1, (
            f"Expected 1 PERSONA_SWITCH step, found {len(persona_steps)}. "
            f"Steps: {[s.step_type for s in test_plan.steps]}"
        )
        assert persona_steps[0].target_persona == "Demo Prod dir", (
            f"Expected target_persona='Demo Prod dir', got '{persona_steps[0].target_persona}'"
        )

    @pytest.mark.anyio
    async def test_ac_parser_emits_goal_string_for_persona_switch(self):
        """
        AC-ENTRY-1: The acceptance_criteria_steps legacy list must include
        a readable goal string like 'Switch to persona: Demo Prod dir'.
        """
        state = _make_state()
        state["jira_ticket"]["acceptance_criteria"] = (
            "Log in as Demo AE. As Demo Prod dir, verify X."
        )
        state["jira_ticket"]["summary"] = "Persona test"
        state["jira_ticket"]["attachments"] = []

        stage2_plan_json = _make_test_plan_json(
            _make_step_json(1, "NAVIGATE", "Login as Demo AE"),
            _make_step_json(2, "PERSONA_SWITCH", "Switch to persona: Demo Prod dir", "Demo Prod dir"),
            _make_step_json(3, "VERIFY_ONLY", "Verify X as Demo Prod dir"),
        )

        with (
            patch("backend.engine.ac_parser._stage_1_normalize", new_callable=AsyncMock) as mock_s1,
            patch("backend.engine.ac_parser._stage_2_compile", new_callable=AsyncMock) as mock_s2,
            patch("backend.engine.ac_parser.build_global_context", new_callable=AsyncMock) as mock_ctx,
            patch("backend.engine.ac_parser.score_ac_quality") as mock_quality,
        ):
            from backend.engine.schemas import TestPlan

            mock_s1.return_value = "BDD text"
            mock_s2.return_value = TestPlan.model_validate(json.loads(stage2_plan_json))
            mock_ctx.return_value = ""
            mock_quality.return_value = MagicMock(score=8, to_dict=lambda: {"score": 8, "passed": True})

            from backend.engine.ac_parser import ac_parser_node
            result = await ac_parser_node(state)

        # Check legacy acceptance_criteria_steps includes persona switch goal
        updated_ticket = result.get("jira_ticket", {})
        ac_steps = updated_ticket.get("acceptance_criteria_steps", [])
        assert len(ac_steps) >= 1, "acceptance_criteria_steps should not be empty"

        persona_goals = [s for s in ac_steps if "persona" in s.lower() or "switch" in s.lower()]
        assert len(persona_goals) >= 1, (
            f"acceptance_criteria_steps must include persona-switch goal. "
            f"Steps: {ac_steps}"
        )

    @pytest.mark.anyio
    async def test_ac_parser_handles_multiple_persona_switches(self):
        """
        AC-HAPPY-4: Multiple PERSONA_SWITCH steps in one test plan are all emitted.
        """
        state = _make_state()
        state["jira_ticket"]["acceptance_criteria"] = (
            "Log in as Demo AE. As Demo Prod dir, do X. As yourself, verify Y."
        )
        state["jira_ticket"]["summary"] = "Multi-switch test"
        state["jira_ticket"]["attachments"] = []

        stage2_plan_json = _make_test_plan_json(
            _make_step_json(1, "NAVIGATE", "Login as Demo AE"),
            _make_step_json(2, "PERSONA_SWITCH", "Switch to persona: Demo Prod dir", "Demo Prod dir"),
            _make_step_json(3, "CLICK", "Do action X"),
            _make_step_json(4, "PERSONA_SWITCH", "Switch to persona: yourself", "yourself"),
            _make_step_json(5, "VERIFY_ONLY", "Verify Y"),
        )

        with (
            patch("backend.engine.ac_parser._stage_1_normalize", new_callable=AsyncMock) as mock_s1,
            patch("backend.engine.ac_parser._stage_2_compile", new_callable=AsyncMock) as mock_s2,
            patch("backend.engine.ac_parser.build_global_context", new_callable=AsyncMock) as mock_ctx,
            patch("backend.engine.ac_parser.score_ac_quality") as mock_quality,
        ):
            from backend.engine.schemas import TestPlan

            mock_s1.return_value = "BDD text"
            mock_s2.return_value = TestPlan.model_validate(json.loads(stage2_plan_json))
            mock_ctx.return_value = ""
            mock_quality.return_value = MagicMock(score=8, to_dict=lambda: {"score": 8, "passed": True})

            from backend.engine.ac_parser import ac_parser_node
            result = await ac_parser_node(state)

        test_plan_dict = result.get("test_plan")
        from backend.engine.schemas import TestPlan
        test_plan = TestPlan.model_validate(test_plan_dict)

        persona_steps = [s for s in test_plan.steps if s.step_type == "PERSONA_SWITCH"]
        assert len(persona_steps) == 2, f"Expected 2 PERSONA_SWITCH steps, got {len(persona_steps)}"
        assert persona_steps[0].target_persona == "Demo Prod dir"
        assert persona_steps[1].target_persona == "yourself"


# ---------------------------------------------------------------------------
# 5. Role alias resolution tests (AC-ENTRY-2)
# ---------------------------------------------------------------------------


class TestRoleAliasResolution:
    """
    AC-ENTRY-2: Verify that ROLE_ALIASES resolves persona names used in
    AC text to correct role keys. These are unit tests of the existing
    resolve_role_by_name() function against persona-switch-specific aliases.
    """

    def test_as_yourself_resolves_via_alias(self):
        """
        'yourself' is not a ROLE_ALIAS — it's a sentinel that the
        persona_switch_node maps to initial_actor. This test confirms
        resolve_role_by_name('yourself') returns None (sentinel, not a role).
        """
        from backend.engine.roles import resolve_role_by_name

        result = resolve_role_by_name("yourself")
        # "yourself" is NOT in ROLE_ALIASES — it's handled by persona_switch_node
        # as a sentinel → initial_actor. resolve_role_by_name should return None.
        assert result is None, (
            "'yourself' must NOT resolve to a role via ROLE_ALIASES — "
            "it's a sentinel handled by persona_switch_node. "
            f"Got: {result}"
        )

    def test_demo_prod_dir_resolves_to_digital_director(self):
        """'Demo Prod dir' must resolve to 'digital_director' role."""
        from backend.engine.roles import resolve_role_by_name

        result = resolve_role_by_name("Demo Prod dir")
        assert result is not None, "Expected 'Demo Prod dir' to resolve to a role, got None"
        assert result["role_key"] == "digital_director", (
            f"Expected role_key='digital_director', got '{result['role_key']}'"
        )

    def test_production_director_resolves_to_digital_director(self):
        """'Production Director' must resolve to 'digital_director' (alias)."""
        from backend.engine.roles import resolve_role_by_name

        result = resolve_role_by_name("Production Director")
        assert result is not None
        assert result["role_key"] == "digital_director"

    def test_demo_production_director_resolves_to_digital_director(self):
        """'Demo Production Director' must resolve to 'digital_director'."""
        from backend.engine.roles import resolve_role_by_name

        result = resolve_role_by_name("Demo Production Director")
        assert result is not None
        assert result["role_key"] == "digital_director"

    def test_alias_resolution_is_case_insensitive(self):
        """Alias resolution must be case-insensitive (AC-ENTRY-2)."""
        from backend.engine.roles import resolve_role_by_name

        # All-caps
        result_upper = resolve_role_by_name("DEMO PROD DIR")
        assert result_upper is not None, "'DEMO PROD DIR' (uppercase) should resolve"
        assert result_upper["role_key"] == "digital_director"

        # Mixed case
        result_mixed = resolve_role_by_name("Demo PROD Dir")
        assert result_mixed is not None
        assert result_mixed["role_key"] == "digital_director"

    def test_unknown_persona_returns_none(self):
        """Unknown persona names should return None (triggers HITL in persona_switch_node)."""
        from backend.engine.roles import resolve_role_by_name

        result = resolve_role_by_name("Completely Unknown Persona XYZ123")
        assert result is None, (
            "Unknown persona names must return None from resolve_role_by_name. "
            f"Got: {result}"
        )

    def test_demo_ae_resolves_to_account_executive(self):
        """'Demo AE' must resolve to 'account_executive'."""
        from backend.engine.roles import resolve_role_by_name

        result = resolve_role_by_name("Demo AE")
        assert result is not None
        assert result["role_key"] == "account_executive"

    def test_demo_producer_resolves_to_producer(self):
        """'Demo Producer' must resolve to 'producer'."""
        from backend.engine.roles import resolve_role_by_name

        result = resolve_role_by_name("Demo Producer")
        assert result is not None
        assert result["role_key"] == "producer"


# ---------------------------------------------------------------------------
# 6. BDD Normalizer prompt handles persona-switch AC patterns (prompt content)
# ---------------------------------------------------------------------------


class TestBDDNormalizerPersonaPatternCoverage:
    """
    Verify the BDD normalizer prompt specifically covers the AC text patterns
    that trigger PERSONA_SWITCH detection per the TASK-063 requirements.
    """

    def test_bdd_normalizer_prompt_covers_as_role_name_pattern(self):
        """BDD_NORMALIZER_PROMPT must cover the 'as [Role Name]' language pattern."""
        from backend.engine.prompts import BDD_NORMALIZER_PROMPT

        lower = BDD_NORMALIZER_PROMPT.lower()
        # Must have SOME guidance about switching personas during a test
        assert any(phrase in lower for phrase in [
            "as yourself",
            "as [role",
            "as [name",
            "persona",
            "switch user",
            "log out",
        ]), (
            "BDD_NORMALIZER_PROMPT must include persona-switching guidance covering "
            "patterns like 'as yourself', 'as [Role Name]', or similar. "
            "None of the expected phrases found."
        )

    def test_json_compiler_prompt_has_persona_switch_example(self):
        """JSON_COMPILER_PROMPT should include a PERSONA_SWITCH usage example."""
        from backend.engine.prompts import JSON_COMPILER_PROMPT

        # Either has a direct example or at minimum the step type documented
        assert "PERSONA_SWITCH" in JSON_COMPILER_PROMPT, (
            "JSON_COMPILER_PROMPT must document PERSONA_SWITCH step type. "
            "Expected to find 'PERSONA_SWITCH' in the prompt."
        )
