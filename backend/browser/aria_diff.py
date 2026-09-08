"""
backend/browser/aria_diff.py
==============================
TASK-080-P1B: ARIA Differential Diffing for FEAT-060 Prompt Compression.

Computes the delta between two ARIA tree text snapshots, transmitting only
changed nodes to the LLM planner instead of the full tree each turn.

This is Stage (a) of the Prompt Compression Pipeline (Item 2 in FEAT-060 spec).

Expected token reduction: 60–80% for pages where most DOM nodes are stable
(e.g., a data table where only 1–2 cells changed between planner turns).

Algorithm:
  1. Tokenize each ARIA tree into lines.
  2. Build a set of the previous tree's lines (O(n) lookup).
  3. Collect lines present in current but NOT in previous → changed/new lines.
  4. Emit changed lines as delta_text, wrapped in a <aria_delta> XML block.
  5. If delta is empty (no changes), set is_empty=True and return a minimal
     sentinel so the planner knows the page is stable.

Feature flag: PROMPT_COMPRESSION_ENABLED (default true)
  When false: delta_text = full current tree (baseline behavior).

Design: See TASK-080 Specification Item 2 (Stage a).
"""

import logging
from dataclasses import dataclass, field
from difflib import unified_diff

from backend.config import settings

logger = logging.getLogger(__name__)

# Prefix added to the delta block so the planner understands its semantics
_DELTA_HEADER = "<aria_delta>\n"
_DELTA_FOOTER = "\n</aria_delta>"
_UNCHANGED_SENTINEL = "<aria_delta><!-- no DOM changes since last turn --></aria_delta>"
_MAX_CONTEXT_LINES = 2  # lines of unchanged context around each changed line


# ---------------------------------------------------------------------------
# DiffResult data class
# ---------------------------------------------------------------------------


@dataclass
class DiffResult:
    """
    Result of an ARIA differential diff computation.

    Attributes:
        delta_text: The computed diff to send to the LLM. When ``is_empty``
                    is True this is the empty-change sentinel string.
        is_empty: True when no lines differ between previous and current tree.
        change_count: Number of lines that changed/were added.
    """

    delta_text: str = ""
    is_empty: bool = False
    change_count: int = 0


# ---------------------------------------------------------------------------
# AriaDiff
# ---------------------------------------------------------------------------


class AriaDiff:
    """
    ARIA accessibility tree differential diffing engine.

    Computes a compact delta between two ARIA tree text snapshots,
    reducing LLM input token usage by only transmitting changed nodes.

    Args:
        enabled: When False, ``compute_delta()`` returns the full current
                 tree as ``delta_text`` (baseline pre-FEAT-060 behavior).
    """

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    def compute_delta(self, previous_tree: str, current_tree: str) -> DiffResult:
        """
        Compute the differential delta between two ARIA tree snapshots.

        Args:
            previous_tree: The ARIA tree text from the previous planner turn.
                           Empty string on the first call (no previous state).
            current_tree: The ARIA tree text from the current planner turn.

        Returns:
            DiffResult with delta_text suitable for injection into the planner
            system prompt instead of the full current_tree.

        Examples:
            >>> differ = AriaDiff()
            >>> result = differ.compute_delta("", "button 'Submit'")
            >>> result.is_empty
            False
            >>> differ.compute_delta("a", "a").is_empty
            True
        """
        # Feature flag off → always return full tree
        if not self.enabled:
            return DiffResult(
                delta_text=current_tree,
                is_empty=(current_tree == ""),
                change_count=0 if current_tree == "" else 1,
            )

        # Edge: both empty
        if not previous_tree and not current_tree:
            return DiffResult(delta_text="", is_empty=True, change_count=0)

        # Edge: no previous tree (first call) → full current is the delta
        if not previous_tree:
            return DiffResult(
                delta_text=_DELTA_HEADER + current_tree + _DELTA_FOOTER,
                is_empty=False,
                change_count=len(current_tree.splitlines()),
            )

        # Edge: empty current tree
        if not current_tree:
            return DiffResult(
                delta_text=_UNCHANGED_SENTINEL,
                is_empty=True,
                change_count=0,
            )

        # Compute line-level diff using Python's difflib
        prev_lines = previous_tree.splitlines(keepends=True)
        curr_lines = current_tree.splitlines(keepends=True)

        try:
            diff_lines = list(
                unified_diff(
                    prev_lines,
                    curr_lines,
                    fromfile="prev",
                    tofile="curr",
                    n=_MAX_CONTEXT_LINES,
                )
            )
        except Exception as exc:
            # Malformed input — fall back to full tree
            logger.warning(
                "aria_diff: unified_diff failed (%s), falling back to full tree",
                str(exc)[:100],
            )
            return DiffResult(
                delta_text=_DELTA_HEADER + current_tree + _DELTA_FOOTER,
                is_empty=False,
                change_count=1,
            )

        # Count actual changes (lines starting with + or - excluding header)
        change_count = sum(
            1
            for line in diff_lines
            if line.startswith("+") or line.startswith("-")
            # Exclude the file header lines (--- / +++)
            if not line.startswith("---") and not line.startswith("+++")
        )

        if change_count == 0:
            return DiffResult(
                delta_text=_UNCHANGED_SENTINEL,
                is_empty=True,
                change_count=0,
            )

        # Build the delta text from changed lines only (filter out context markers)
        changed_lines = []
        for line in diff_lines:
            # Skip unified_diff header lines
            if line.startswith("---") or line.startswith("+++") or line.startswith("@@"):
                continue
            # Include added lines (strip the leading +) and context lines (strip space)
            if line.startswith("+"):
                changed_lines.append(line[1:].rstrip("\n"))
            elif line.startswith(" "):
                # Context line (unchanged, included for readability)
                changed_lines.append(line[1:].rstrip("\n"))
            # Lines starting with "-" are removed from current — skip them

        delta_body = "\n".join(changed_lines).strip()

        logger.debug(
            "aria_diff: prev=%d lines, curr=%d lines, delta=%d changes, delta_chars=%d (was %d)",
            len(prev_lines),
            len(curr_lines),
            change_count,
            len(delta_body),
            len(current_tree),
        )

        return DiffResult(
            delta_text=_DELTA_HEADER + delta_body + _DELTA_FOOTER,
            is_empty=False,
            change_count=change_count,
        )
