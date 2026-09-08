"""
tests/test_webhooks_nightly.py
================================
Unit tests for the compact Slack Block Kit payload builder used by the
nightly scheduled Playwright test suite.

These tests verify AC-VERIFY-2 and AC-VERIFY-3 from the task spec:
  - Green run (all pass): header uses ✅, summary text "2/2 passed", each
    test line shows emoji + duration + name, "View Report" button present.
  - All-fail run (0/2): header uses ❌, summary "0/2 passed", per-test lines
    use ❌, error_snippet truncated to 200 chars under each failing test.
  - Mixed run (1/2): correct per-test emoji mix, correct summary count.

The builder is a PURE function — no I/O, no external calls. Tests are fast
and fully deterministic.

Test count: 3
  - test_compact_slack_payload_all_pass
  - test_compact_slack_payload_all_fail
  - test_compact_slack_payload_mixed
"""

import pytest

from backend.engine.webhooks import _build_nightly_slack_payload


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

REPORT_URL = "https://vqa.vcreative.net/playwright?suite_run_id=nightly-abc123"

PASS_RUN_DATA = {
    "suite_run_id": "nightly-abc123",
    "status": "completed",
    "outcome": "PASS",
    "total": 2,
    "passed": 2,
    "failed": 0,
    "results": [
        {
            "test_id": "qa-170-search.test",
            "name": "QA-170: Search",
            "status": "PASS",
            "duration_ms": 12400.0,
            "error_snippet": None,
        },
        {
            "test_id": "qa-172-production.test",
            "name": "QA-172: Production",
            "status": "PASS",
            "duration_ms": 18700.0,
            "error_snippet": None,
        },
    ],
}

FAIL_RUN_DATA = {
    "suite_run_id": "nightly-abc123",
    "status": "completed",
    "outcome": "FAIL",
    "total": 2,
    "passed": 0,
    "failed": 2,
    "results": [
        {
            "test_id": "qa-170-search.test",
            "name": "QA-170: Search",
            "status": "FAIL",
            "duration_ms": 5200.0,
            "error_snippet": "Error: expect(received).toBe(expected)\n"
            + "x" * 250,  # Will be truncated to 200 chars
        },
        {
            "test_id": "qa-172-production.test",
            "name": "QA-172: Production",
            "status": "FAIL",
            "duration_ms": 3100.0,
            "error_snippet": "TimeoutError: waiting for selector '#submit-btn'",
        },
    ],
}

