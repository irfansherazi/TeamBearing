"""
T2-e — PromptBudget Eviction Priority Tests
============================================

Verifies AC-VERIFY-7: the `evictable` field on PromptSection correctly
protects `reasoning_workflow`, `interactive_elements` (selector/skill hints),
and `current_ac_step` from budget eviction, while `failure_diary` is
trimmed first among evictable sections.

Tests:
    test_evictable_field_default_true
        AC-VERIFY-7 pre-req: new PromptSection defaults to evictable=True
        (backward-compat — no caller breaks).

    test_non_evictable_never_dropped_when_over_budget
        AC-VERIFY-7a: over-budget scenario; reasoning_workflow,
        interactive_elements, current_ac_step NOT in dropped_names.

    test_failure_diary_trimmed_first
        AC-VERIFY-7b: failure_diary is the FIRST section in dropped_names
        when the budget is exceeded.
"""

from backend.engine.prompt_budget import PromptBudget, PromptSection, Slot, Tier

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _big(n_chars: int) -> str:
    """Return a string of exactly n_chars 'x' characters."""
    return "x" * n_chars


# ---------------------------------------------------------------------------
# AC-VERIFY-7 pre-req: backward-compat default
# ---------------------------------------------------------------------------


class TestEvictableFieldDefault:
    """PromptSection.evictable defaults to True (backward-compat)."""

    def test_evictable_field_default_true(self) -> None:
        """New PromptSection without explicit evictable= returns True."""
        section = PromptSection(
            name="test_section",
            tier=Tier.ACTIVE,
            content="some content",
        )
        assert section.evictable is True, (
            "PromptSection.evictable must default to True to preserve "
            "backward-compat with all existing budget.add() call sites"
        )

    def test_evictable_can_be_set_false(self) -> None:
        """PromptSection.evictable=False is accepted."""
        section = PromptSection(
            name="protected",
            tier=Tier.STATIC,
            content="protected content",
            evictable=False,
        )
        assert section.evictable is False

    def test_budget_add_accepts_evictable_kwarg(self) -> None:
        """PromptBudget.add() accepts and propagates evictable=False."""
        budget = PromptBudget(max_tokens=8000)
        budget.add("my_section", Tier.ACTIVE, "content", evictable=False)
        # Inspect internal list to confirm the flag was stored.
        match = next((s for s in budget._sections if s.name == "my_section"), None)
        assert match is not None
        assert match.evictable is False


# ---------------------------------------------------------------------------
# AC-VERIFY-7a: non-evictable sections are NEVER dropped
# ---------------------------------------------------------------------------


class TestNonEvictableNeverDropped:
    """reasoning_workflow, interactive_elements, current_ac_step are never
    dropped when failure_diary and global_run_context are both non-empty."""

    def _build_over_budget(self) -> tuple[PromptBudget, int]:
        """Return an over-budget PromptBudget with the three protected
        sections plus large evictable sections that exceed the budget."""
        # Budget: 1 000 tokens = 4 000 chars
        budget = PromptBudget(max_tokens=1_000)
        max_chars = budget.max_chars  # 4 000

        # Protected (non-evictable) — each 200 chars each, well under budget
        budget.add(
            "reasoning_workflow",
            Tier.STATIC,
            _big(200),
            slot=Slot.REASONING_WORKFLOW,
            evictable=False,
        )
        budget.add(
            "interactive_elements",
            Tier.RAG,
            _big(200),
            slot=Slot.RAG_CONTEXT,
            evictable=False,
        )
        budget.add(
            "current_ac_step",
            Tier.CRITICAL,
            _big(200),
            slot=Slot.CURRENT_TASK,
            evictable=False,
        )

        # Evictable fillers that push us over budget
        budget.add(
            "failure_diary",
            Tier.ACTIVE,
            _big(max_chars),  # alone would fill the budget
            slot=Slot.ACTIVE_CONSTRAINTS,
            evictable=True,
        )
        budget.add(
            "global_run_context",
            Tier.AMBIENT,
            _big(max_chars),
            slot=Slot.GLOBAL_RUN_CONTEXT,
            evictable=True,
        )

        return budget, max_chars

    def test_non_evictable_never_dropped_when_over_budget(self) -> None:
        """AC-VERIFY-7a: reasoning_workflow, interactive_elements, and
        current_ac_step must not appear in dropped_names even when the
        assembled prompt is over budget."""
        budget, _ = self._build_over_budget()
        _prompt, included, dropped = budget.assemble(run_id="test")

        protected = {"reasoning_workflow", "interactive_elements", "current_ac_step"}
        dropped_set = set(d.split("(")[0] for d in dropped)

        assert not (protected & dropped_set), (
            f"Protected sections must NEVER be dropped. "
            f"Found in dropped: {protected & dropped_set}"
        )
        # All three must be in included
        included_set = set(included)
        assert protected.issubset(included_set), (
            f"Protected sections must be in included. Missing: {protected - included_set}"
        )

    def test_evictable_sections_are_dropped_when_over_budget(self) -> None:
        """Complement: evictable sections ARE dropped when over budget."""
        budget, _ = self._build_over_budget()
        _prompt, _included, dropped = budget.assemble(run_id="test")

        dropped_names = [d.split("(")[0] for d in dropped]
        evictable_in_dropped = [n for n in dropped_names if n in ("failure_diary", "global_run_context")]

        assert evictable_in_dropped, (
            "At least one evictable section (failure_diary or global_run_context) "
            "should be dropped when over budget."
        )


# ---------------------------------------------------------------------------
# AC-VERIFY-7b: failure_diary is trimmed FIRST
# ---------------------------------------------------------------------------


class TestFailureDiaryTrimmedFirst:
    """failure_diary is the FIRST section dropped when over budget."""

    def test_failure_diary_trimmed_first(self) -> None:
        """AC-VERIFY-7b: when over budget, failure_diary appears before
        any other section in the dropped_names list."""
        budget = PromptBudget(max_tokens=500)  # 2 000 chars tight budget
        max_chars = budget.max_chars

        # Non-evictable anchor (must survive)
        budget.add(
            "reasoning_workflow",
            Tier.STATIC,
            _big(100),
            slot=Slot.REASONING_WORKFLOW,
            evictable=False,
        )

        # Evictable sections — failure_diary is Tier.ACTIVE (higher priority
        # than Tier.AMBIENT), so in the standard fill-from-high-priority logic
        # failure_diary would be included BEFORE global_run_context.
        # With the evictable guard, when budget is tight, the DROP order
        # must put failure_diary FIRST (it's the highest-tier evictable section
        # that gets dropped when it still doesn't fit).
        budget.add(
            "failure_diary",
            Tier.ACTIVE,
            _big(max_chars),  # large — will not fit after anchor
            slot=Slot.ACTIVE_CONSTRAINTS,
            evictable=True,
        )
        budget.add(
            "global_run_context",
            Tier.AMBIENT,
            _big(50),  # small — might fit if failure_diary is dropped first
            slot=Slot.GLOBAL_RUN_CONTEXT,
            evictable=True,
        )

        _prompt, included, dropped = budget.assemble(run_id="test")
        dropped_names = [d.split("(")[0] for d in dropped]

        assert "failure_diary" in dropped_names, (
            "failure_diary must be in dropped_names when over budget"
        )
        # failure_diary must appear FIRST in dropped list (trimmed first)
        assert dropped_names[0] == "failure_diary", (
            f"failure_diary must be the FIRST dropped section. "
            f"Got: {dropped_names}"
        )
