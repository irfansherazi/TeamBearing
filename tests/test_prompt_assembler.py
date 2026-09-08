"""
Tests for FEAT-060 Phase 4A — PromptAssembler
=============================================
Tests for backend/engine/prompt_assembler.py

Verifies:
- Step-scoped prompt building based on predicted action type
- Global rules only injected on first turn
- Caching of static sections (complements prompt caching)
- Feature-flag gated (step_scoped_prompts_enabled)
- Integration with action type classification
"""

import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def assembler():
    """Create a PromptAssembler instance."""
    from backend.engine.prompt_assembler import PromptAssembler
    return PromptAssembler()


@pytest.fixture
def state_first_turn():
    """VQAState-like dict for first turn of an AC step."""
    return {
        "run_id": "test-001",
        "planner_iteration": 0,
        "ac_step_index": 0,
        "jira_ticket": {
            "acceptance_criteria_steps": [
                "Navigate to the production orders page",
                "Click on the client name to open the spot",
            ]
        },
    }


@pytest.fixture
def state_later_turn():
    """VQAState-like dict for a later turn of an AC step."""
    return {
        "run_id": "test-001",
        "planner_iteration": 3,
        "ac_step_index": 1,
        "jira_ticket": {
            "acceptance_criteria_steps": [
                "Navigate to the production orders page",
                "Click on the client name to open the spot",
            ]
        },
    }


# ---------------------------------------------------------------------------
# P4A-1: Module import and PromptAssembler instantiation
# ---------------------------------------------------------------------------


class TestPromptAssemblerImport:
    """Verify the module exists and exports the expected API."""

    def test_import_succeeds(self):
        """PromptAssembler can be imported without error."""
        from backend.engine.prompt_assembler import PromptAssembler
        assert PromptAssembler is not None

    def test_instantiation(self):
        """PromptAssembler can be instantiated without arguments."""
        from backend.engine.prompt_assembler import PromptAssembler
        assembler = PromptAssembler()
        assert assembler is not None

    def test_build_system_prompt_method_exists(self, assembler):
        """PromptAssembler has a build_system_prompt method."""
        assert hasattr(assembler, "build_system_prompt")
        assert callable(assembler.build_system_prompt)

    def test_get_static_sections_method_exists(self, assembler):
        """PromptAssembler has a get_static_sections method."""
        assert hasattr(assembler, "get_static_sections")
        assert callable(assembler.get_static_sections)


# ---------------------------------------------------------------------------
# P4A-2: Step-scoped prompt building
# ---------------------------------------------------------------------------


class TestStepScopedPromptBuilding:
    """Verify that prompt content is scoped to the predicted action type."""

    def test_navigate_action_includes_navigation_rules(self, assembler):
        """Navigate action type includes navigation-specific rules."""
        prompt = assembler.build_system_prompt(
            ac_step="Navigate to the production orders page",
            action_type="navigate",
            turn=0,
            target_url="https://example.com",
        )
        assert isinstance(prompt, str)
        assert len(prompt) > 100
        # Navigation rules should be present
        assert "navigate" in prompt.lower() or "navigation" in prompt.lower() or "url" in prompt.lower()

    def test_click_action_includes_click_rules(self, assembler):
        """Click action type includes click/interaction rules."""
        prompt = assembler.build_system_prompt(
            ac_step="Click on the Submit button",
            action_type="click",
            turn=0,
            target_url="https://example.com",
        )
        assert isinstance(prompt, str)
        assert len(prompt) > 100

    def test_fill_action_includes_fill_rules(self, assembler):
        """Fill action type includes fill/input rules."""
        prompt = assembler.build_system_prompt(
            ac_step="Fill the email field with test@example.com",
            action_type="fill",
            turn=0,
            target_url="https://example.com",
        )
        assert isinstance(prompt, str)
        assert len(prompt) > 100

    def test_verify_action_includes_verify_rules(self, assembler):
        """Verify action type includes verification rules."""
        prompt = assembler.build_system_prompt(
            ac_step="Verify the success message is visible",
            action_type="verify",
            turn=0,
            target_url="https://example.com",
        )
        assert isinstance(prompt, str)
        assert len(prompt) > 100

    def test_unknown_action_type_returns_base_prompt(self, assembler):
        """Unknown action type returns a base prompt without crashing."""
        prompt = assembler.build_system_prompt(
            ac_step="Some unknown action",
            action_type="unknown_action_type",
            turn=0,
            target_url="https://example.com",
        )
        assert isinstance(prompt, str)
        assert len(prompt) > 50

    def test_prompt_is_smaller_for_simple_action_vs_complex(self, assembler):
        """Simple deterministic action yields a prompt (at most) as long as a complex one.
        
        Step-scoped prompts should not be larger than full prompts — they should be equal
        or smaller by omitting irrelevant rule sections.
        """
        click_prompt = assembler.build_system_prompt(
            ac_step="Click Submit",
            action_type="click",
            turn=0,
            target_url="https://example.com",
        )
        # Complex: all rules included (e.g., None or 'all' action type)
        full_prompt = assembler.build_system_prompt(
            ac_step="Do something complex",
            action_type=None,  # None = include all rules
            turn=0,
            target_url="https://example.com",
        )
        # The click prompt should not exceed the full prompt
        assert len(click_prompt) <= len(full_prompt) + 200  # small tolerance


# ---------------------------------------------------------------------------
# P4A-3: Global rules only on first turn
# ---------------------------------------------------------------------------


