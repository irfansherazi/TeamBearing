"""
Tests for the Prompt Token Budget Controller.

Covers:
  - Basic assembly within budget
  - Priority-based section dropping when over budget
  - Per-section character caps
  - Slot-based ordering in output
  - Empty/whitespace section skipping
  - Critical tier truncation (never fully dropped)
  - Diagnostic output
"""

from backend.engine.prompt_budget import PromptBudget, Slot, Tier

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_content(chars: int, label: str = "x") -> str:
    """Generate a string of exactly `chars` characters."""
    return (label * chars)[:chars]


# ---------------------------------------------------------------------------
# Basic Assembly
# ---------------------------------------------------------------------------


class TestBasicAssembly:
    """Tests for normal assembly within budget."""

    def test_empty_budget_returns_empty(self):
        budget = PromptBudget(max_tokens=8000)
        prompt, included, dropped = budget.assemble()
        assert prompt == ""
        assert included == []
        assert dropped == []

    def test_single_section(self):
        budget = PromptBudget(max_tokens=8000)
        budget.add("identity", Tier.CRITICAL, "You are vQA.", slot=Slot.IDENTITY)
        prompt, included, dropped = budget.assemble()
        assert "You are vQA." in prompt
        assert "identity" in included
        assert dropped == []

    def test_multiple_sections_ordered_by_slot(self):
        budget = PromptBudget(max_tokens=8000)
        # Add in reverse slot order
        budget.add("guidance", Tier.GUIDANCE, "Human guidance here.", slot=Slot.CRITICAL_GUIDANCE)
        budget.add("identity", Tier.CRITICAL, "You are vQA.", slot=Slot.IDENTITY)
        budget.add("task", Tier.CRITICAL, "Current step: click X.", slot=Slot.CURRENT_TASK)

        prompt, included, dropped = budget.assemble()

        # Verify slot ordering: identity → task → guidance
        id_pos = prompt.index("You are vQA.")
        task_pos = prompt.index("Current step: click X.")
        guidance_pos = prompt.index("Human guidance here.")

        assert id_pos < task_pos < guidance_pos
        assert len(dropped) == 0

    def test_whitespace_sections_skipped(self):
        budget = PromptBudget(max_tokens=8000)
        budget.add("empty", Tier.CRITICAL, "")
        budget.add("spaces", Tier.CRITICAL, "   ")
        budget.add("real", Tier.CRITICAL, "Real content.")

        prompt, included, dropped = budget.assemble()
        assert "Real content." in prompt
        assert len(included) == 1
        assert "real" in included


# ---------------------------------------------------------------------------
# Priority-Based Dropping
# ---------------------------------------------------------------------------


class TestPriorityDropping:
    """Tests for budget overflow handling."""

    def test_lowest_tier_dropped_first(self):
        # Budget: 100 tokens = 400 chars
        budget = PromptBudget(max_tokens=100)

        budget.add("critical", Tier.CRITICAL, _make_content(200, "A"), slot=0)
        budget.add("ambient", Tier.AMBIENT, _make_content(300, "B"), slot=10)

        prompt, included, dropped = budget.assemble()

        assert "critical" in included
        assert any("ambient" in d for d in dropped)

    def test_higher_tier_survives_over_lower(self):
        # Budget: 150 tokens = 600 chars
        budget = PromptBudget(max_tokens=150)

        budget.add("critical", Tier.CRITICAL, _make_content(300, "C"), slot=0)
        budget.add("rules", Tier.RULES, _make_content(200, "R"), slot=20)
        budget.add("ambient", Tier.AMBIENT, _make_content(200, "A"), slot=30)

        prompt, included, dropped = budget.assemble()

        assert "critical" in included
        assert "rules" in included
        # ambient should be dropped (300 + 200 = 500, + 200 = 700 > 600)
        assert any("ambient" in d for d in dropped)

    def test_multiple_sections_dropped_when_over_budget(self):
        # Budget: 50 tokens = 200 chars
        budget = PromptBudget(max_tokens=50)

        budget.add("critical", Tier.CRITICAL, _make_content(100, "C"), slot=0)
        budget.add("rag", Tier.RAG, _make_content(150, "R"), slot=30)
        budget.add("ambient", Tier.AMBIENT, _make_content(150, "A"), slot=40)

        prompt, included, dropped = budget.assemble()

        assert "critical" in included
        assert len(dropped) >= 1  # at least ambient dropped

    def test_critical_tier_truncated_not_dropped(self):
        # Budget: 500 tokens = 2000 chars. First critical = 1200 chars, second = 1200 chars.
        # Total = 2400 > 2000, so second won't fit fully. But since it's CRITICAL tier
        # and remaining (800 chars) > 500 threshold, it should be truncated to fit.
        budget = PromptBudget(max_tokens=500)

        budget.add("critical1", Tier.CRITICAL, _make_content(1200, "A"), slot=0)
        budget.add("critical2", Tier.CRITICAL, _make_content(1200, "B"), slot=2)

        prompt, included, dropped = budget.assemble()

        # Both should be included (second one truncated)
        assert "critical1" in included
        assert "critical2" in included
        # The truncation marker should appear
        assert "[truncated to fit budget]" in prompt


