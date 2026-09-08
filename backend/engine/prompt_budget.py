"""
vQA — Prompt Token Budget Controller
========================================
Module: backend/engine/prompt_budget.py

Enforces a hard token ceiling on the assembled planner system prompt via
priority-based section management.  Each prompt section is assigned a
priority tier; when the total exceeds the budget, the lowest-priority
sections are dropped first.

Architecture Context
--------------------
  _build_system_prompt() (planner.py)
      └── PromptBudget.assemble(sections)   ← THIS MODULE
              ├── Fill from TIER_0 (critical) upward
              ├── Drop TIER_5 (ambient) sections first
              └── Log dropped sections at INFO level

Design Decisions
----------------
  - char-based estimation (÷ 4 ≈ tokens) — avoids tiktoken dependency
  - sections within the same tier sorted by char count (smaller = more
    likely to fit within remaining budget)
  - per-section caps applied before budget assembly to catch runaway RAG
  - the budget controller is a pure function with no side effects

Usage
-----
    from backend.engine.prompt_budget import PromptBudget, PromptSection, Tier

    budget = PromptBudget(max_tokens=8000)
    budget.add("identity", Tier.CRITICAL, identity_text)
    budget.add("kb_context", Tier.RAG, kb_text, max_chars=2000)
    prompt = budget.assemble()
"""

import logging
from dataclasses import dataclass
from enum import IntEnum

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Priority Tiers
# ---------------------------------------------------------------------------


class Tier(IntEnum):
    """
    Priority tiers for prompt sections.

    Lower number = higher priority = last to be dropped when over budget.
    Sections within the same tier are sorted by size (smallest first) so
    that more sections fit within the remaining budget.

    Drop order (first dropped → last dropped):
      AMBIENT → STATIC → HISTORY → RAG → RULES → GUIDANCE → ACTIVE → CRITICAL

    TASK-015 Bug 5 fix: HISTORY tier (5) was added between RAG (4) and
    STATIC (6) so execution history is dropped BEFORE domain context
    (KB/RAG). Previously, execution_history was at Tier.ACTIVE (1) which
    meant domain context (Tier.RAG=4) was dropped first — causing the
    planner to lose critical domain knowledge during retries.
    """

    CRITICAL = 0  # AC step, identity, schema rule, page state
    ACTIVE = 1  # Failure diary, forbidden locators, input value
    GUIDANCE = 2  # Human guidance, learned workflow, recipes
    RULES = 3  # Contextual rules, step-type-specific rules
    RAG = 4  # KB context, selector hints, skill hints, playwright RAG
    HISTORY = 5  # Execution history (dropped before RAG to preserve domain context)
    STATIC = 6  # Few-shot examples, reasoning workflow
    AMBIENT = 7  # Global run context, persistent memory, long-term memory


# ---------------------------------------------------------------------------
# Prompt Section
# ---------------------------------------------------------------------------


@dataclass
class PromptSection:
    """
    A single named section of the planner system prompt.

    Attributes
    ----------
    name : str
        Human-readable label (e.g., "kb_context", "failure_diary").
    tier : Tier
        Priority tier — determines drop order when over budget.
    content : str
        The raw text content of this section.
    max_chars : int
        Per-section character cap applied before budget assembly.
        0 means no cap.
    slot : int
        Position in the final prompt (lower = earlier). Sections with
        the same slot are ordered by tier then insertion order.
    """

    name: str
    tier: Tier
    content: str
    max_chars: int = 0
    slot: int = 50  # default middle position
    evictable: bool = True  # T2-e: False = protected from budget eviction

    @property
    def char_count(self) -> int:
        """Effective character count after per-section cap."""
        if self.max_chars > 0 and len(self.content) > self.max_chars:
            return self.max_chars
        return len(self.content)

    @property
    def estimated_tokens(self) -> int:
        """Rough token estimate (chars ÷ 4)."""
        return self.char_count // 4

    @property
    def effective_content(self) -> str:
        """Content after per-section cap is applied."""
        if self.max_chars > 0 and len(self.content) > self.max_chars:
            return self.content[: self.max_chars] + "\n... [section truncated]"
        return self.content


# ---------------------------------------------------------------------------
# Budget Controller
# ---------------------------------------------------------------------------


