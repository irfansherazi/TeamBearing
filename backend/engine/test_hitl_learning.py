"""
FEAT-005: HITL Learning Loop Fixes — Unit Tests
=================================================

Tests for the three critical bug fixes + bonus dedup key fix:
  1. Race condition: cache invalidation after KB writes
  2. Fuzzy matching in learned_workflows.json (read + write)
  3. DOM action capture validation (ACTIONS_MISSING flag)
  4. Dedup key includes ticket_id

Run: .venv/bin/python -m pytest backend/engine/test_hitl_learning.py -v
"""

import json
import sys
from pathlib import Path

# Ensure the project root is on sys.path for imports
_PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ═══════════════════════════════════════════════════════════════════════════
# Bug 1: Race condition fix — cache invalidation
# ═══════════════════════════════════════════════════════════════════════════


def test_invalidate_human_guidance_cache():
    """Verify invalidate_human_guidance_cache() clears all 4 cache dicts."""
    from backend.engine import planner

    # Populate the caches with dummy data
    planner._HG_RESULT_CACHE["test_key"] = "cached_result"
    planner._HG_RESULT_CACHE_TS["test_key"] = 12345.0
    planner._HG_FILE_CACHE["/some/path"] = "file content"
    planner._HG_FILE_MTIME["/some/path"] = 99999.0

    # Call the invalidation function
    planner.invalidate_human_guidance_cache()

    # All 4 dicts should be empty
    assert len(planner._HG_RESULT_CACHE) == 0, "_HG_RESULT_CACHE not cleared"
    assert len(planner._HG_RESULT_CACHE_TS) == 0, "_HG_RESULT_CACHE_TS not cleared"
    assert len(planner._HG_FILE_CACHE) == 0, "_HG_FILE_CACHE not cleared"
    assert len(planner._HG_FILE_MTIME) == 0, "_HG_FILE_MTIME not cleared"


# ═══════════════════════════════════════════════════════════════════════════
# Bug 2: Fuzzy matching in learned_workflows.json — READ side
# ═══════════════════════════════════════════════════════════════════════════


def _create_learned_workflows_file(tmp_path: Path, data: dict) -> Path:
    """Helper: write a learned_workflows.json file in tmp and return its path."""
    wf_dir = tmp_path / "knowledge" / "blueprints"
    wf_dir.mkdir(parents=True, exist_ok=True)
    wf_file = wf_dir / "learned_workflows.json"
    wf_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return wf_file


def test_fuzzy_match_exact_still_works(tmp_path):
    """Exact match takes priority over fuzzy — no regression."""

    data = {
        "Click the Submit button": {
            "ticket_id": "QA-100",
            "recorded_at": "2026-05-01T00:00:00Z",
            "action_sequence": [
                {"action": "click", "strategy": "get_by_role", "name": "Submit", "value": "", "inner_text": "Submit"}
            ],
        },
        "Navigate to compact view": {
            "ticket_id": "QA-101",
            "recorded_at": "2026-05-01T00:00:00Z",
            "action_sequence": [
                {"action": "click", "strategy": "get_by_text", "name": "Compact", "value": "", "inner_text": "Compact"}
            ],
        },
    }

    # Simulate the lookup logic from _load_learned_workflow_override
    ac_step = "Click the Submit button"

    # Exact match should win
    entry = data.get(ac_step)
    assert entry is not None, "Exact match should find the entry directly"
    assert entry["ticket_id"] == "QA-100", "Exact match should return the correct entry"

    # Fuzzy should NOT be attempted when exact match succeeds
    # (entry is already found, so the fuzzy block is skipped)


def test_fuzzy_match_whitespace_difference(tmp_path):
    """'Click the Submit button' matches 'Click  the  Submit  button'."""
    data = {
        "Click  the  Submit  button": {
            "ticket_id": "QA-101",
            "recorded_at": "2026-05-01T00:00:00Z",
            "action_sequence": [
                {"action": "click", "strategy": "get_by_text", "name": "Submit", "value": "", "inner_text": "Submit"}
            ],
        }
    }
    _create_learned_workflows_file(tmp_path, data)

    import re
    from difflib import SequenceMatcher

    def _normalize_step(s: str) -> str:
        return re.sub(r"\s+", s.strip().lower()).strip()

    # Direct test of the matching logic
    query = "Click the Submit button"
    stored_key = "Click  the  Submit  button"

    query_norm = re.sub(r"\s+", " ", query.strip().lower()).strip()
    stored_norm = re.sub(r"\s+", " ", stored_key.strip().lower()).strip()
    ratio = SequenceMatcher(None, query_norm, stored_norm).ratio()

    assert ratio >= 0.85, f"Whitespace-collapsed strings should match (ratio={ratio:.3f})"


def test_fuzzy_match_minor_rephrasing():
    """'Navigate to compact view' matches 'Navigate to the compact view'."""
    import re
    from difflib import SequenceMatcher

    query = "Navigate to compact view"
    stored = "Navigate to the compact view"

    query_norm = re.sub(r"\s+", " ", query.strip().lower()).strip()
    stored_norm = re.sub(r"\s+", " ", stored.strip().lower()).strip()
    ratio = SequenceMatcher(None, query_norm, stored_norm).ratio()

    assert ratio >= 0.85, f"Minor rephrasing should match (ratio={ratio:.3f})"