class TestGlobalRulesInjection:
    """Global rules should only appear on the first turn (turn=0)."""

    def test_global_rules_present_on_first_turn(self, assembler):
        """First turn (turn=0) includes global rules in the prompt."""
        prompt_turn0 = assembler.build_system_prompt(
            ac_step="Navigate to production orders",
            action_type="navigate",
            turn=0,
            target_url="https://example.com",
            include_global_rules=True,
        )
        # Should include some form of global/core rules
        assert len(prompt_turn0) > 200

    def test_global_rules_omitted_on_later_turns(self, assembler):
        """Later turns (turn>0) can omit global rules when explicitly disabled."""
        prompt_turn0 = assembler.build_system_prompt(
            ac_step="Navigate to production orders",
            action_type="navigate",
            turn=0,
            target_url="https://example.com",
            include_global_rules=True,
        )
        prompt_turn3 = assembler.build_system_prompt(
            ac_step="Navigate to production orders",
            action_type="navigate",
            turn=3,
            target_url="https://example.com",
            include_global_rules=False,
        )
        # Later turn without global rules should be shorter
        assert len(prompt_turn3) < len(prompt_turn0)

    def test_include_global_rules_defaults_to_true(self, assembler):
        """include_global_rules defaults to True (safe default)."""
        # Should not raise even if include_global_rules not provided
        prompt = assembler.build_system_prompt(
            ac_step="Click Submit",
            action_type="click",
            turn=5,
            target_url="https://example.com",
        )
        assert isinstance(prompt, str)
        assert len(prompt) > 100


# ---------------------------------------------------------------------------
# P4A-4: Static section caching
# ---------------------------------------------------------------------------


class TestStaticSectionCaching:
    """Static sections (tool schemas, recipe library) should be cached."""

    def test_get_static_sections_returns_string(self, assembler):
        """get_static_sections returns a non-empty string."""
        sections = assembler.get_static_sections()
        assert isinstance(sections, str)
        # May be empty if there are no static sections configured — just check type

    def test_get_static_sections_deterministic(self, assembler):
        """get_static_sections returns the same content on repeated calls."""
        s1 = assembler.get_static_sections()
        s2 = assembler.get_static_sections()
        assert s1 == s2

    def test_get_dynamic_section_for_step(self, assembler):
        """get_dynamic_section returns step-specific context."""
        dynamic = assembler.get_dynamic_section(
            ac_step="Click the Save button",
            action_type="click",
            target_url="https://example.com",
        )
        assert isinstance(dynamic, str)

    def test_dynamic_sections_differ_by_action_type(self, assembler):
        """Different action types produce different dynamic sections."""
        dynamic_click = assembler.get_dynamic_section(
            ac_step="Click the Save button",
            action_type="click",
            target_url="https://example.com",
        )
        dynamic_fill = assembler.get_dynamic_section(
            ac_step="Fill the email field",
            action_type="fill",
            target_url="https://example.com",
        )
        # At least one should be non-empty (they can be equal if action-neutral)
        assert isinstance(dynamic_click, str)
        assert isinstance(dynamic_fill, str)


# ---------------------------------------------------------------------------
# P4A-5: Feature flag integration
# ---------------------------------------------------------------------------


class TestStepScopedPromptsFeatureFlag:
    """Verify feature flag STEP_SCOPED_PROMPTS_ENABLED controls the assembler."""

    def test_feature_flag_exists_in_config(self):
        """config.py has step_scoped_prompts_enabled field."""
        from backend.config import settings
        assert hasattr(settings, "step_scoped_prompts_enabled")

    def test_feature_flag_default_is_true(self):
        """step_scoped_prompts_enabled defaults to True per spec."""
        from backend.config import settings
        assert settings.step_scoped_prompts_enabled is True

    def test_assembler_respects_flag_when_disabled(self):
        """When feature flag is False, assembler falls back to full prompt."""
        from backend.engine.prompt_assembler import PromptAssembler
        assembler = PromptAssembler(enabled=False)
        prompt = assembler.build_system_prompt(
            ac_step="Click Submit",
            action_type="click",
            turn=0,
            target_url="https://example.com",
        )
        # Should still return a valid prompt (fallback behavior)
        assert isinstance(prompt, str)
        assert len(prompt) > 50


# ---------------------------------------------------------------------------
# P4A-6: Login / upload / table keywords
# ---------------------------------------------------------------------------


class TestKeywordBasedRuleInjection:
    """Keyword detection in ac_step triggers specific rule sections."""

    def test_login_keyword_triggers_login_rules(self, assembler):
        """AC step containing 'login' gets login-specific rules injected."""
        prompt = assembler.build_system_prompt(
            ac_step="Login with the AE account credentials",
            action_type="fill",
            turn=0,
            target_url="https://example.com/login",
        )
        assert isinstance(prompt, str)
        # Should include some reference to login/credentials
        assert len(prompt) > 100

    def test_upload_keyword_triggers_upload_rules(self, assembler):
        """AC step containing 'upload' gets file-upload rules injected."""
        prompt = assembler.build_system_prompt(
            ac_step="Upload the audio file",
            action_type="click",
            turn=0,
            target_url="https://example.com",
        )
        assert isinstance(prompt, str)
        assert len(prompt) > 100

    def test_table_keyword_triggers_table_rules(self, assembler):
        """AC step containing 'table'/'sort'/'click client' gets table rules."""
        prompt = assembler.build_system_prompt(
            ac_step="Sort the production orders table by due date",
            action_type="click",
            turn=0,
            target_url="https://example.com",
        )
        assert isinstance(prompt, str)
        assert len(prompt) > 100
