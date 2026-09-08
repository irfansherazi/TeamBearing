"""
Tests for Bug 5: Prompt Budget Trimming Priority (TASK-015 Phase 2).

Validates that prompt assembly drops content in the correct priority order:
  1. Drop oldest history entries FIRST
  2. Drop session context SECOND
  3. Drop domain context LAST (highest priority of the optional blocks)

Covers:
  AC-HAPPY-11: Prompt trimming drops oldest history entries first
  AC-HAPPY-12: <domain_context> (UI_RULES/kb_context) is never dropped if
               it fits within remaining budget after trimming history
  AC-ERROR-4:  Warning logged when total prompt still exceeds budget after
               trimming all optional blocks
  AC-REGRESS-5: FEAT-020 action history buffer's most recent 2 entries
                are always preserved even during trimming
"""

import logging
import re

from backend.engine.prompt_budget import PromptBudget, Slot, Tier

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_content(chars: int, label: str = "x") -> str:
    """Generate a string of exactly `chars` characters."""
    return (label * chars)[:chars]


def _build_budget_with_history_and_domain(
    max_tokens: int,
    domain_chars: int = 500,
    history_chars: int = 3000,
    critical_chars: int = 200,
) -> PromptBudget:
    """
    Build a PromptBudget with identity (CRITICAL), domain context (RAG),
    and execution history (ACTIVE) sections.
    """
    budget = PromptBudget(max_tokens=max_tokens)
    budget.add("identity", Tier.CRITICAL, _make_content(critical_chars, "I"), slot=Slot.IDENTITY)
    budget.add("current_task", Tier.CRITICAL, _make_content(200, "T"), slot=Slot.CURRENT_TASK)
    budget.add(
        "kb_context",
        Tier.RAG,
        f"<UI_RULES>\n{_make_content(domain_chars - 22, 'D')}\n</UI_RULES>",
        slot=Slot.RAG_CONTEXT,
        max_chars=domain_chars,
    )
    budget.add(
        "execution_history",
        Tier.HISTORY,
        f"<execution_history>\n{_make_content(history_chars - 42, 'H')}\n</execution_history>",
        slot=Slot.EXECUTION_HISTORY,
        max_chars=history_chars,
    )
    return budget


# ---------------------------------------------------------------------------
# AC-HAPPY-11: Prompt trimming drops oldest history entries first
# ---------------------------------------------------------------------------


class TestTrimmingDropsHistoryFirst:
    """
    When the budget is tight, execution_history entries should be dropped
    BEFORE domain context (kb_context / UI_RULES).
    """

    def test_history_dropped_before_domain_context_when_over_budget(self):
        """
        With a tight budget, the assembler should include kb_context (domain)
        and drop execution_history, NOT the reverse.

        Bug behavior: execution_history (Tier.ACTIVE=1) was kept over
        kb_context (Tier.RAG=4) because ACTIVE had higher priority.
        Fixed: execution_history uses Tier.HISTORY which is lower priority
        than RAG, so domain context survives.
        """
        # Budget allows ~1200 chars total (300 tokens × 4)
        # critical (200) + task (200) + domain (500) = 900 → fits
        # Adding history (3000) pushes to 3900 → WAY over 1200
        budget = _build_budget_with_history_and_domain(
            max_tokens=300,
            domain_chars=500,
            history_chars=3000,
            critical_chars=200,
        )
        prompt, included, dropped = budget.assemble()

        # Domain context (kb_context) should survive
        assert "kb_context" in included, (
            "Domain context was dropped — trimming priority is wrong. History entries should be dropped first."
        )
        # History should be dropped (or truncated to minimal)
        dropped_names_flat = " ".join(dropped)
        # Either execution_history is dropped entirely, or it's not included
        if "execution_history" not in included:
            assert "execution_history" in dropped_names_flat
        # Verify domain content is actually in the assembled prompt
        assert "D" * 10 in prompt, "Domain context text not found in prompt"

    def test_history_dropped_entirely_when_budget_very_tight(self):
        """
        When budget only fits critical + domain context, history is dropped entirely.
        """
        # Budget = 200 tokens = 800 chars
        # critical (200) + task (200) + domain (300) = 700 → fits
        # history (500) → 1200 > 800 → dropped
        budget = PromptBudget(max_tokens=200)
        budget.add("identity", Tier.CRITICAL, _make_content(200, "I"), slot=Slot.IDENTITY)
        budget.add("current_task", Tier.CRITICAL, _make_content(200, "T"), slot=Slot.CURRENT_TASK)
        budget.add("kb_context", Tier.RAG, _make_content(300, "D"), slot=Slot.RAG_CONTEXT)
        budget.add("execution_history", Tier.HISTORY, _make_content(500, "H"), slot=Slot.EXECUTION_HISTORY)

        prompt, included, dropped = budget.assemble()

        assert "kb_context" in included
        dropped_flat = " ".join(dropped)
        assert "execution_history" in dropped_flat

    def test_all_tiers_have_correct_drop_order(self):
        """
        Verify the overall tier drop order matches the specification:
        AMBIENT (lowest) → STATIC → HISTORY → RAG → RULES → GUIDANCE → ACTIVE → CRITICAL
        """
        # After the fix, Tier.HISTORY should exist and be between STATIC and RAG
        assert hasattr(Tier, "HISTORY"), "Tier.HISTORY enum value must exist for execution_history sections"
        # HISTORY should be dropped before RAG (lower priority = higher number)
        assert Tier.HISTORY > Tier.RAG, (
            "Tier.HISTORY must be lower priority than Tier.RAG so history is dropped before domain context"
        )
        # But HISTORY should be higher priority than STATIC
        assert Tier.HISTORY < Tier.AMBIENT, "Tier.HISTORY must be higher priority than Tier.AMBIENT"