# ---------------------------------------------------------------------------
# Per-Section Caps
# ---------------------------------------------------------------------------


class TestPerSectionCaps:
    """Tests for max_chars per-section truncation."""

    def test_section_capped_at_max_chars(self):
        budget = PromptBudget(max_tokens=8000)
        long_content = _make_content(5000, "X")
        budget.add("kb", Tier.RAG, long_content, max_chars=2000, slot=30)

        prompt, included, dropped = budget.assemble()

        # The content should be truncated
        assert len(prompt) < 2100  # 2000 + truncation message
        assert "[section truncated]" in prompt

    def test_section_under_cap_unchanged(self):
        budget = PromptBudget(max_tokens=8000)
        short_content = "Short KB article."
        budget.add("kb", Tier.RAG, short_content, max_chars=2000, slot=30)

        prompt, included, dropped = budget.assemble()

        assert prompt.strip() == short_content
        assert "[section truncated]" not in prompt


# ---------------------------------------------------------------------------
# Slot Ordering
# ---------------------------------------------------------------------------


class TestSlotOrdering:
    """Tests for slot-based output ordering."""

    def test_slots_determine_output_position(self):
        budget = PromptBudget(max_tokens=8000)

        budget.add("last", Tier.GUIDANCE, "LAST SECTION", slot=60)
        budget.add("first", Tier.CRITICAL, "FIRST SECTION", slot=0)
        budget.add("middle", Tier.RULES, "MIDDLE SECTION", slot=30)

        prompt, _, _ = budget.assemble()

        first_pos = prompt.index("FIRST SECTION")
        middle_pos = prompt.index("MIDDLE SECTION")
        last_pos = prompt.index("LAST SECTION")

        assert first_pos < middle_pos < last_pos

    def test_same_slot_ordered_by_tier(self):
        budget = PromptBudget(max_tokens=8000)

        budget.add("low_pri", Tier.AMBIENT, "AMBIENT", slot=30)
        budget.add("high_pri", Tier.CRITICAL, "CRITICAL", slot=30)

        prompt, _, _ = budget.assemble()

        critical_pos = prompt.index("CRITICAL")
        ambient_pos = prompt.index("AMBIENT")

        assert critical_pos < ambient_pos


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


class TestDiagnostics:
    """Tests for diagnostic output."""

    def test_diagnostics_returns_all_sections(self):
        budget = PromptBudget(max_tokens=8000)
        budget.add("identity", Tier.CRITICAL, "You are vQA.", slot=0)
        budget.add("kb", Tier.RAG, "KB content here.", slot=30, max_chars=500)

        diag = budget.get_diagnostics()

        assert "identity" in diag
        assert "kb" in diag
        assert diag["identity"]["tier"] == "CRITICAL"
        assert diag["kb"]["tier"] == "RAG"
        assert diag["identity"]["chars"] == len("You are vQA.")

    def test_dropped_sections_include_tier_and_size(self):
        budget = PromptBudget(max_tokens=20)  # 80 chars

        budget.add("critical", Tier.CRITICAL, _make_content(60, "C"), slot=0)
        budget.add("ambient", Tier.AMBIENT, _make_content(60, "A"), slot=40)

        _, _, dropped = budget.assemble()

        assert len(dropped) >= 1
        assert any("AMBIENT" in d for d in dropped)
        assert any("60ch" in d for d in dropped)


# ---------------------------------------------------------------------------
# Slot Constants
# ---------------------------------------------------------------------------


class TestSlotConstants:
    """Tests that slot constants maintain proper ordering."""

    def test_primacy_slots_before_middle(self):
        assert Slot.PAGE_STATE < Slot.CONTEXTUAL_RULES
        assert Slot.IDENTITY < Slot.CONTEXTUAL_RULES
        assert Slot.CURRENT_TASK < Slot.CONTEXTUAL_RULES

    def test_current_task_in_primacy_zone(self):
        """The AC step must be in the top 10 slots (primacy zone)."""
        assert Slot.CURRENT_TASK <= 10

    def test_critical_guidance_in_recency_zone(self):
        """Human guidance must be in the bottom slots (recency zone)."""
        assert Slot.CRITICAL_GUIDANCE >= 50

    def test_rag_context_in_middle_zone(self):
        """RAG context should be in the middle zone."""
        assert 20 <= Slot.RAG_CONTEXT <= 40

    def test_slot_ordering_is_logical(self):
        """Verify the overall layout follows the attention curve design."""
        assert Slot.PAGE_STATE < Slot.IDENTITY < Slot.CURRENT_TASK
        assert Slot.CURRENT_TASK < Slot.ACTIVE_CONSTRAINTS
        assert Slot.CONTEXTUAL_RULES < Slot.RAG_CONTEXT
        assert Slot.RAG_CONTEXT < Slot.REASONING_WORKFLOW
        assert Slot.REASONING_WORKFLOW < Slot.CRITICAL_GUIDANCE
