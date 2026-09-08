"""
vQA — Selector Registry & Keyword Completeness Tests
======================================================
Module: backend/kb/test_selector_completeness.py

Phase 1 TDD guard tests for TASK-001 (KB Refactor & Coverage Expansion).

These four tests validate that:
  1. Every entry in knowledge/selector_registry.json has a non-null,
     non-empty timing_note (AC-VERIFY-1).
  2. Every entry in knowledge/selector_registry.json has a non-empty
     context field (AC-VERIFY-1 regression guard).
  3. Every KEYWORDS line in knowledge/human_guidance.md has ≤ 8 terms
     (AC-VERIFY-6).
  4. Every KEYWORDS line in knowledge/vSuite-actions.md has ≤ 8 terms
     (AC-VERIFY-6).

All four tests are expected to FAIL before Phase 1 implementation runs.
After WI-001 through WI-004 complete, all four should pass.

Run:
    pytest backend/kb/test_selector_completeness.py -v
"""

import json
from pathlib import Path

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

_KNOWLEDGE_DIR = Path(__file__).parent.parent.parent / "knowledge"
_SELECTOR_REGISTRY_PATH = _KNOWLEDGE_DIR / "selector_registry.json"
_HUMAN_GUIDANCE_PATH = _KNOWLEDGE_DIR / "human_guidance.md"
# vSuite-actions.md was moved under knowledge/vpromedia/ as part of product-KB
# scoping (see backend/kb/loader.py._discover_kb_files).
_VSUITE_ACTIONS_PATH = _KNOWLEDGE_DIR / "vpromedia" / "vSuite-actions.md"

# ---------------------------------------------------------------------------
# Helper: load the selectors dict from selector_registry.json
# ---------------------------------------------------------------------------


def _load_selectors() -> dict:
    """Return the dict at selector_registry.json['selectors']."""
    with _SELECTOR_REGISTRY_PATH.open(encoding="utf-8") as fh:
        data = json.load(fh)
    return data["selectors"]


# ---------------------------------------------------------------------------
# Helper: parse KEYWORDS lines from a Markdown KB file
# ---------------------------------------------------------------------------


def _parse_keyword_lines(md_path: Path) -> list[tuple[str, list[str]]]:
    """
    Return a list of (workflow_name, [term, ...]) tuples for every
    KEYWORDS: line found in the given Markdown file.

    Workflow name is taken from the most recent '## WORKFLOW:' line above
    the KEYWORDS line.  Terms are split on commas and stripped of
    surrounding whitespace.
    """
    results: list[tuple[str, list[str]]] = []
    current_workflow = "<unknown>"

    with md_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if line.startswith("## WORKFLOW:"):
                current_workflow = line[len("## WORKFLOW:") :].strip()
            elif line.startswith("KEYWORDS:"):
                raw_terms = line[len("KEYWORDS:") :].strip()
                terms = [t.strip() for t in raw_terms.split(",") if t.strip()]
                results.append((current_workflow, terms))

    return results


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_all_selectors_have_timing_note():
    """
    AC-VERIFY-1: Every entry in selector_registry.json must have a
    non-null, non-empty timing_note.

    Before Phase 1 implementation this fails because 293 of 328 entries
    have timing_note == null.  After WI-001 fills them in it should pass.
    """
    selectors = _load_selectors()

    missing = [name for name, entry in selectors.items() if not entry.get("timing_note")]

    assert missing == [], f"{len(missing)} selector(s) are missing a timing_note.\nFirst 10 missing: {missing[:10]}"


def test_all_selectors_have_context():
    """
    AC-VERIFY-1 (regression guard): Every entry in selector_registry.json
    must have a non-empty context field.

    Before Phase 1 implementation this fails because 139 of 328 entries
    have context == "".  After WI-002 fills them in it should pass.
    """
    selectors = _load_selectors()

    missing = [name for name, entry in selectors.items() if not entry.get("context")]

    assert missing == [], f"{len(missing)} selector(s) are missing a context value.\nFirst 10 missing: {missing[:10]}"


def test_human_guidance_keyword_max_length():
    """
    AC-VERIFY-6: No KEYWORDS line in knowledge/human_guidance.md may have
    more than 8 comma-separated terms.

    Before Phase 1 implementation this fails because most of the 75 entries
    have 10-13 terms (filler words not yet stripped).  After WI-003 runs it
    should pass.
    """
    keyword_lines = _parse_keyword_lines(_HUMAN_GUIDANCE_PATH)

    violators = [(workflow, terms) for workflow, terms in keyword_lines if len(terms) > 8]

    assert violators == [], f"{len(violators)} KEYWORDS line(s) in human_guidance.md exceed 8 terms.\n" + "\n".join(
        f"  WORKFLOW '{wf}': {len(terms)} terms — {terms}" for wf, terms in violators[:5]
    )


def test_vsuite_actions_keyword_max_length():
    """
    AC-VERIFY-6: No KEYWORDS line in knowledge/vSuite-actions.md may have
    more than 8 comma-separated terms.

    Before Phase 1 implementation this fails because 51 of 103 entries have
    keyword bloat.  After WI-004 strips those entries it should pass.
    """
    keyword_lines = _parse_keyword_lines(_VSUITE_ACTIONS_PATH)

    violators = [(workflow, terms) for workflow, terms in keyword_lines if len(terms) > 8]

    assert violators == [], f"{len(violators)} KEYWORDS line(s) in vSuite-actions.md exceed 8 terms.\n" + "\n".join(
        f"  WORKFLOW '{wf}': {len(terms)} terms — {terms}" for wf, terms in violators[:5]
    )