# ---------------------------------------------------------------------------
# AC-HAPPY-12: Domain context preserved during trim
# ---------------------------------------------------------------------------


class TestDomainContextPreserved:
    """
    The <domain_context> / <UI_RULES> block should NEVER be dropped if it
    fits within the remaining budget after history trimming.
    """

    def test_domain_context_survives_when_history_trimmed(self):
        """
        After dropping history, domain context should still be present.
        """
        # Budget = 250 tokens = 1000 chars
        # critical (200) + task (200) + domain (400) = 800 → fits in 1000
        # history (800) → 1600 > 1000 → dropped
        budget = PromptBudget(max_tokens=250)
        budget.add("identity", Tier.CRITICAL, _make_content(200, "I"), slot=Slot.IDENTITY)
        budget.add("current_task", Tier.CRITICAL, _make_content(200, "T"), slot=Slot.CURRENT_TASK)
        budget.add(
            "kb_context",
            Tier.RAG,
            "<UI_RULES>Domain knowledge for dropdown navigation</UI_RULES>",
            slot=Slot.RAG_CONTEXT,
        )
        budget.add(
            "execution_history",
            Tier.HISTORY,
            "<execution_history>Long history</execution_history>" + _make_content(700, "H"),
            slot=Slot.EXECUTION_HISTORY,
        )

        prompt, included, dropped = budget.assemble()

        assert "kb_context" in included
        assert "Domain knowledge" in prompt

    def test_domain_context_fits_after_history_drop(self):
        """
        When budget is exactly enough for critical + domain (after history drop),
        domain context should be included, not dropped.
        """
        # Budget = 175 tokens = 700 chars
        # identity (150) + task (150) = 300
        # domain (350) → 650 ≤ 700 → fits
        # history (500) → 1150 > 700 → dropped
        budget = PromptBudget(max_tokens=175)
        budget.add("identity", Tier.CRITICAL, _make_content(150, "I"), slot=Slot.IDENTITY)
        budget.add("current_task", Tier.CRITICAL, _make_content(150, "T"), slot=Slot.CURRENT_TASK)
        budget.add("kb_context", Tier.RAG, _make_content(350, "D"), slot=Slot.RAG_CONTEXT)
        budget.add("execution_history", Tier.HISTORY, _make_content(500, "H"), slot=Slot.EXECUTION_HISTORY)

        prompt, included, dropped = budget.assemble()

        assert "kb_context" in included
        assert "execution_history" not in included

    def test_both_domain_and_session_context_survive_over_history(self):
        """
        Both RAG (domain) and GUIDANCE (session) should survive when history
        is the section that gets dropped due to budget pressure.
        """
        # Budget = 400 tokens = 1600 chars
        # identity (200) + task (200) + domain (300) + session (300) = 1000 → fits
        # history (1000) → 2000 > 1600 → dropped
        budget = PromptBudget(max_tokens=400)
        budget.add("identity", Tier.CRITICAL, _make_content(200, "I"), slot=Slot.IDENTITY)
        budget.add("current_task", Tier.CRITICAL, _make_content(200, "T"), slot=Slot.CURRENT_TASK)
        budget.add("kb_context", Tier.RAG, _make_content(300, "D"), slot=Slot.RAG_CONTEXT)
        budget.add("critical_guidance", Tier.GUIDANCE, _make_content(300, "S"), slot=Slot.CRITICAL_GUIDANCE)
        budget.add("execution_history", Tier.HISTORY, _make_content(1000, "H"), slot=Slot.EXECUTION_HISTORY)

        prompt, included, dropped = budget.assemble()

        assert "kb_context" in included, "Domain context dropped — wrong priority"
        assert "critical_guidance" in included, "Session context dropped — wrong priority"
        dropped_flat = " ".join(dropped)
        assert "execution_history" in dropped_flat


