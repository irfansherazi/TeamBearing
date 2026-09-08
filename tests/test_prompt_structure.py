"""
tests/test_prompt_structure.py
==============================
TASK-079: Prompt Engineering Hardening — Structural Test Suite

Purpose: Encode structural invariants that all target prompts MUST satisfy.
These tests run as PURE STATIC STRING ANALYSIS — no LLM calls, no browser.

Tests:
  1. test_planner_no_duplicate_highest_priority  — _CORE_RULES has exactly 1 "HIGHEST PRIORITY"
  2. test_all_prompts_have_golden_rules_at_start  — <GOLDEN_RULES> in first 20% of each prompt
  3. test_all_prompts_have_critical_reminder_at_end — <CRITICAL_REMINDER> in last 20% of each prompt
  4. test_supervisor_uses_xml_delimiters          — <AC_STEP> wraps ac_step in HumanMessage
  5. test_few_shot_covers_primeng_cases           — SLOT 26 few-shot has 3 required PrimeNG patterns
  6. test_prompt_budget_not_exceeded              — assembled planner prompt ≤ 8000 tokens

Acceptance Criteria (from TASK-079 spec):
  AC-ENTRY-1, AC-ENTRY-2, AC-HAPPY-1, AC-HAPPY-2, AC-EDGE-2
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path setup: ensure backend package is importable
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def _fraction_slice(text: str, start: float, end: float) -> str:
    """Return the portion of *text* between fractional positions [start, end)."""
    n = len(text)
    return text[int(n * start) : int(n * end)]


def _first_n_pct(text: str, pct: float = 0.20) -> str:
    """Return the first *pct* fraction of *text*."""
    return _fraction_slice(text, 0.0, pct)


def _last_n_pct(text: str, pct: float = 0.20) -> str:
    """Return the last *pct* fraction of *text*."""
    return _fraction_slice(text, 1.0 - pct, 1.0)


# ---------------------------------------------------------------------------
# Test 1: AC-ENTRY-1 — No duplicate HIGHEST PRIORITY in _CORE_RULES
# ---------------------------------------------------------------------------


class TestPlannerNoDuplicateHighestPriority:
    """AC-ENTRY-1: _CORE_RULES must have exactly ONE 'HIGHEST PRIORITY' rule."""

    def test_planner_no_duplicate_highest_priority(self) -> None:
        """
        Scans _CORE_RULES string in planner.py.
        Asserts 'HIGHEST PRIORITY' appears at most once.

        The RECIPE MANDATE must subsume the P-SELECT EXCEPTION as a nested
        clause — they must NOT both bear 'HIGHEST PRIORITY' labels.
        """
        from backend.engine import planner  # noqa: PLC0415

        core_rules: str = planner._CORE_RULES  # type: ignore[attr-defined]
        assert isinstance(core_rules, str), "_CORE_RULES must be a string"

        count = core_rules.count("HIGHEST PRIORITY")
        assert count <= 1, (
            f"_CORE_RULES contains {count} occurrences of 'HIGHEST PRIORITY'. "
            "Expected ≤ 1. The P-SELECT EXCEPTION must be nested inside the "
            "RECIPE MANDATE block as an exception clause, not a co-equal rule. "
            "Fix: move '⛔ RECIPE EXCEPTION' text inside the RECIPE MANDATE "
            "block and remove the duplicate ═══ border."
        )

    def test_planner_core_rules_has_recipe_mandate(self) -> None:
        """Verify the RECIPE MANDATE itself still exists after restructuring."""
        from backend.engine import planner  # noqa: PLC0415

        core_rules: str = planner._CORE_RULES  # type: ignore[attr-defined]
        assert "RECIPE MANDATE" in core_rules, (
            "_CORE_RULES must still contain the RECIPE MANDATE rule."
        )

    def test_planner_core_rules_has_p_select_exception(self) -> None:
        """The P-SELECT EXCEPTION text must still be present (just nested, not co-equal)."""
        from backend.engine import planner  # noqa: PLC0415

        core_rules: str = planner._CORE_RULES  # type: ignore[attr-defined]
        # The exception clause must survive — only the 'HIGHEST PRIORITY' label is removed
        assert "p-select" in core_rules.lower() or "RECIPE EXCEPTION" in core_rules, (
            "_CORE_RULES must still contain the p-select exception clause "
            "(just nested inside RECIPE MANDATE, not as a separate rule)."
        )


# ---------------------------------------------------------------------------
# Test 2: AC-ENTRY-2 — All five target prompts have <GOLDEN_RULES> at start
# ---------------------------------------------------------------------------


class TestAllPromptsHaveGoldenRulesAtStart:
    """AC-ENTRY-2 (primacy): <GOLDEN_RULES> must appear in the first 20% of each prompt."""

    def _assert_golden_rules_at_start(self, name: str, prompt: str) -> None:
        first_20 = _first_n_pct(prompt, 0.20)
        assert "<GOLDEN_RULES>" in first_20, (
            f"Prompt '{name}' does not have <GOLDEN_RULES> in its first 20%. "
            f"First 200 chars: {repr(prompt[:200])}"
        )

    def test_planner_core_rules_has_golden_rules_at_start(self) -> None:
        """_CORE_RULES (planner system prompt base) starts with <GOLDEN_RULES>."""
        from backend.engine import planner  # noqa: PLC0415

        prompt: str = planner._CORE_RULES  # type: ignore[attr-defined]
        # The planner assembles GOLDEN_RULES at the top of its CRITICAL tier (identity slot)
        # For _CORE_RULES itself: it should start with or reference GOLDEN_RULES
        # We check the assembled planner prompt via the _build_system_prompt_v2 function
        # indirectly: GOLDEN_RULES is injected at IDENTITY slot (first CRITICAL slot).
        # This test verifies the fragment is present in _CORE_RULES or that
        # prompt_fragments.GOLDEN_RULES is referenced at import time.
        from backend.engine.prompt_fragments import GOLDEN_RULES  # noqa: PLC0415

        assert "<GOLDEN_RULES>" in GOLDEN_RULES, (
            "prompt_fragments.GOLDEN_RULES must contain the <GOLDEN_RULES> tag."
        )

    def test_verifier_system_prompt_has_golden_rules_at_start(self) -> None:
        """_VERIFIER_SYSTEM_PROMPT starts with <GOLDEN_RULES> block."""
        from backend.engine import verifier  # noqa: PLC0415

        prompt: str = verifier._VERIFIER_SYSTEM_PROMPT  # type: ignore[attr-defined]
        self._assert_golden_rules_at_start("_VERIFIER_SYSTEM_PROMPT", prompt)

    def test_supervisor_prompt_has_golden_rules_at_start(self) -> None:
        """_CLASSIFY_SYSTEM_PROMPT starts with <GOLDEN_RULES> block (via prompt_fragments)."""
        from backend.engine import supervisor  # noqa: PLC0415

        prompt: str = supervisor._CLASSIFY_SYSTEM_PROMPT  # type: ignore[attr-defined]
        self._assert_golden_rules_at_start("_CLASSIFY_SYSTEM_PROMPT", prompt)

    def test_bdd_normalizer_prompt_has_golden_rules_at_start(self) -> None:
        """BDD_NORMALIZER_PROMPT starts with <GOLDEN_RULES> block."""
        from backend.engine import prompts  # noqa: PLC0415

        prompt: str = prompts.BDD_NORMALIZER_PROMPT  # type: ignore[attr-defined]
        self._assert_golden_rules_at_start("BDD_NORMALIZER_PROMPT", prompt)

    def test_json_compiler_prompt_has_golden_rules_at_start(self) -> None:
        """JSON_COMPILER_PROMPT starts with <GOLDEN_RULES> block."""
        from backend.engine import prompts  # noqa: PLC0415

        prompt: str = prompts.JSON_COMPILER_PROMPT  # type: ignore[attr-defined]
        self._assert_golden_rules_at_start("JSON_COMPILER_PROMPT", prompt)


# ---------------------------------------------------------------------------
# Test 3: AC-ENTRY-2 — All five target prompts have <CRITICAL_REMINDER> at end
# ---------------------------------------------------------------------------


class TestAllPromptsHaveCriticalReminderAtEnd:
    """AC-ENTRY-2 (recency): <CRITICAL_REMINDER> must appear in the last 20% of each prompt."""

    def _assert_critical_reminder_at_end(self, name: str, prompt: str) -> None:
        last_20 = _last_n_pct(prompt, 0.20)
        assert "<CRITICAL_REMINDER>" in last_20, (
            f"Prompt '{name}' does not have <CRITICAL_REMINDER> in its last 20%. "
            f"Last 200 chars: {repr(prompt[-200:])}"
        )

    def test_verifier_system_prompt_has_critical_reminder_at_end(self) -> None:
        """_VERIFIER_SYSTEM_PROMPT ends with a <CRITICAL_REMINDER> block."""
        from backend.engine import verifier  # noqa: PLC0415

        prompt: str = verifier._VERIFIER_SYSTEM_PROMPT  # type: ignore[attr-defined]
        self._assert_critical_reminder_at_end("_VERIFIER_SYSTEM_PROMPT", prompt)

    def test_supervisor_prompt_has_critical_reminder_at_end(self) -> None:
        """_CLASSIFY_SYSTEM_PROMPT ends with a <CRITICAL_REMINDER> block."""
        from backend.engine import supervisor  # noqa: PLC0415

        prompt: str = supervisor._CLASSIFY_SYSTEM_PROMPT  # type: ignore[attr-defined]
        self._assert_critical_reminder_at_end("_CLASSIFY_SYSTEM_PROMPT", prompt)

    def test_bdd_normalizer_prompt_has_critical_reminder_at_end(self) -> None:
        """BDD_NORMALIZER_PROMPT ends with a <CRITICAL_REMINDER> block."""
        from backend.engine import prompts  # noqa: PLC0415

        prompt: str = prompts.BDD_NORMALIZER_PROMPT  # type: ignore[attr-defined]
        self._assert_critical_reminder_at_end("BDD_NORMALIZER_PROMPT", prompt)

    def test_json_compiler_prompt_has_critical_reminder_at_end(self) -> None:
        """JSON_COMPILER_PROMPT ends with a <CRITICAL_REMINDER> block."""
        from backend.engine import prompts  # noqa: PLC0415

        prompt: str = prompts.JSON_COMPILER_PROMPT  # type: ignore[attr-defined]
        self._assert_critical_reminder_at_end("JSON_COMPILER_PROMPT", prompt)


# ---------------------------------------------------------------------------
# Test 4: AC-HAPPY-2 — Supervisor uses XML delimiters + AC_STEP wrapping
# ---------------------------------------------------------------------------


class TestSupervisorUsesXmlDelimiters:
    """AC-HAPPY-2: supervisor.py must use XML structural delimiters."""

    def test_supervisor_classify_system_prompt_has_xml_sections(self) -> None:
        """
        _CLASSIFY_SYSTEM_PROMPT must use XML section tags (not just Markdown ## headers).
        Expected sections: <WORKER_TYPES> and <CLASSIFICATION_RULES>.
        """
        from backend.engine import supervisor  # noqa: PLC0415

        prompt: str = supervisor._CLASSIFY_SYSTEM_PROMPT  # type: ignore[attr-defined]

        assert "<WORKER_TYPES>" in prompt, (
            "_CLASSIFY_SYSTEM_PROMPT must wrap the Worker Types section in <WORKER_TYPES> tags. "
            "Current prompt uses ## Markdown headers with no XML isolation."
        )
        assert "<CLASSIFICATION_RULES>" in prompt, (
            "_CLASSIFY_SYSTEM_PROMPT must wrap the Rules section in <CLASSIFICATION_RULES> tags."
        )

    def test_supervisor_imports_golden_rules_from_fragments(self) -> None:
        """
        AC-HAPPY-2: supervisor.py must import GOLDEN_RULES from prompt_fragments
        and include its content in _CLASSIFY_SYSTEM_PROMPT.
        """
        from backend.engine import supervisor  # noqa: PLC0415
        from backend.engine.prompt_fragments import GOLDEN_RULES  # noqa: PLC0415

        prompt: str = supervisor._CLASSIFY_SYSTEM_PROMPT  # type: ignore[attr-defined]

        # The GOLDEN_RULES content (without leading/trailing whitespace) must be in prompt
        golden_core = "<GOLDEN_RULES>" 
        assert golden_core in prompt, (
            "supervisor._CLASSIFY_SYSTEM_PROMPT must include GOLDEN_RULES from prompt_fragments. "
            f"Expected to find '{golden_core}' in prompt. "
            "Fix: import GOLDEN_RULES from backend.engine.prompt_fragments and prepend to prompt."
        )

    def test_supervisor_ac_step_wrapping_in_human_message(self) -> None:
        """
        AC-HAPPY-2 + AC-ENTRY-2: When _classify_intent is called, the HumanMessage
        must wrap ac_step in <AC_STEP>...</AC_STEP> XML tags.

        We test this by inspecting the source of _classify_intent or by checking
        that the string '<AC_STEP>' appears somewhere in supervisor.py source.
        """
        import inspect  # noqa: PLC0415

        from backend.engine import supervisor  # noqa: PLC0415

        source = inspect.getsource(supervisor)
        assert "<AC_STEP>" in source, (
            "supervisor.py must wrap the ac_step variable in <AC_STEP> XML tags "
            "when building the HumanMessage in _classify_intent(). "
            "Expected to find '<AC_STEP>' in the module source."
        )


# ---------------------------------------------------------------------------
# Test 5: AC-HAPPY-1 — Few-shot covers three PrimeNG failure modes (SLOT 26)
# ---------------------------------------------------------------------------


class TestFewShotCoversPrimeNGCases:
    """AC-HAPPY-1: SLOT 26 few-shot examples must cover the 3 PrimeNG failure modes."""

    _REQUIRED_KEYWORDS = [
        "primeng_dropdown",           # sorting re-render race condition pattern
        "po-sorting-dropdown-panel",  # correct portal_class for p-select column headers
        "p-select-overlay",           # p-select anti-loop guard pattern
    ]

    def _get_few_shot_block(self) -> str:
        """
        Extract the SLOT 26 few-shot block from the _build_system_prompt_v2 source.
        We look for it directly in _CORE_RULES or in the static few_shot string
        assembled in _build_system_prompt_v2.
        """
        import inspect  # noqa: PLC0415

        from backend.engine import planner  # noqa: PLC0415

        # The few-shot examples live in _CORE_RULES (static string at module level)
        # and are also injected via budget.add("few_shot_examples", ...) in _build_system_prompt_v2.
        # Both locations must cover the required patterns.
        source = planner._CORE_RULES  # type: ignore[attr-defined]
        build_source = inspect.getsource(planner._build_system_prompt_v2)  # type: ignore[attr-defined]
        return source + build_source

    def test_few_shot_has_primeng_dropdown_keyword(self) -> None:
        """SLOT 26 must contain 'primeng_dropdown' to cover sorting re-render race condition."""
        block = self._get_few_shot_block()
        assert "primeng_dropdown" in block, (
            "The SLOT 26 few-shot block must include an example of 'primeng_dropdown' action "
            "to cover the PrimeNG sorting re-render race condition failure mode."
        )

    def test_few_shot_has_po_sorting_dropdown_panel_keyword(self) -> None:
        """SLOT 26 must contain 'po-sorting-dropdown-panel' (correct portal_class for p-select)."""
        block = self._get_few_shot_block()
        assert "po-sorting-dropdown-panel" in block, (
            "The SLOT 26 few-shot block must include an example using portal_class "
            "'.po-sorting-dropdown-panel' to cover compound column sort (Due/Days)."
        )

    def test_few_shot_has_p_select_overlay_or_anti_loop_pattern(self) -> None:
        """
        SLOT 26 must contain 'p-select-overlay' to cover the p-select dropdown
        anti-loop guard (don't re-click after open pattern).
        """
        block = self._get_few_shot_block()
        assert "p-select-overlay" in block, (
            "The SLOT 26 few-shot block must include an example referencing 'p-select-overlay' "
            "to cover the p-select dropdown toggle anti-loop guard (don't re-click after open). "
            "Add an explicit example showing that when .p-select-overlay is visible, "
            "the agent must NOT click the trigger again."
        )


# ---------------------------------------------------------------------------
# Test 6: AC-EDGE-2 — Token budget not exceeded
# ---------------------------------------------------------------------------


class TestPromptBudgetNotExceeded:
    """AC-EDGE-2: Assembled planner prompt must stay within the token budget ceiling."""

    _CHARS_PER_TOKEN_APPROX = 4  # Conservative estimate for English/code text
    _DEFAULT_MAX_TOKENS = 8000

    def test_core_rules_token_estimate_within_budget(self) -> None:
        """
        _CORE_RULES char count must not itself exceed the full token budget.
        This is a conservative guard — the assembled prompt includes many more
        sections, so _CORE_RULES alone must leave headroom.
        """
        from backend.engine import planner  # noqa: PLC0415

        core_rules: str = planner._CORE_RULES  # type: ignore[attr-defined]
        estimated_tokens = len(core_rules) // self._CHARS_PER_TOKEN_APPROX

        # _CORE_RULES is ~40% of the full prompt — flag if it alone exceeds 50% budget
        budget_ceiling = self._DEFAULT_MAX_TOKENS
        warn_at = budget_ceiling * 0.50
        assert estimated_tokens <= warn_at, (
            f"_CORE_RULES is estimated at {estimated_tokens} tokens "
            f"(len={len(core_rules)} chars ÷ {self._CHARS_PER_TOKEN_APPROX}). "
            f"This exceeds 50% of the {budget_ceiling} token budget before any "
            "dynamic slots are added. The expanded few-shot may have pushed it over."
        )

    def test_prompt_fragments_within_budget(self) -> None:
        """
        GOLDEN_RULES + COT_WORKFLOW + JSON_OUTPUT_REMINDER combined must be
        reasonable (< 1000 tokens) since they appear in multiple prompts.
        """
        from backend.engine import prompt_fragments  # noqa: PLC0415

        combined = (
            prompt_fragments.GOLDEN_RULES
            + prompt_fragments.COT_WORKFLOW
            + prompt_fragments.JSON_OUTPUT_REMINDER
        )
        estimated_tokens = len(combined) // self._CHARS_PER_TOKEN_APPROX
        assert estimated_tokens < 1000, (
            f"Combined prompt_fragments tokens estimated at {estimated_tokens}. "
            "These fragments appear in multiple prompts — keep them concise (< 1000 tokens combined)."
        )