class PromptBudget:
    """
    Assembles prompt sections within a token budget.

    Fills from highest-priority (TIER_0) to lowest (TIER_6). When the
    budget is exceeded, the most recently added lowest-priority section
    is dropped. Dropped sections are logged at INFO level.

    T2-e evictable field: sections marked ``evictable=False`` are never
    dropped regardless of budget pressure. Among evictable sections,
    ``EVICTION_FIRST_NAMES`` are tried for eviction before any other
    section — this ensures the failure diary (retry noise) is shed before
    ambient context (global_run_context).

    Parameters
    ----------
    max_tokens : int
        Target token ceiling for the assembled system prompt.
        Tokens are estimated as chars ÷ 4.
    """

    # Default budget — tuned for Claude Haiku attention quality
    DEFAULT_MAX_TOKENS = 8000

    # T2-e: sections that should be evicted FIRST when budget is exceeded.
    # failure_diary is retry noise; it is more expendable than global_run_context
    # even though it has a higher priority tier (ACTIVE < AMBIENT).
    EVICTION_FIRST_NAMES: frozenset[str] = frozenset({"failure_diary"})

    def __init__(self, max_tokens: int = DEFAULT_MAX_TOKENS):
        self.max_tokens = max_tokens
        self._sections: list[PromptSection] = []

    @property
    def max_chars(self) -> int:
        """Convert token budget to character budget."""
        return self.max_tokens * 4

    def add(
        self,
        name: str,
        tier: Tier,
        content: str,
        slot: int = 50,
        max_chars: int = 0,
        evictable: bool = True,
    ) -> None:
        """
        Add a section to the prompt budget.

        Empty or whitespace-only content is silently skipped.

        Args
        ----
        name : str
            Human-readable section label.
        tier : Tier
            Priority tier for drop-order control.
        content : str
            Raw text content.
        slot : int
            Position in the final prompt (lower = earlier in output).
        max_chars : int
            Per-section character cap. 0 = no cap.
        evictable : bool
            T2-e: When False, this section is protected from budget eviction
            and will never appear in dropped_names. Defaults to True for
            backward-compat with all existing call sites.
        """
        if not content or not content.strip():
            return
        self._sections.append(
            PromptSection(
                name=name,
                tier=tier,
                content=content,
                max_chars=max_chars,
                slot=slot,
                evictable=evictable,
            )
        )

    def assemble(self, run_id: str = "?") -> tuple[str, list[str], list[str]]:
        """
        Assemble all sections within the token budget.

        Sections are included in priority order (lowest tier number first).
        When the budget is exceeded, sections are dropped from the highest
        tier number (lowest priority) first. Within the same tier, larger
        sections are dropped before smaller ones.

        The final output is ordered by ``slot`` (not tier), so the prompt
        reads in a logical top-to-bottom flow regardless of priority.

        Args
        ----
        run_id : str
            Run identifier for diagnostic logging.

        Returns
        -------
        tuple[str, list[str], list[str]]
            (assembled_prompt, included_section_names, dropped_section_names)
        """
        if not self._sections:
            return "", [], []

        # ── Step 1: Sort by fill priority ─────────────────────────────────
        # T2-e ordering (three levels):
        #   Level 0 — non-evictable (always included, process first)
        #   Level 1 — evictable but NOT in EVICTION_FIRST_NAMES (normal fill)
        #   Level 2 — evictable AND in EVICTION_FIRST_NAMES (tentative; first
        #              candidates for eviction when budget is tight)
        # Within each level, lower tier.value = higher priority = smaller size first.
        def _fill_key(s: PromptSection) -> tuple:
            if not s.evictable:
                evict_level = 0  # always included
            elif s.name in self.EVICTION_FIRST_NAMES:
                evict_level = 2  # included last → first eviction candidate
            else:
                evict_level = 1  # normal fill
            return (evict_level, s.tier.value, s.char_count)

        priority_sorted = sorted(self._sections, key=_fill_key)

        included: list[PromptSection] = []
        dropped: list[PromptSection] = []
        total_chars = 0

        # ── Step 2: Fill budget from highest priority ──────────────────────
        for section in priority_sorted:
            section_chars = section.char_count
            if total_chars + section_chars <= self.max_chars:
                included.append(section)
                total_chars += section_chars
            else:
                # T2-e: non-evictable sections are ALWAYS included even if
                # they push us over budget (they are the protected core).
                if not section.evictable:
                    included.append(section)
                    total_chars += section_chars
                # T2-e: EVICTION_FIRST_NAMES sections are dropped outright —
                # never truncated. Truncation would keep them in the prompt,
                # defeating their role as the first eviction candidates.
                elif section.name in self.EVICTION_FIRST_NAMES:
                    dropped.append(section)
                # Try to fit a truncated version for CRITICAL/ACTIVE tiers
                elif section.tier <= Tier.ACTIVE:
                    remaining = self.max_chars - total_chars
                    if remaining > 500:  # only truncate if there's meaningful space
                        truncated = PromptSection(
                            name=section.name,
                            tier=section.tier,
                            content=section.content[: remaining - 50] + "\n... [truncated to fit budget]",
                            slot=section.slot,
                        )
                        included.append(truncated)
                        total_chars += len(truncated.content)
                    else:
                        dropped.append(section)
                else:
                    dropped.append(section)

        # ── Step 3: Sort included sections by slot for output ordering ─────
        included.sort(key=lambda s: (s.slot, s.tier.value))

        # ── Step 4: Assemble final prompt ──────────────────────────────────
        parts = [s.effective_content for s in included]
        assembled = "\n".join(parts)

        included_names = [s.name for s in included]
        dropped_names = [f"{s.name}({s.tier.name}:{s.char_count}ch)" for s in dropped]

        # ── Step 5: Diagnostic logging ─────────────────────────────────────
        estimated_tokens = len(assembled) // 4
        if dropped:
            logger.info(
                "[%s] PromptBudget: %d sections included (%d tokens), %d sections DROPPED: %s",
                run_id,
                len(included),
                estimated_tokens,
                len(dropped),
                ", ".join(dropped_names),
            )
        else:
            logger.debug(
                "[%s] PromptBudget: %d sections included (%d tokens), all sections fit within budget (%d max)",
                run_id,
                len(included),
                estimated_tokens,
                self.max_tokens,
            )

        return assembled, included_names, dropped_names

    def get_diagnostics(self) -> dict:
        """
        Return a diagnostic dict of all registered sections.

        Useful for prompt snapshot testing and debugging.

        Returns
        -------
        dict
            Keys: section names. Values: dict with tier, chars, tokens, slot.
        """
        return {
            s.name: {
                "tier": s.tier.name,
                "chars": s.char_count,
                "tokens": s.estimated_tokens,
                "slot": s.slot,
            }
            for s in self._sections
        }


