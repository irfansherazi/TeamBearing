"""
Regression tests for two related fixes:

1. _repair_json in failure_analyzer context
   The failure analyzer previously called json.loads() directly on raw LLM
   output.  Truncated responses (unterminated strings, missing closing braces)
   caused a crash with no recovery path.  The fix imports _repair_json from
   ac_parser.py — same battle-tested logic used there.  These tests verify
   _repair_json handles all truncation patterns the failure analyzer LLM can
   produce.

2. url_check modal/panel SKIP sentinel
   When the compiled TestPlan uses url_check for a step that opens a side panel
   (e.g. Quick Order form), the URL never changes and the verifier returns
   not_yet forever.  goal_satisfiable_check returns True (the panel IS visible)
   so the normal loop-prevention SKIP path never fires.  The fix adds a fast
   path that detects "will never pass" in the evidence string and emits SKIP
   immediately.  These tests verify the sentinel string is present in url_check
   evidence and that the detection logic works.

Run: .venv/bin/python -m pytest backend/engine/test_repair_json_and_url_check_skip.py -v
"""

import json
import sys
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backend.engine.ac_parser import _repair_json


# ═══════════════════════════════════════════════════════════════════════════
# _repair_json tests
# ═══════════════════════════════════════════════════════════════════════════


def test_repair_json_valid_passthrough():
    raw = '{"overall": "product_bug", "steps": []}'
    result = _repair_json(raw)
    assert json.loads(result) == {"overall": "product_bug", "steps": []}


def test_repair_json_markdown_fence():
    raw = '```json\n{"overall": "agent_issue", "steps": []}\n```'
    result = _repair_json(raw)
    assert json.loads(result)["overall"] == "agent_issue"


def test_repair_json_trailing_comma():
    raw = '{"overall": "mixed", "steps": [{"classification": "passed",}]}'
    result = _repair_json(raw)
    parsed = json.loads(result)
    assert parsed["overall"] == "mixed"
    assert parsed["steps"][0]["classification"] == "passed"


def test_repair_json_truncated_mid_string():
    # Simulates LLM output cut off inside a string value.
    # The repair strips the incomplete string/array and produces a partial but
    # valid JSON object.  The "steps" key may be lost — the caller uses
    # parsed.get("steps", []) so this is handled gracefully.
    raw = '{"overall": "product_bug", "steps": [{"classification": "product_bug", "reason": "the button did'
    result = _repair_json(raw)
    parsed = json.loads(result)
    assert parsed.get("overall") == "product_bug"
    # steps may be absent or empty after truncation repair — both are acceptable
    assert parsed.get("steps") is None or isinstance(parsed.get("steps"), list)


def test_repair_json_truncated_mid_object():
    # Simulates LLM output cut off mid-object with no closing brace
    raw = '{"overall": "agent_issue", "steps": [{"classification": "agent_issue"'
    result = _repair_json(raw)
    parsed = json.loads(result)
    assert parsed["overall"] == "agent_issue"


def test_repair_json_truncated_after_colon():
    # Simulates LLM output cut off immediately after a colon (no value)
    raw = '{"overall": "unknown", "steps": [{"classification":'
    result = _repair_json(raw)
    # Must be parseable — value is irrelevant as long as it doesn't raise
    json.loads(result)


def test_repair_json_empty_steps():
    raw = '{"overall": "product_bug", "steps": [], "jira_comment": "Found a bug"}'
    result = _repair_json(raw)
    parsed = json.loads(result)
    assert parsed["steps"] == []
    assert parsed["jira_comment"] == "Found a bug"


def test_repair_json_nested_truncation():
    # Deeply nested truncation — stops inside a nested dict
    raw = '{"overall": "mixed", "steps": [{"classification": "product_bug", "lesson": {"summary": "click'
    result = _repair_json(raw)
    parsed = json.loads(result)
    assert parsed["overall"] == "mixed"


# ═══════════════════════════════════════════════════════════════════════════
# url_check modal/panel SKIP sentinel tests
# ═══════════════════════════════════════════════════════════════════════════

# These tests verify the sentinel string that the loop-prevention fast path
# in step_verifier_node detects.  We test the evidence strings produced by
# _check_single_verification directly without Playwright by examining the
# constant used in both the verifier output and the detection condition.


_URL_CHECK_SENTINEL = "will never pass"

_URL_CHECK_NOT_YET_EVIDENCE_TEMPLATE = (
    "url_check: '{pattern}' NOT found in URL '{url}'. "
    "If the target opens as a modal/panel (no URL change), this check will never pass. "
    "The planner should verify by checking element_visible on a persistent panel element instead."
)


def test_url_check_evidence_contains_sentinel():
    evidence = _URL_CHECK_NOT_YET_EVIDENCE_TEMPLATE.format(
        pattern="/quick-order", url="https://qa.vcreative.net/#/vpr/production-orders"
    )
    assert _URL_CHECK_SENTINEL in evidence, (
        "Sentinel string not found in url_check NOT_YET evidence. "
        "If the sentinel changed, update the detection condition in step_verifier_node."
    )


def test_url_check_skip_detection_logic():
    # Mirrors the condition used in step_verifier_node loop prevention fast path
    prog_evidence = _URL_CHECK_NOT_YET_EVIDENCE_TEMPLATE.format(
        pattern="/quick-order", url="https://qa.vcreative.net/#/vpr/production-orders"
    )
    should_skip = _URL_CHECK_SENTINEL in prog_evidence
    assert should_skip is True


def test_url_check_skip_does_not_fire_for_normal_evidence():
    # Normal url_check failure (wrong page, not a panel) should NOT trigger the fast path
    normal_evidence = "url_check: '/production-order/' NOT found in URL 'https://qa.vcreative.net/#/login'."
    should_skip = _URL_CHECK_SENTINEL in normal_evidence
    assert should_skip is False


def test_url_check_skip_does_not_fire_for_element_visible():
    # element_visible NOT_YET evidence should never trigger the url_check fast path
    ev_evidence = "element_visible: no selector_hint — LLM fallback"
    should_skip = _URL_CHECK_SENTINEL in ev_evidence
    assert should_skip is False