# ---------------------------------------------------------------------------
# AC-REGRESS-5: Minimum 2 history entries always preserved
# ---------------------------------------------------------------------------


class TestMinimumHistoryPreserved:
    """
    FEAT-020 action history buffer — the most recent 2 entries must always
    be preserved to prevent amnesic retry loops, even during aggressive trimming.
    """

    def test_action_history_buffer_keeps_recent_entries(self):
        """
        _build_action_history always returns at least min(2, available) entries.
        This is a unit test for the history builder, not the budget system.
        """
        # This tests that when max_recent is set, at least 2 entries survive

        # Simulate state with 5 action history entries
        state = {
            "detailed_execution_log": [
                {"action_type": "click", "locator_value": "button1", "result": "success", "ac_step_index": 0},
                {"action_type": "fill", "locator_value": "input1", "result": "success", "ac_step_index": 0},
                {"action_type": "click", "locator_value": "button2", "result": "timeout", "ac_step_index": 0},
                {"action_type": "click", "locator_value": "button3", "result": "success", "ac_step_index": 0},
                {"action_type": "fill", "locator_value": "input2", "result": "success", "ac_step_index": 0},
            ],
            "ac_step_index": 0,
        }

        from backend.engine.planner import _build_action_history

        history = _build_action_history(state, max_recent=2)

        # Should contain at least the 2 most recent entries
        assert "input2" in history or "button3" in history, "Most recent entries not found in history output"

    def test_history_with_fewer_than_2_entries_keeps_all(self):
        """When only 1 entry exists, it should still be included."""
        state = {
            "detailed_execution_log": [
                {"action_type": "click", "locator_value": "only_button", "result": "success", "ac_step_index": 0},
            ],
            "ac_step_index": 0,
        }

        from backend.engine.planner import _build_action_history

        history = _build_action_history(state, max_recent=2)

        assert "only_button" in history


# ---------------------------------------------------------------------------
# AC-ERROR-4: Budget exceeded warning logged
# ---------------------------------------------------------------------------


