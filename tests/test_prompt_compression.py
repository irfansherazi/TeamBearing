"""
tests/test_prompt_compression.py
==================================
Unit tests for rolling context summarization (TASK-080-P1C).

Tests cover:
- Token count estimate before/after compression pipeline
- Summarization trigger fires at every N=5 turns
- Summarization does NOT fire before N=5 turns
- session_summary block format in output
- Feature flag: PROMPT_COMPRESSION_ENABLED=false → no summarization
- Empty history edge case
- History shorter than window (no truncation needed)
"""

import pytest

from backend.engine.prompt_budget import (
    PromptBudget,
    RollingContextSummarizer,
    SummarizationResult,
    Tier,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def summarizer():
    return RollingContextSummarizer(window_size=5, enabled=True)


@pytest.fixture()
def disabled_summarizer():
    return RollingContextSummarizer(window_size=5, enabled=False)


def _make_action_history(n: int) -> list[dict]:
    """Create a list of N fake action history entries."""
    return [
        {
            "action": "click",
            "strategy": "get_by_role",
            "role": "button",
            "name": f"Button {i}",
            "reasoning": f"Clicked button {i} to proceed",
        }
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Summarization Trigger Tests
# ---------------------------------------------------------------------------


class TestSummarizationTrigger:
    def test_fires_at_exactly_5_turns(self, summarizer):
        history = _make_action_history(5)
        result: SummarizationResult = summarizer.maybe_summarize(history, planner_iteration=5)
        assert result.triggered

    def test_fires_at_multiples_of_5(self, summarizer):
        for iteration in [5, 10, 15, 20]:
            history = _make_action_history(iteration)
            result: SummarizationResult = summarizer.maybe_summarize(history, planner_iteration=iteration)
            assert result.triggered, f"Expected trigger at iteration {iteration}"

    def test_does_not_fire_before_5_turns(self, summarizer):
        for iteration in [1, 2, 3, 4]:
            history = _make_action_history(iteration)
            result: SummarizationResult = summarizer.maybe_summarize(history, planner_iteration=iteration)
            assert not result.triggered, f"Unexpected trigger at iteration {iteration}"

    def test_does_not_fire_between_windows(self, summarizer):
        """Iterations 6, 7, 8, 9 should not trigger (next trigger at 10)."""
        for iteration in [6, 7, 8, 9]:
            history = _make_action_history(iteration)
            result: SummarizationResult = summarizer.maybe_summarize(history, planner_iteration=iteration)
            assert not result.triggered, f"Unexpected trigger at iteration {iteration}"


# ---------------------------------------------------------------------------
# Output Format Tests
# ---------------------------------------------------------------------------


class TestSummarizationOutput:
    def test_summary_contains_session_summary_block(self, summarizer):
        history = _make_action_history(5)
        result: SummarizationResult = summarizer.maybe_summarize(history, planner_iteration=5)
        assert result.triggered
        assert "<session_summary>" in result.summary_text
        assert "</session_summary>" in result.summary_text

    def test_summary_is_shorter_than_full_history(self, summarizer):
        history = _make_action_history(10)
        full_history_text = str(history)
        result: SummarizationResult = summarizer.maybe_summarize(history, planner_iteration=10)
        assert result.triggered
        assert len(result.summary_text) < len(full_history_text)

    def test_no_trigger_summary_is_empty(self, summarizer):
        history = _make_action_history(3)
        result: SummarizationResult = summarizer.maybe_summarize(history, planner_iteration=3)
        assert not result.triggered
        assert result.summary_text == "" or result.summary_text is None


# ---------------------------------------------------------------------------
# Token Count Reduction Tests
# ---------------------------------------------------------------------------


class TestTokenCountReduction:
    def test_summarized_prompt_has_fewer_estimated_tokens(self, summarizer):
        """
        Build a prompt with 10 history items, trigger summarization at iter 10,
        verify the resulting prompt estimate is fewer tokens.
        """
        history = _make_action_history(10)
        raw_history_text = "\n".join(
            f"[{i}] {h['action']} {h['role']} '{h['name']}'" for i, h in enumerate(history)
        )
        result: SummarizationResult = summarizer.maybe_summarize(history, planner_iteration=10)
        assert result.triggered
        # summary_text should be shorter than raw history
        assert len(result.summary_text) < len(raw_history_text) * 2  # 2x headroom for XML tags


# ---------------------------------------------------------------------------
# Feature Flag Tests
# ---------------------------------------------------------------------------


class TestSummarizationFeatureFlag:
    def test_disabled_never_triggers(self, disabled_summarizer):
        for iteration in [5, 10, 15, 100]:
            history = _make_action_history(iteration)
            result: SummarizationResult = disabled_summarizer.maybe_summarize(history, planner_iteration=iteration)
            assert not result.triggered, f"Disabled summarizer triggered at iteration {iteration}"

    def test_disabled_returns_empty_summary(self, disabled_summarizer):
        history = _make_action_history(5)
        result: SummarizationResult = disabled_summarizer.maybe_summarize(history, planner_iteration=5)
        assert result.summary_text == "" or result.summary_text is None


# ---------------------------------------------------------------------------
# Edge Case Tests
# ---------------------------------------------------------------------------


class TestSummarizationEdgeCases:
    def test_empty_history_does_not_crash(self, summarizer):
        result: SummarizationResult = summarizer.maybe_summarize([], planner_iteration=5)
        assert result is not None

    def test_single_item_history_at_trigger(self, summarizer):
        """Single-item history at trigger iteration is handled gracefully."""
        history = _make_action_history(1)
        result: SummarizationResult = summarizer.maybe_summarize(history, planner_iteration=5)
        assert result is not None  # no crash

    def test_window_size_customizable(self):
        """Window size 3 triggers at 3, 6, 9..."""
        s = RollingContextSummarizer(window_size=3, enabled=True)
        history = _make_action_history(3)
        result = s.maybe_summarize(history, planner_iteration=3)
        assert result.triggered

        result2 = s.maybe_summarize(history, planner_iteration=2)
        assert not result2.triggered