# ---------------------------------------------------------------------------
# Slot Constants — canonical positions in the prompt layout
# ---------------------------------------------------------------------------
# These constants define the fixed topology of the prompt. Each section
# is assigned a slot number that determines its position in the final
# assembled prompt, regardless of the order in which sections are added.


class Slot:
    """
    Fixed prompt slot positions.

    Lower number = earlier in the prompt (closer to the top).
    The layout is designed to exploit primacy/recency bias:
      - Slots 0-10: Primacy zone (identity, AC step, active constraints)
      - Slots 20-40: Middle zone (rules, RAG, history)
      - Slots 50-60: Recency zone (reasoning workflow, schema, human guidance)
    """

    PAGE_STATE = 0  # Deterministic ground truth from DOM
    SESSION_CONTEXT = 1  # URL, heading, navigation history
    IDENTITY = 2  # vQA identity + mission + credentials
    CURRENT_TASK = 4  # ★ AC step (moved to primacy zone)
    INPUT_VALUE = 5  # Mandatory fill value (if applicable)
    DROPDOWN_OPTIONS = 6  # Proactive dropdown option injection (TASK-013)
    ACTIVE_CONSTRAINTS = 8  # Failure diary, forbidden locators
    LEARNED_WORKFLOW = 10  # Human-recorded sequence override
    RECIPE_BLOCK = 12  # Matched YAML recipe
    GLOBAL_GUIDANCE = 14  # Operator pre-run context
    INSTRUCTION_PRIORITY = 16  # Priority ladder
    ROLE_CONSTRAINTS = 18  # Role-specific constraints
    CONTEXTUAL_RULES = 20  # Core + conditional rules
    LOCATOR_STRATEGY = 22  # Locator strategy rules
    AVAILABLE_ACTIONS = 24  # Action type reference
    FEW_SHOT_EXAMPLES = 26  # Selected few-shot examples
    GROUND_TRUTH_TESTS = 28  # Human-written Playwright tests
    GLOBAL_RUN_CONTEXT = 30  # Preflight KB articles
    RAG_CONTEXT = 32  # KB, selector hints, skills, PW RAG
    EXECUTION_HISTORY = 34  # Action history
    MEMORY = 36  # Long-term + persistent memory
    REASONING_WORKFLOW = 50  # Mandatory thought process
    SCHEMA_RULE = 52  # kb_acknowledgement requirement
    CRITICAL_GUIDANCE = 54  # Human intervention rules (recency)
    TRANSIENT_OBS = 56  # Transient page observation
    FINAL_REMINDER = 60  # Recency anchoring of golden rules (anchoring)


# ---------------------------------------------------------------------------
# TASK-080-P1C: Rolling Context Summarization
# ---------------------------------------------------------------------------