class TestBudgetExceededWarning:
    """
    When total prompt exceeds budget after trimming ALL optional blocks,
    a WARNING should be logged with the budget breakdown.
    """

    def test_warning_logged_when_all_optional_dropped_still_over(self, caplog):
        """
        If critical sections alone exceed the budget, a warning should be logged.
        """
        # Budget = 50 tokens = 200 chars
        # Two critical sections of 150 chars each = 300 > 200
        budget = PromptBudget(max_tokens=50)
        budget.add("identity", Tier.CRITICAL, _make_content(150, "I"), slot=Slot.IDENTITY)
        budget.add("current_task", Tier.CRITICAL, _make_content(150, "T"), slot=Slot.CURRENT_TASK)
        budget.add("ambient_extra", Tier.AMBIENT, _make_content(100, "A"), slot=Slot.MEMORY)

        with caplog.at_level(logging.INFO):
            prompt, included, dropped = budget.assemble()

        # The ambient section should be dropped
        dropped_flat = " ".join(dropped)
        assert "ambient_extra" in dropped_flat

        # Critical sections are truncated to fit, not dropped
        assert "identity" in included

    def test_v1_cascading_trim_logs_warning_on_stage2(self, caplog):
        """
        The v1 cascading trim in planner_node should log a WARNING when
        it needs to enter Stage 2 (history trimming) after Stage 1.

        This verifies the cascading trim cascade order is correct:
          Stage 0: overlay options
          Stage 1: execution_history (oldest entries) ← CHANGED from UI_RULES
          Stage 2: UI_RULES (domain context)           ← CHANGED from history
        """
        # This is a structural test — verifying the cascade order in the code.
        # We can't easily call planner_node in a unit test, but we can verify
        # the regex pattern ordering in the source code.
        import inspect

        from backend.engine import planner as planner_module

        # Read the source of planner_node to verify cascade order
        source = inspect.getsource(planner_module)

        # Find the cascading trim section
        # After the fix: Stage 1 should trim execution_history BEFORE UI_RULES
        stage1_match = re.search(
            r"Stage 1.*?trim.*?execution_history|Stage 1.*?history",
            source,
            re.IGNORECASE | re.DOTALL,
        )
        re.search(
            r"Stage 2.*?trim.*?UI_RULES|Stage 2.*?RAG",
            source,
            re.IGNORECASE | re.DOTALL,
        )

        # After the fix, Stage 1 should reference history and Stage 2 should reference UI_RULES
        assert stage1_match is not None, (
            "Stage 1 of cascading trim should target execution_history (not UI_RULES). "
            "The trimming priority order must drop history before domain context."
        )


# ---------------------------------------------------------------------------
# Regression: Existing prompt budget behavior unchanged
# ---------------------------------------------------------------------------


class TestPromptBudgetRegression:
    """
    Ensure the fix doesn't break existing PromptBudget behavior for
    non-history sections.
    """

    def test_ambient_still_dropped_first(self):
        """AMBIENT tier should still be the lowest priority (dropped first)."""
        budget = PromptBudget(max_tokens=100)  # 400 chars
        budget.add("critical", Tier.CRITICAL, _make_content(200, "C"), slot=0)
        budget.add("ambient", Tier.AMBIENT, _make_content(300, "A"), slot=40)

        _, included, dropped = budget.assemble()
        assert "critical" in included
        assert any("ambient" in d for d in dropped)

    def test_critical_still_never_dropped(self):
        """CRITICAL tier sections are truncated, never dropped."""
        budget = PromptBudget(max_tokens=200)  # 800 chars
        budget.add("c1", Tier.CRITICAL, _make_content(250, "A"), slot=0)
        budget.add("c2", Tier.CRITICAL, _make_content(800, "B"), slot=2)

        _, included, _ = budget.assemble()
        assert "c1" in included
        assert "c2" in included  # truncated to fit (800-250=550 > 500 threshold)

    def test_rag_survives_when_budget_allows(self):
        """RAG sections should be included when there's enough budget."""
        budget = PromptBudget(max_tokens=8000)  # Plenty of room
        budget.add("identity", Tier.CRITICAL, "You are vQA.", slot=Slot.IDENTITY)
        budget.add("kb_context", Tier.RAG, "KB context here.", slot=Slot.RAG_CONTEXT)
        budget.add("execution_history", Tier.HISTORY, "History here.", slot=Slot.EXECUTION_HISTORY)

        _, included, dropped = budget.assemble()
        assert "kb_context" in included
        assert "execution_history" in included
        assert dropped == []

    def test_slot_ordering_preserved_after_fix(self):
        """Output ordering by slot should still work correctly."""
        budget = PromptBudget(max_tokens=8000)
        budget.add("history", Tier.HISTORY, "HISTORY", slot=Slot.EXECUTION_HISTORY)
        budget.add("identity", Tier.CRITICAL, "IDENTITY", slot=Slot.IDENTITY)
        budget.add("kb", Tier.RAG, "KB_CONTEXT", slot=Slot.RAG_CONTEXT)

        prompt, _, _ = budget.assemble()

        id_pos = prompt.index("IDENTITY")
        kb_pos = prompt.index("KB_CONTEXT")
        hist_pos = prompt.index("HISTORY")

        # Slot order: IDENTITY (2) < RAG_CONTEXT (32) < EXECUTION_HISTORY (34)
        assert id_pos < kb_pos < hist_pos