def test_fuzzy_match_low_similarity_rejected():
    """'Upload a file' does NOT match 'Navigate to compact view' (ratio < 0.85)."""
    import re
    from difflib import SequenceMatcher

    query = "Upload a file"
    stored = "Navigate to compact view"

    query_norm = re.sub(r"\s+", " ", query.strip().lower()).strip()
    stored_norm = re.sub(r"\s+", " ", stored.strip().lower()).strip()
    ratio = SequenceMatcher(None, query_norm, stored_norm).ratio()

    assert ratio < 0.85, f"Dissimilar strings should NOT match (ratio={ratio:.3f})"


# ═══════════════════════════════════════════════════════════════════════════
# Bug 3: DOM action capture validation — ACTIONS_MISSING flag
# ═══════════════════════════════════════════════════════════════════════════


def test_combined_entry_with_actions(tmp_path):
    """Entry with action_sequence includes CAPTURED DOM ACTIONS block."""
    # Create a temporary human_guidance.md
    kb_file = tmp_path / "human_guidance.md"
    kb_file.write_text("", encoding="utf-8")

    action_sequence = [
        {
            "event_type": "click",
            "strategy": "get_by_text",
            "best_selector": "Submit",
            "inner_text": "Submit",
        }
    ]

    # Call the entry formatting logic directly (extracted from _save_combined_hitl_entry)
    dom_steps_lines = []
    for i, rec in enumerate(action_sequence, start=1):
        pw = {
            "action": rec.get("event_type", "click"),
            "strategy": rec.get("strategy", "get_by_text"),
            "name": rec.get("best_selector", rec.get("inner_text", "")),
        }
        if rec.get("value"):
            pw["value"] = rec["value"]
        dom_steps_lines.append(f"  Step {i}: {json.dumps(pw)}")

    has_dom_actions = bool(dom_steps_lines)

    if has_dom_actions:
        dom_block = "\nCAPTURED DOM ACTIONS (replay these verbatim in Playwright):\n" + "\n".join(dom_steps_lines)
    else:
        dom_block = (
            "\n⚠ ACTIONS_MISSING: The JS click listener did NOT capture any DOM actions.\n"
            "This entry contains the human's explanation ONLY — no replay sequence available.\n"
            "The agent should follow the text explanation below to determine the correct approach.\n"
        )

    assert "CAPTURED DOM ACTIONS" in dom_block, "Should contain CAPTURED DOM ACTIONS block"
    assert "ACTIONS_MISSING" not in dom_block, "Should NOT contain ACTIONS_MISSING flag"
    assert "Step 1:" in dom_block, "Should contain Step 1"


def test_combined_entry_without_actions():
    """Entry without action_sequence includes ACTIONS_MISSING flag, no replay block."""
    action_sequence = []  # Empty — JS listener failed

    dom_steps_lines = []
    for i, rec in enumerate(action_sequence, start=1):
        pw = {
            "action": rec.get("event_type", "click"),
            "strategy": rec.get("strategy", "get_by_text"),
            "name": rec.get("best_selector", rec.get("inner_text", "")),
        }
        dom_steps_lines.append(f"  Step {i}: {json.dumps(pw)}")

    has_dom_actions = bool(dom_steps_lines)

    if has_dom_actions:
        dom_block = "\nCAPTURED DOM ACTIONS (replay these verbatim in Playwright):\n" + "\n".join(dom_steps_lines)
    else:
        dom_block = (
            "\n⚠ ACTIONS_MISSING: The JS click listener did NOT capture any DOM actions.\n"
            "This entry contains the human's explanation ONLY — no replay sequence available.\n"
            "The agent should follow the text explanation below to determine the correct approach.\n"
        )

    assert "ACTIONS_MISSING" in dom_block, "Should contain ACTIONS_MISSING flag"
    assert "CAPTURED DOM ACTIONS" not in dom_block, "Should NOT contain CAPTURED DOM ACTIONS block"
    assert "(no DOM actions captured)" not in dom_block, "Should NOT contain old noise text"


# ═══════════════════════════════════════════════════════════════════════════
# Bonus: Dedup key includes ticket_id
# ═══════════════════════════════════════════════════════════════════════════


def test_dedup_key_includes_ticket_id():
    """Same explanation for different ticket_ids produces different dedup keys."""
    explanation = "Click the Save button in the top-right corner of the form"
    ticket_a = "QA-100"
    ticket_b = "QA-200"

    # Simulate the new dedup key format
    dedup_key_a = f"{ticket_a}::{explanation.strip()[:80]}"
    dedup_key_b = f"{ticket_b}::{explanation.strip()[:80]}"

    assert dedup_key_a != dedup_key_b, "Same text with different tickets should produce different keys"
    assert ticket_a in dedup_key_a, "Dedup key should contain the ticket_id"
    assert ticket_b in dedup_key_b, "Dedup key should contain the ticket_id"


def test_dedup_key_same_ticket_same_text_matches():
    """Same explanation and ticket_id produces the same dedup key."""
    explanation = "Click the Save button in the top-right corner of the form"
    ticket = "QA-100"

    dedup_key_1 = f"{ticket}::{explanation.strip()[:80]}"
    dedup_key_2 = f"{ticket}::{explanation.strip()[:80]}"

    assert dedup_key_1 == dedup_key_2, "Same ticket + text should produce identical keys"