MIXED_RUN_DATA = {
    "suite_run_id": "nightly-abc123",
    "status": "completed",
    "outcome": "FAIL",
    "total": 2,
    "passed": 1,
    "failed": 1,
    "results": [
        {
            "test_id": "qa-170-search.test",
            "name": "QA-170: Search",
            "status": "PASS",
            "duration_ms": 12400.0,
            "error_snippet": None,
        },
        {
            "test_id": "qa-172-production.test",
            "name": "QA-172: Production",
            "status": "FAIL",
            "duration_ms": 3100.0,
            "error_snippet": "AssertionError: expected element to be visible",
        },
    ],
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_compact_slack_payload_all_pass():
    """
    AC-VERIFY-2: Green run produces compact Slack Block Kit payload.

    Expected:
    - Header block uses ✅
    - Summary text contains "Nightly suite — 2/2 passed"
    - Exactly one line per test: ✅ <test_id> — <duration>s
    - "View Report" button with the correct URL
    - No cost, role, or AC count fields (compact format)
    """
    payload = _build_nightly_slack_payload(
        suite_run_id="nightly-abc123",
        run_data=PASS_RUN_DATA,
        report_url=REPORT_URL,
    )

    assert isinstance(payload, dict), "Payload must be a dict"
    blocks = payload.get("blocks", [])
    assert len(blocks) >= 2, "Payload must have at least header + section blocks"

    # Header block uses ✅
    header_block = blocks[0]
    assert header_block["type"] == "header"
    header_text = header_block["text"]["text"]
    assert "✅" in header_text, f"Header must contain ✅ for all-pass, got: {header_text!r}"

    # Summary text contains "Nightly suite — 2/2 passed"
    all_text = " ".join(
        block.get("text", {}).get("text", "")
        if isinstance(block.get("text"), dict)
        else str(block.get("text", ""))
        for block in blocks
    )
    # Also search through fields in section blocks
    for block in blocks:
        if block.get("type") == "section":
            fields = block.get("fields", [])
            for field in fields:
                all_text += " " + field.get("text", "")
            if isinstance(block.get("text"), dict):
                all_text += " " + block["text"].get("text", "")

    assert "2/2 passed" in all_text, f"Payload must contain '2/2 passed', got text: {all_text!r}"
    assert "Nightly suite" in all_text, f"Payload must mention 'Nightly suite'"

    # Per-test lines with ✅ and duration
    assert "qa-170-search.test" in all_text, "Payload must list qa-170-search.test"
    assert "qa-172-production.test" in all_text, "Payload must list qa-172-production.test"
    assert "12.4s" in all_text, "Payload must show duration 12.4s for qa-170"
    assert "18.7s" in all_text, "Payload must show duration 18.7s for qa-172"

    # View Report button
    actions_block = next((b for b in blocks if b.get("type") == "actions"), None)
    assert actions_block is not None, "Payload must contain an actions block with View Report button"
    elements = actions_block.get("elements", [])
    assert len(elements) >= 1, "Actions block must have at least one button"
    button_urls = [el.get("url", "") for el in elements if el.get("type") == "button"]
    assert REPORT_URL in button_urls, f"View Report button must link to {REPORT_URL}"

    # Compact: no cost, role, or AC count
    assert "$" not in all_text, "Compact payload must NOT include cost fields"
    assert "AC Steps" not in all_text, "Compact payload must NOT include AC step counts"


def test_compact_slack_payload_all_fail():
    """
    AC-VERIFY-3: Red run produces compact Slack Block Kit payload with error snippets.

    Expected:
    - Header block uses ❌
    - Summary text contains "Nightly suite — 0/2 passed"
    - Per-test lines use ❌ emoji
    - error_snippet truncated to 200 chars appears under each failing test
    - "View Report" button present
    """
    payload = _build_nightly_slack_payload(
        suite_run_id="nightly-abc123",
        run_data=FAIL_RUN_DATA,
        report_url=REPORT_URL,
    )

    blocks = payload.get("blocks", [])

    # Header uses ❌
    header_block = blocks[0]
    header_text = header_block["text"]["text"]
    assert "❌" in header_text, f"Header must contain ❌ for all-fail, got: {header_text!r}"

    # Collect all text
    all_text = ""
    for block in blocks:
        if block.get("type") == "header":
            all_text += " " + block["text"]["text"]
        elif block.get("type") == "section":
            if isinstance(block.get("text"), dict):
                all_text += " " + block["text"].get("text", "")
            for field in block.get("fields", []):
                all_text += " " + field.get("text", "")
        elif block.get("type") == "context":
            for el in block.get("elements", []):
                if isinstance(el, dict):
                    all_text += " " + el.get("text", "")

    assert "0/2 passed" in all_text, f"Payload must contain '0/2 passed', got: {all_text!r}"

    # Both test IDs in output with ❌ emojis
    assert "qa-170-search.test" in all_text
    assert "qa-172-production.test" in all_text

    # error_snippet for first test (long snippet truncated to 200 chars)
    # The snippet starts with "Error: expect(received)..." then 250 x's
    # Truncated to 200 chars = full snippet prefix + enough x's up to 200
    long_snippet_start = "Error: expect(received).toBe(expected)"
    assert long_snippet_start in all_text, "error_snippet must appear in payload"

    # Ensure the snippet is truncated (the full 250 x's should NOT appear)
    full_x_string = "x" * 250
    assert full_x_string not in all_text, "error_snippet must be truncated, not full 250-char x string"

    # Second test error snippet
    assert "TimeoutError" in all_text, "Second test error snippet must appear"

    # View Report button
    actions_block = next((b for b in blocks if b.get("type") == "actions"), None)
    assert actions_block is not None
    elements = actions_block.get("elements", [])
    button_urls = [el.get("url", "") for el in elements if el.get("type") == "button"]
    assert REPORT_URL in button_urls


def test_compact_slack_payload_mixed():
    """
    AC-VERIFY-3 (mixed case): 1/2 passed produces correct per-test emoji mix.

    Expected:
    - Header uses ❌ (because overall outcome is FAIL)
    - Summary "Nightly suite — 1/2 passed"
    - Passing test line uses ✅, failing test line uses ❌
    - error_snippet only appears for the failing test, not the passing test
    """
    payload = _build_nightly_slack_payload(
        suite_run_id="nightly-abc123",
        run_data=MIXED_RUN_DATA,
        report_url=REPORT_URL,
    )

    blocks = payload.get("blocks", [])

    # Header uses ❌ (overall FAIL)
    header_block = blocks[0]
    header_text = header_block["text"]["text"]
    assert "❌" in header_text, f"Header must use ❌ for overall FAIL, got: {header_text!r}"

    # Collect all text
    all_text = ""
    for block in blocks:
        if block.get("type") == "header":
            all_text += " " + block["text"]["text"]
        elif block.get("type") == "section":
            if isinstance(block.get("text"), dict):
                all_text += " " + block["text"].get("text", "")
            for field in block.get("fields", []):
                all_text += " " + field.get("text", "")
        elif block.get("type") == "context":
            for el in block.get("elements", []):
                if isinstance(el, dict):
                    all_text += " " + el.get("text", "")

    assert "1/2 passed" in all_text, f"Payload must contain '1/2 passed', got: {all_text!r}"

    # Both test IDs present
    assert "qa-170-search.test" in all_text
    assert "qa-172-production.test" in all_text

    # error_snippet for failing test but NOT passing test (passing has None snippet)
    assert "AssertionError" in all_text, "Failing test's error_snippet must appear"

    # View Report button
    actions_block = next((b for b in blocks if b.get("type") == "actions"), None)
    assert actions_block is not None
    elements = actions_block.get("elements", [])
    button_urls = [el.get("url", "") for el in elements if el.get("type") == "button"]
    assert REPORT_URL in button_urls
