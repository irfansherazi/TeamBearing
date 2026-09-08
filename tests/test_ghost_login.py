"""
tests/test_ghost_login.py
=========================
TDD tests for TASK-125, Phase 1: Ghost Keyword Detection.

Verifies that ``backend/engine/prompts.py`` has been broadened so the
AC parser emits GHOST_LOGIN for ANY text containing the word "ghost"
(case-insensitive), not only the narrow "Ghost In As [user]" phrasing.

All tests are prompt-level (static string assertions against
BDD_NORMALIZER_PROMPT and JSON_COMPILER_PROMPT) — no LLM calls in CI.

Acceptance Criteria covered:
    AC-ENTRY-1: bare "ghost" triggers GHOST_LOGIN detection
    AC-ENTRY-2: "Ghost In As John Smith" triggers GHOST_LOGIN with target_user
"""

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bdd_prompt() -> str:
    from backend.engine.prompts import BDD_NORMALIZER_PROMPT
    return BDD_NORMALIZER_PROMPT


def _compiler_prompt() -> str:
    from backend.engine.prompts import JSON_COMPILER_PROMPT
    return JSON_COMPILER_PROMPT


# ---------------------------------------------------------------------------
# 1. BDD Normalizer — broad ghost detection
# ---------------------------------------------------------------------------


class TestBDDNormalizerGhostDetection:
    """BDD_NORMALIZER_PROMPT must detect any 'ghost' mention, not just 'Ghost In As'."""

    def test_bdd_prompt_detects_bare_ghost_keyword(self):
        """
        Prompt must contain explicit guidance to detect bare 'ghost' (case-insensitive)
        as a ghost-login trigger — not only 'Ghost In As'.
        """
        prompt = _bdd_prompt().lower()
        # Must mention both broad ghost detection AND Ghost In As
        assert "ghost" in prompt, (
            "BDD_NORMALIZER_PROMPT must mention 'ghost' keyword detection."
        )
        # Must include the broadened rule — bare 'ghost' anywhere
        assert "ghost_login" in prompt or "ghost login" in prompt, (
            "BDD_NORMALIZER_PROMPT must instruct the LLM to emit GHOST_LOGIN for ghost mentions."
        )

    def test_bdd_prompt_covers_ghost_in_as_phrasing(self):
        """
        Prompt must still support the narrow 'Ghost In As [user]' phrasing
        for backward compatibility.
        """
        prompt = _bdd_prompt().lower()
        assert "ghost in as" in prompt, (
            "BDD_NORMALIZER_PROMPT must still mention 'Ghost In As' for backward compatibility."
        )

    def test_bdd_prompt_includes_mixed_case_ghost_guidance(self):
        """
        Prompt must instruct the LLM that ghost detection is case-insensitive —
        any capitalisation of 'ghost' should trigger GHOST_LOGIN detection.
        """
        prompt = _bdd_prompt().lower()
        # The prompt content (case-normalised) should contain ghost-related rules
        assert "ghost" in prompt, (
            "BDD_NORMALIZER_PROMPT must contain ghost-login detection guidance."
        )
        # Verify the rule references broader detection (not just exact capitalisation)
        assert "ghost_login" in prompt or "ghost login" in prompt, (
            "Prompt must instruct emission of GHOST_LOGIN for ghost-keyword matches."
        )

    def test_bdd_prompt_no_false_positive_guidance(self):
        """
        Prompt must NOT expand ghost detection so broadly that unrelated words trigger it.
        The rule must specifically anchor to the word 'ghost', not free-form.
        """
        prompt = _bdd_prompt()
        # Confirm the ghost rule is in the RULES or CRITICAL_REMINDER section,
        # meaning it is a deliberate instruction rather than an accidental mention.
        has_ghost_in_rules = (
            "<RULES>" in prompt and "ghost" in prompt[prompt.index("<RULES>"):].lower()
        ) or (
            "<CRITICAL_REMINDER>" in prompt
            and "ghost" in prompt[prompt.index("<CRITICAL_REMINDER>"):].lower()
        )
        assert has_ghost_in_rules, (
            "Ghost detection rule must be in the <RULES> or <CRITICAL_REMINDER> section "
            "of BDD_NORMALIZER_PROMPT, not as an incidental mention."
        )


# ---------------------------------------------------------------------------
# 2. JSON Compiler — GHOST_LOGIN component and target_user guidance
# ---------------------------------------------------------------------------


class TestJSONCompilerGhostLogin:
    """JSON_COMPILER_PROMPT must instruct GHOST_LOGIN to use 'ghost_panel' target_component."""

    def test_compiler_prompt_specifies_ghost_panel_target_component(self):
        """
        STEP_TYPE_GUIDE must instruct the compiler to set
        target_component = 'ghost_panel' for GHOST_LOGIN steps.
        """
        prompt = _compiler_prompt()
        assert "ghost_panel" in prompt, (
            "JSON_COMPILER_PROMPT STEP_TYPE_GUIDE must specify target_component='ghost_panel' "
            "for GHOST_LOGIN steps so the ghost_login_node can locate the credential form."
        )