@dataclass
class SummarizationResult:
    """
    Result of a rolling context summarization attempt.

    Attributes:
        triggered: True when the summarization window fired and a summary
                   was generated. False when below the trigger threshold.
        summary_text: The compacted session summary wrapped in a
                      <session_summary> XML block. Empty string when
                      ``triggered`` is False.
    """

    triggered: bool = False
    summary_text: str = ""


class RollingContextSummarizer:
    """
    TASK-080-P1C: Rolling context summarizer for execution history.

    Fires every ``window_size`` planner iterations and replaces the
    verbatim action history with a compact <session_summary> digest,
    reducing token usage by ~50% for long-running test steps.

    Design Decision (conservative):
        Summarization is purely local (no extra LLM call). We extract
        the key patterns from the action history — successful actions,
        failed selectors, and net navigation state — in a structured
        format that preserves the information the planner needs.

    Feature flag: PROMPT_COMPRESSION_ENABLED (default true)
        When false, summarization is disabled and ``maybe_summarize()``
        always returns ``triggered=False``.

    Args:
        window_size: Number of planner iterations between summarization
                     triggers. Default 5.
        enabled: Feature flag. When False, never summarizes.
    """

    def __init__(self, window_size: int = 5, enabled: bool = True) -> None:
        self.window_size = max(1, window_size)
        self.enabled = enabled

    def maybe_summarize(
        self,
        action_history: list[dict],
        planner_iteration: int,
    ) -> SummarizationResult:
        """
        Summarize action history if the trigger window has been reached.

        Args:
            action_history: List of action dicts from the execution log.
                            Each dict has keys: action, strategy, role,
                            name, reasoning (+ optional error fields).
            planner_iteration: Current 1-based planner iteration count.

        Returns:
            SummarizationResult — triggered=True with summary_text when the
            window fires; triggered=False otherwise.

        Examples:
            >>> s = RollingContextSummarizer(window_size=5)
            >>> s.maybe_summarize(history, planner_iteration=4).triggered
            False
            >>> s.maybe_summarize(history, planner_iteration=5).triggered
            True
        """
        if not self.enabled:
            return SummarizationResult(triggered=False, summary_text="")

        # Fire at every multiple of window_size
        if planner_iteration == 0 or (planner_iteration % self.window_size) != 0:
            return SummarizationResult(triggered=False, summary_text="")

        if not action_history:
            return SummarizationResult(triggered=True, summary_text="<session_summary>No actions taken yet.</session_summary>")

        summary_text = self._build_summary(action_history, planner_iteration)
        return SummarizationResult(triggered=True, summary_text=summary_text)

    def _build_summary(self, history: list[dict], iteration: int) -> str:
        """
        Build a compact <session_summary> digest from action history.

        Extracts:
          - Count of successful vs. failed actions
          - Last 3 successful action descriptions
          - Any failed selectors (to avoid the planner repeating them)
          - Net navigation state (last navigate action destination)

        This is a local summarization (no LLM call). The output is
        designed to be injected as a compact history replacement.
        """
        successful: list[str] = []
        failed_selectors: list[str] = []
        last_url: str = ""

        for entry in history:
            action = entry.get("action", "")
            name = entry.get("name", "")
            role = entry.get("role", "")
            strategy = entry.get("strategy", "")
            reasoning = entry.get("reasoning", "")
            success = entry.get("success", True)  # default: assume success if unset

            if action == "navigate":
                last_url = entry.get("value", "") or name

            if not success:
                key = f"{action}/{strategy}/{role}/{name}".strip("/")
                if key not in failed_selectors:
                    failed_selectors.append(key)
            else:
                desc = f"{action}"
                if role:
                    desc += f" [{role}]"
                if name:
                    desc += f" '{name}'"
                if reasoning:
                    desc += f" — {reasoning[:60]}"
                successful.append(desc)

        total = len(history)
        success_count = len(successful)
        fail_count = total - success_count

        # Build compact digest lines
        lines = [
            f"Session at iteration {iteration} ({total} total actions, {success_count} ✓ / {fail_count} ✗):",
        ]

        if last_url:
            lines.append(f"  Current URL context: {last_url}")

        if successful:
            lines.append("  Last successful actions (newest first):")
            for desc in successful[-3:]:
                lines.append(f"    • {desc}")

        if failed_selectors:
            lines.append("  Failed selectors (DO NOT retry these):")
            for sel in failed_selectors[-5:]:
                lines.append(f"    ✗ {sel}")

        summary_body = "\n".join(lines)
        return f"<session_summary>\n{summary_body}\n</session_summary>"
