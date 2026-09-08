"""
Unit tests for backend/engine/computer_use.

These tests exercise the module surface WITHOUT hitting Bedrock or launching a
real browser. Anything that reaches those layers is proven live from
`/execute-cu` against QA-359, not here.
"""

from __future__ import annotations

import pytest

from backend.engine.computer_use.prompts import SYSTEM_PROMPT, build_user_message
from backend.engine.computer_use.runner import (
    _has_restart_intent,
    _initial_user_message,
    _is_scroll_click_turn,
    _is_wait_only_turn,
    _model_id,
    _prune_old_screenshots,
    _refresh_rolling_cache_point,
    _tool_config,
)
from backend.engine.computer_use.tools import TOOL_SCHEMAS, dispatch_tool


def test_tool_schemas_are_complete_and_well_formed():
    """Every tool has a valid Anthropic-style JSON-Schema input_schema, and
    the core roster is present. The set has grown from 11 to 14 as widget-
    specific tools (select2_pick, run_scripted_flow, lookup_selector) were
    added — use a subset assertion so future additions don't break this
    test while the required core is still guarded."""
    names = {t["name"] for t in TOOL_SCHEMAS}
    required_core = {
        "click", "click_at", "fill", "type_text", "select", "press",
        "navigate", "wait", "mark_step_status", "done", "request_help",
        "select2_pick", "run_scripted_flow", "lookup_selector",
    }
    assert required_core.issubset(names), (
        f"missing required tool schemas: {required_core - names}"
    )
    for t in TOOL_SCHEMAS:
        assert isinstance(t["description"], str) and t["description"]
        assert t["input_schema"]["type"] == "object"
        assert "properties" in t["input_schema"]


def test_bedrock_tool_config_shape():
    """Bedrock Converse expects toolSpec + inputSchema.json envelope."""
    cfg = _tool_config()
    assert "tools" in cfg
    assert len(cfg["tools"]) == len(TOOL_SCHEMAS)
    for t in cfg["tools"]:
        spec = t["toolSpec"]
        assert "name" in spec
        assert "description" in spec
        assert "inputSchema" in spec
        assert "json" in spec["inputSchema"]


def test_model_id_falls_back_to_heavy(monkeypatch):
    """VQA_CU_MODEL_ID env override wins, otherwise bedrock_model_id_heavy."""
    monkeypatch.delenv("VQA_CU_MODEL_ID", raising=False)
    mid = _model_id()
    assert "anthropic" in mid  # sanity — some Bedrock Anthropic inference profile

    monkeypatch.setenv("VQA_CU_MODEL_ID", "us.anthropic.claude-opus-4-20250514-v1:0")
    assert _model_id() == "us.anthropic.claude-opus-4-20250514-v1:0"


def test_system_prompt_is_short_and_names_all_tools():
    """The system prompt must stay reasonably tight and document every tool.
    Upper bound raised from 5000 to 10000 as the escalation ladder,
    widget contracts, and scripted-flow guidance were added — each earned
    their words by preventing observed runaway loops (see prompts.py
    module docstring and the QA-359 postmortem). Keep this test as a
    tripwire: crossing 10k means the prompt has drifted into RAG-in-prompt
    territory and should be pushed to keyword-triggered helper files."""
    assert 1000 < len(SYSTEM_PROMPT) < 10000, "system prompt should stay tight"
    for name in (
        "click", "click_at", "fill", "type_text", "select", "select2_pick",
        "press", "navigate", "wait", "mark_step_status",
        "lookup_selector", "run_scripted_flow", "done", "request_help",
    ):
        assert name in SYSTEM_PROMPT, f"tool {name!r} not documented in system prompt"


def test_build_user_message_includes_ac_and_context():
    msg = build_user_message("Given a widget, when I click, then the widget saves.", "https://app.example.com", "QA-359")
    assert "QA-359" in msg
    assert "app.example.com" in msg
    assert "Given a widget" in msg


@pytest.mark.asyncio
async def test_dispatch_tool_returns_help_sentinel_for_request_help():
    """request_help must surface a 'help' status to trigger HITL."""
    status, text = await dispatch_tool(page=None, name="request_help", args={"reason": "stuck"})
    assert status == "help"
    assert "stuck" in text


@pytest.mark.asyncio
async def test_dispatch_tool_returns_done_sentinel_for_done():
    status, text = await dispatch_tool(page=None, name="done", args={"summary": "form saved"})
    assert status == "done"
    assert "form saved" in text


@pytest.mark.asyncio
async def test_dispatch_tool_handles_unknown_tool_gracefully():
    status, text = await dispatch_tool(page=None, name="nonexistent_tool", args={})
    assert status == "ok"
    assert "unknown tool" in text.lower()


@pytest.mark.asyncio
async def test_click_at_converts_screenshot_pixels_to_css_pixels():
    """
    click_at is the whole point of this loop's coordinate-based fallback.
    Regression risk lives in the conversion: model outputs pixels in the
    *downsampled screenshot's* space, Playwright needs *CSS viewport* pixels.

    Simulated: 640px-wide screenshot backing a 1920px-wide CSS viewport (3x
    downsample). A model click at screenshot (100, 50) must dispatch to CSS
    (300, 150).
    """
    from types import SimpleNamespace

    calls: list[tuple[float, float]] = []

    class _FakeMouse:
        async def click(self, x, y):
            calls.append((x, y))

    fake_page = SimpleNamespace(
        mouse=_FakeMouse(),
        _vqa_click_meta={
            "screenshot_w": 640,
            "screenshot_h": 400,
            "viewport_w": 1920,
            "viewport_h": 1200,
        },
    )

    status, text = await dispatch_tool(
        page=fake_page,
        name="click_at",
        args={"x": 100, "y": 50, "reason": "Category dropdown"},
    )
    assert status == "ok"
    assert "click_at ok" in text
    assert len(calls) == 1
    css_x, css_y = calls[0]
    assert css_x == pytest.approx(300.0)
    assert css_y == pytest.approx(150.0)


def test_build_user_message_numbers_steps_when_provided():
    """When step texts are passed, they must be numbered starting at 0 so the
    indices line up with mark_step_status calls."""
    msg = build_user_message(
        "AC text",
        "https://app.example.com",
        "QA-359",
        steps=["Ghost in", "Click New PRF", "Fill required fields"],
    )
    assert "[0] Ghost in" in msg
    assert "[1] Click New PRF" in msg
    assert "[2] Fill required fields" in msg
    assert "mark_step_status" in msg  # cross-reference to the tool


def test_build_user_message_omits_step_block_when_steps_absent():
    """No steps → the numbered block must not appear (backward compatibility
    with callers that don't pass step lists)."""
    msg = build_user_message("AC text", "https://app.example.com", "QA-359")
    assert "Numbered AC steps" not in msg


def test_init_step_state_shape_matches_ws_ac_step():
    """The dicts produced by _init_step_state must be broadcast-ready
    (index, text, status='pending', error='', human_selector='') plus the
    ghost-login rail metadata (is_ghost_step, ghost_target — see the
    'Ghost-login enforcement' section in runner.py)."""
    from backend.engine.computer_use.runner import _init_step_state
    state = _init_step_state(["one", "two"])
    assert state == [
        {
            "index": 0, "text": "one", "status": "pending", "error": "",
            "human_selector": "", "is_ghost_step": False, "ghost_target": None,
        },
        {
            "index": 1, "text": "two", "status": "pending", "error": "",
            "human_selector": "", "is_ghost_step": False, "ghost_target": None,
        },
    ]


def test_init_step_state_tags_ghost_login_steps_with_target():
    """
    Any of the ghost-login phrasings the AC parser emits must be detected
    and the target user extracted so the runner rail can verify the
    top-right badge later. See the 'Ghost-login enforcement' section in
    runner.py for the failure mode this protects against.
    """
    from backend.engine.computer_use.runner import _init_step_state
    state = _init_step_state([
        "Click the New PRF button",                        # not a ghost step
        "Perform ghost login as Sales Person",             # canonical parser output
        "Ghost in as Sales Assistant",                     # short human phrasing
        "Ghost - Traffic Manager",                         # dash form
        "Ghost login as John Smith to test PRF creation",  # trailing qualifier stripped
        "Perform ghost login",                             # no target named
    ])
    assert [s["is_ghost_step"] for s in state] == [False, True, True, True, True, True]
    assert [s["ghost_target"] for s in state] == [
        None, "Sales Person", "Sales Assistant", "Traffic Manager", "John Smith", None,
    ]


def test_parse_ghost_target_returns_false_for_non_ghost_text():
    """Words like 'host' or 'login' alone must not trip the ghost detector."""
    from backend.engine.computer_use.runner import _parse_ghost_target
    for text in [
        "Click the Login button",
        "Log in with credentials",
        "Host the meeting as moderator",
        "",
    ]:
        is_ghost, target = _parse_ghost_target(text)
        assert is_ghost is False, f"false positive on {text!r}"
        assert target is None


def test_name_matches_badge_permissive_but_not_wildly_wrong():
    """Word-level match tolerates minor formatting differences but rejects
    a totally different persona (the failure mode QA-359 exhibited)."""
    from backend.engine.computer_use.runner import _name_matches_badge
    # Full substring
    assert _name_matches_badge("Sales Person", "SP - Sales Person") is True
    # Word-level fallback
    assert _name_matches_badge("Sales Person", "Currently viewing as: Person, Sales") is True
    # Case + whitespace tolerance
    assert _name_matches_badge("Sales Person", "sales     person") is True
    # Wrong persona — the exact bug we're preventing
    assert _name_matches_badge("Sales Person", "Admin User admin@vcreativeinc.com") is False
    # Empty inputs → not a match
    assert _name_matches_badge("", "Sales Person") is False
    assert _name_matches_badge("Sales Person", "") is False


@pytest.mark.asyncio
async def test_verify_ghost_switch_rejects_when_badge_still_admin():
    """
    Simulate the QA-359 signature: model claims 'already ghosting as Sales
    Person' but the top-right badge still shows the admin. _verify_ghost_switch
    must return (verified=False, badge_text, target='Sales Person').
    """
    from types import SimpleNamespace
    from backend.engine.computer_use.runner import _verify_ghost_switch

    async def _fake_evaluate(js):
        return "Admin User | admin@vcreativeinc.com | Sign Out"

    fake_page = SimpleNamespace(evaluate=_fake_evaluate)
    verified, badge, target = await _verify_ghost_switch(
        fake_page, "Perform ghost login as Sales Person", admin_email="admin@vcreativeinc.com",
    )
    assert verified is False
    assert target == "Sales Person"
    assert "Admin User" in badge


@pytest.mark.asyncio
async def test_verify_ghost_switch_passes_when_badge_shows_target():
    """Happy path — badge shows the target user's name → verified=True."""
    from types import SimpleNamespace
    from backend.engine.computer_use.runner import _verify_ghost_switch

    async def _fake_evaluate(js):
        return "Now viewing as: Sales Person | Return to admin"

    fake_page = SimpleNamespace(evaluate=_fake_evaluate)
    verified, _, _ = await _verify_ghost_switch(
        fake_page, "Ghost login as Sales Person", admin_email="admin@vcreativeinc.com",
    )
    assert verified is True


@pytest.mark.asyncio
async def test_verify_ghost_switch_fails_open_on_empty_badge_read():
    """
    Infra glitch: JS evaluate returns empty string (headless timing, DOM
    not ready). The rail must fail-OPEN in that case — a broken screenshot
    pipeline should not block runs. The runner comment on
    _read_top_right_badge_text explains this policy.
    """
    from types import SimpleNamespace
    from backend.engine.computer_use.runner import _verify_ghost_switch

    async def _fake_evaluate(js):
        return ""

    fake_page = SimpleNamespace(evaluate=_fake_evaluate)
    verified, badge, _ = await _verify_ghost_switch(
        fake_page, "Ghost login as Sales Person", admin_email="admin@vcreativeinc.com",
    )
    assert verified is True
    assert badge == ""


@pytest.mark.asyncio
async def test_verify_ghost_switch_untargeted_step_fails_open():
    """
    When the step names no target ('Perform ghost login'), we don't have
    a strong signal — the admin email's local-part is a common substring
    in header UI ('Return to admin' links). Rail policy in this case is
    fail-open (verified=True). The docstring on _verify_ghost_switch
    documents this trade-off. In practice the AC parser overwhelmingly
    emits the 'as X' form, so this branch is rare.
    """
    from types import SimpleNamespace
    from backend.engine.computer_use.runner import _verify_ghost_switch

    async def _any_badge(js):
        return "some badge text"

    verified, _, target = await _verify_ghost_switch(
        SimpleNamespace(evaluate=_any_badge), "Perform ghost login",
        admin_email="admin@vcreativeinc.com",
    )
    assert verified is True
    assert target is None


def test_init_step_state_dedupes_normalized_text_and_renumbers():
    """
    QA-359 regression: the AC parser legitimately emits 58 steps for a
    ticket with 4 test scenarios that share setup steps ("Authenticate…",
    "Click New PRF", "Click Save"). The runner dedupes so the UI list
    collapses to unique rows, indices are recomputed contiguously, and
    the model's mark_step_status indices still line up with rendered rows.
    """
    from backend.engine.computer_use.runner import _init_step_state
    state = _init_step_state([
        "Authenticate and ghost-login as Sales Person",  # kept
        "Click New PRF button",                          # kept
        "  authenticate and GHOST-login as Sales Person  ",  # dropped (case+ws)
        "Click Save button",                             # kept
        "Click New PRF button",                          # dropped (exact repeat)
        "",                                               # dropped (empty)
        "   ",                                            # dropped (whitespace)
        "Click Save button",                             # dropped (exact repeat)
        "Verify success toast",                          # kept
    ])
    assert [s["text"] for s in state] == [
        "Authenticate and ghost-login as Sales Person",
        "Click New PRF button",
        "Click Save button",
        "Verify success toast",
    ]
    # Indices are re-numbered contiguously — the model's mark_step_status(index=N)
    # must correspond to the row's position after dedupe, not the position in
    # the raw input.
    assert [s["index"] for s in state] == [0, 1, 2, 3]


def test_init_step_state_handles_non_string_gracefully():
    """Non-string entries (e.g., None from a JSON round-trip) must not crash."""
    from backend.engine.computer_use.runner import _init_step_state
    state = _init_step_state(["real step", None, 42, "another step"])  # type: ignore[list-item]
    assert [s["text"] for s in state] == ["real step", "another step"]


def test_apply_step_update_marks_and_returns_change_flag():
    from backend.engine.computer_use.runner import _apply_step_update, _init_step_state
    state = _init_step_state(["a", "b"])

    assert _apply_step_update(state, 0, "in_progress") is True
    assert state[0]["status"] == "in_progress"

    # Applying the same status twice is a no-op — save the broadcast.
    assert _apply_step_update(state, 0, "in_progress") is False

    # Out-of-range index is silently ignored.
    assert _apply_step_update(state, 99, "passed") is False


def test_apply_step_update_populates_error_on_failed():
    from backend.engine.computer_use.runner import _apply_step_update, _init_step_state
    state = _init_step_state(["step-1"])
    _apply_step_update(state, 0, "failed", note="validation did not fire")
    assert state[0]["status"] == "failed"
    assert state[0]["error"] == "validation did not fire"


def test_finalize_step_state_marks_all_passed_on_done():
    from backend.engine.computer_use.runner import _apply_step_update, _finalize_step_state, _init_step_state
    state = _init_step_state(["a", "b", "c"])
    _apply_step_update(state, 0, "passed")
    _apply_step_update(state, 1, "in_progress")
    _finalize_step_state(state, "done")
    assert [s["status"] for s in state] == ["passed", "passed", "passed"]


def test_is_browser_gone_matches_expected_error_messages():
    """
    The runner must recognize every Playwright variant that means
    'the browser went away' — not just TargetClosedError. Otherwise
    a manually-closed Chromium window (headed mode) surfaces as
    status=error instead of status=cancelled.
    """
    from backend.engine.computer_use.runner import _is_browser_gone
    # Real Playwright message shapes observed in QA-359 log:
    assert _is_browser_gone(RuntimeError("Page.screenshot: Target page, context or browser has been closed"))
    assert _is_browser_gone(RuntimeError("Browser has been closed"))
    assert _is_browser_gone(RuntimeError("Execution context was destroyed"))
    assert _is_browser_gone(RuntimeError("connection closed"))
    # False for unrelated errors — must not swallow real bugs.
    assert not _is_browser_gone(RuntimeError("selector not found"))
    assert not _is_browser_gone(RuntimeError("timeout waiting for element"))


def test_is_cancelled_reads_routes_cancel_set():
    """
    Cancel signal roundtrip: adding a run_id to routes._cancelled_runs must
    make _is_cancelled(run_id) return True; discarding it must reset.
    """
    from backend.api.routes import _cancelled_runs
    from backend.engine.computer_use.runner import _discard_cancel, _is_cancelled

    run_id = "cu-test-cancel-abc"
    assert _is_cancelled(run_id) is False
    _cancelled_runs.add(run_id)
    try:
        assert _is_cancelled(run_id) is True
        _discard_cancel(run_id)
        assert _is_cancelled(run_id) is False
    finally:
        _cancelled_runs.discard(run_id)


def test_finalize_step_state_marks_in_progress_failed_on_cap():
    """Iteration cap / timeout / error: leftover in_progress becomes failed
    with a diagnostic error, remaining pending stays pending. This is the
    lifecycle safety net the user asked for."""
    from backend.engine.computer_use.runner import _apply_step_update, _finalize_step_state, _init_step_state
    state = _init_step_state(["a", "b", "c"])
    _apply_step_update(state, 0, "passed")
    _apply_step_update(state, 1, "in_progress")
    _finalize_step_state(state, "cap")
    assert state[0]["status"] == "passed"
    assert state[1]["status"] == "failed"
    assert "cap" in state[1]["error"]
    assert state[2]["status"] == "pending"


@pytest.mark.asyncio
async def test_mark_step_status_stages_update_on_page():
    """The tool handler is a passthrough — it stages the update on
    page._vqa_ac_update for the runner to drain. No broadcast from the tool
    itself (the handler has no run_id)."""
    from types import SimpleNamespace
    fake_page = SimpleNamespace()
    status, text = await dispatch_tool(
        page=fake_page,
        name="mark_step_status",
        args={"index": 2, "status": "passed", "note": "verified"},
    )
    assert status == "ok"
    assert "marked step 2 as passed" in text
    assert fake_page._vqa_ac_update == {"index": 2, "status": "passed", "note": "verified"}


@pytest.mark.asyncio
async def test_mark_step_status_rejects_invalid_status():
    from types import SimpleNamespace
    fake_page = SimpleNamespace()
    status, text = await dispatch_tool(
        page=fake_page,
        name="mark_step_status",
        args={"index": 0, "status": "not_a_real_status"},
    )
    assert status == "ok"
    assert "must be one of" in text
    # No staged update on invalid input
    assert not hasattr(fake_page, "_vqa_ac_update") or fake_page._vqa_ac_update is None


@pytest.mark.asyncio
async def test_click_at_falls_back_to_identity_without_metadata():
    """
    If the screenshot helper hasn't stashed metadata yet (defensive path),
    click_at must NOT crash — it treats model coords as already-CSS.
    """
    from types import SimpleNamespace

    calls: list[tuple[float, float]] = []

    class _FakeMouse:
        async def click(self, x, y):
            calls.append((x, y))

    fake_page = SimpleNamespace(mouse=_FakeMouse())  # no _vqa_click_meta

    status, text = await dispatch_tool(
        page=fake_page,
        name="click_at",
        args={"x": 250, "y": 75, "reason": "no meta"},
    )
    assert status == "ok"
    assert calls == [(250.0, 75.0)]
    assert "no screenshot metadata" in text


# ---------------------------------------------------------------------------
# Backpressure classifiers — three anti-pattern detectors observed on
# QA-359 that the runner uses to inject inline warnings to the model.
# ---------------------------------------------------------------------------


def test_is_wait_only_turn_matches_all_wait_and_only_wait():
    """A pure wait-only turn triggers wait-loop backpressure."""
    assert _is_wait_only_turn([{"name": "wait", "input": {"seconds": 2}}])
    assert _is_wait_only_turn([
        {"name": "wait", "input": {"seconds": 1}},
        {"name": "wait", "input": {"seconds": 3}},
    ])
    # Any productive tool mixed in resets the pattern.
    assert not _is_wait_only_turn([
        {"name": "wait", "input": {"seconds": 2}},
        {"name": "click", "input": {"target": "Save"}},
    ])
    # Empty turn is not wait-only (defensive — no false positive when the
    # model returns text-only and the runner enters the nudge branch).
    assert not _is_wait_only_turn([])


def test_is_scroll_click_turn_requires_click_at_with_scroll_reason():
    """click_at turns whose reason mentions scrolling trigger scroll-loop backpressure."""
    assert _is_scroll_click_turn([
        {"name": "click_at", "input": {"x": 1274, "y": 650, "reason": "Scroll down to view more fields"}},
    ])
    # Case-insensitive on the reason substring.
    assert _is_scroll_click_turn([
        {"name": "click_at", "input": {"x": 1274, "y": 650, "reason": "SCROLL up slightly"}},
    ])
    # click_at without a scroll reason does NOT trigger (semantic scroll must
    # be the stated intent — legitimate coordinate clicks are fine).
    assert not _is_scroll_click_turn([
        {"name": "click_at", "input": {"x": 500, "y": 400, "reason": "Click Save button"}},
    ])
    # A non-click_at tool breaks the pattern immediately.
    assert not _is_scroll_click_turn([
        {"name": "click", "input": {"target": "Save"}},
    ])
    # Mixed click_at + non-click_at → False (any productive tool resets).
    assert not _is_scroll_click_turn([
        {"name": "click_at", "input": {"x": 1274, "y": 650, "reason": "Scroll down"}},
        {"name": "press", "input": {"key": "Tab"}},
    ])


def test_has_restart_intent_matches_reason_and_target_broadly():
    """Restart-intent lexicon fires on either reason or target field, case-insensitively."""
    # Reason field on click_at — the QA-359 iter 165 case exactly.
    assert _has_restart_intent([
        {"name": "click_at", "input": {"x": 91, "y": 242, "reason": "Click New PRF button to restart form"}},
    ])
    # Reason with "start over".
    assert _has_restart_intent([
        {"name": "click_at", "input": {"x": 100, "y": 100, "reason": "Start over with a fresh form"}},
    ])
    # target field on click — model could also articulate intent there.
    assert _has_restart_intent([
        {"name": "click", "input": {"target": "restart the form", "hint": "text"}},
    ])
    # A benign "New PRF" click (initial open, not restart) should NOT fire —
    # the lexicon requires the "restart" qualifier or equivalent, not the
    # bare phrase "new prf".
    assert not _has_restart_intent([
        {"name": "click", "input": {"target": "+ New PRF"}},
    ])
    # No reason/target at all → False (defensive).
    assert not _has_restart_intent([{"name": "wait", "input": {"seconds": 2}}])


# ---------------------------------------------------------------------------
# tool_fill contenteditable fallback — the QA-359 fill(*:focus) → span.tasp
# failure mode observed repeatedly in run-55f70989 (iters 191, 202, 204).
# ---------------------------------------------------------------------------


class _FakeContentEditableLocator:
    """Locator that reports itself as a span.tasp contenteditable."""
    def __init__(self, record: dict):
        self._record = record

    async def evaluate(self, script, timeout=None):
        self._record["evaluated"] = True
        return {
            "tag": "span",
            "isContentEditable": True,
            "classes": "tasp form-control",
            "isTasp": True,
        }

    async def click(self, timeout=None):
        self._record["clicked"] = True

    async def fill(self, value, timeout=None):
        self._record["fill_direct"] = value


class _FakePlainInputLocator:
    """Locator that reports itself as a plain <input>."""
    def __init__(self, record: dict):
        self._record = record

    async def evaluate(self, script, timeout=None):
        self._record["evaluated"] = True
        return {
            "tag": "input",
            "isContentEditable": False,
            "classes": "form-control",
            "isTasp": False,
        }

    async def click(self, timeout=None):
        self._record["clicked"] = True

    async def fill(self, value, timeout=None):
        self._record["fill_direct"] = value


class _FakeLocatorParent:
    def __init__(self, leaf):
        self.first = leaf


class _FakeKeyboard:
    def __init__(self):
        self.pressed: list[str] = []
        self.typed: list[str] = []

    async def press(self, key):
        self.pressed.append(key)

    async def type(self, value):
        self.typed.append(value)


@pytest.mark.asyncio
async def test_fill_auto_falls_back_to_keyboard_type_on_contenteditable():
    """
    Regression: vPromotions Description / Play Copy / Prize Info / Liner
    Copy / Liner Notes are `<span class="tasp">` contenteditables.
    Playwright's `.fill()` throws "Element is not an <input>" on these.
    Rather than surface that error and force the model to redispatch as
    ~30 press() calls, tool_fill pre-checks the element type and internally
    dispatches click-to-focus + keyboard.type. This test locks in that
    behavior so a future refactor cannot silently regress.
    """
    from types import SimpleNamespace

    record: dict[str, Any] = {}
    leaf = _FakeContentEditableLocator(record)
    parent = _FakeLocatorParent(leaf)
    kb = _FakeKeyboard()
    fake_page = SimpleNamespace(
        keyboard=kb,
        locator=lambda selector: parent,
        get_by_label=lambda t: parent,
        get_by_placeholder=lambda t: parent,
        get_by_role=lambda r, name=None: parent,
    )

    status, text = await dispatch_tool(
        page=fake_page,
        name="fill",
        args={
            "target": "span.tasp[id$='_description_tasp']",
            "hint": "css",
            "value": "Test description for QA-359",
        },
    )
    assert status == "ok"
    assert record.get("evaluated") is True, "pre-check evaluate must run before dispatching"
    assert record.get("clicked") is True, "fallback path must click to focus first"
    assert "fill_direct" not in record, ".fill() must NOT be called on contenteditable"
    assert kb.typed == ["Test description for QA-359"], "value must be typed via keyboard"
    # Clear-before-type: Control+a and Delete keep the fill idempotent.
    assert "Control+a" in kb.pressed
    assert "Delete" in kb.pressed
    assert "keyboard.type" in text or "contenteditable" in text


@pytest.mark.asyncio
async def test_fill_uses_direct_playwright_fill_on_plain_input():
    """
    Non-regression: the contenteditable fallback must NOT hijack normal
    input fills. For a plain <input>, tool_fill still dispatches
    `loc.first.fill(value)` — no click, no keyboard.type.
    """
    from types import SimpleNamespace

    record: dict[str, Any] = {}
    leaf = _FakePlainInputLocator(record)
    parent = _FakeLocatorParent(leaf)
    kb = _FakeKeyboard()
    fake_page = SimpleNamespace(
        keyboard=kb,
        locator=lambda selector: parent,
        get_by_label=lambda t: parent,
        get_by_placeholder=lambda t: parent,
        get_by_role=lambda r, name=None: parent,
    )

    status, text = await dispatch_tool(
        page=fake_page,
        name="fill",
        args={
            "target": "#prf_form_rightview input[id$='_title']",
            "hint": "css",
            "value": "QA-359 Test PRF",
        },
    )
    assert status == "ok"
    assert record.get("fill_direct") == "QA-359 Test PRF"
    assert "clicked" not in record, "plain input fill must not click to focus first"
    assert kb.typed == [], "plain input fill must not touch the keyboard"
    assert "filled" in text


# ---------------------------------------------------------------------------
# Rolling cache breakpoint + batched pruning
# ---------------------------------------------------------------------------
#
# The rolling breakpoint is the difference between paying $2/M for the entire
# growing conversation on every turn (pre-fix behavior on QA-359 → $20 cap)
# and paying ~$0.20/M for the prior tail (~10× cheaper). These tests pin the
# invariants that make it work:
#   - The initial-user cachePoint (BEFORE the initial screenshot) is never
#     touched by the rolling helper.
#   - Exactly ONE rolling breakpoint exists at any time (we never exhaust
#     the 4-breakpoint Bedrock budget).
#   - Batched pruning is a no-op inside the accumulation window and only
#     mutates when it MUST — that's the property that keeps the cached
#     prefix stable across turns.


def _fake_tool_result_user_msg(tool_use_id: str, text: str, image_bytes: bytes | None = None) -> dict:
    """Minimal tool-result user message in Bedrock Converse shape."""
    content: list[dict] = []
    result_content: list[dict] = [{"text": text}]
    if image_bytes is not None:
        result_content.append({"image": {"format": "png", "source": {"bytes": image_bytes}}})
    content.append({
        "toolResult": {
            "toolUseId": tool_use_id,
            "content": result_content,
            "status": "success",
        }
    })
    return {"role": "user", "content": content}


def test_refresh_rolling_cache_point_adds_marker_to_tail_tool_result():
    """Rolling breakpoint goes at the END of the most recent toolResult user turn."""
    messages = [
        _initial_user_message("hello", b"\x89PNG\r\n\x1a\n"),
        {"role": "assistant", "content": [{"text": "ok"}]},
        _fake_tool_result_user_msg("tu-1", "clicked", image_bytes=b"\x89PNG\r\n\x1a\n"),
    ]

    _refresh_rolling_cache_point(messages)

    tail_content = messages[-1]["content"]
    # Last block is the fresh rolling breakpoint
    assert isinstance(tail_content[-1], dict)
    assert "cachePoint" in tail_content[-1]
    # ToolResult is still present (breakpoint appended, not replaced)
    assert any("toolResult" in b for b in tail_content)


def test_refresh_rolling_cache_point_never_touches_initial_user_marker():
    """
    The initial-user cachePoint sits BETWEEN text and image (not at the end)
    and never has a sibling toolResult in its message. It must survive
    every call to _refresh_rolling_cache_point untouched — otherwise we
    lose the second of the two static breakpoints.
    """
    initial = _initial_user_message("hello", b"\x89PNG\r\n\x1a\n")
    initial_content_before = list(initial["content"])  # shallow-copy for comparison
    messages = [
        initial,
        {"role": "assistant", "content": [{"text": "ok"}]},
        _fake_tool_result_user_msg("tu-1", "clicked"),
    ]

    _refresh_rolling_cache_point(messages)

    # Initial user content unchanged: same shape, same order, same cachePoint position
    assert messages[0]["content"] == initial_content_before


def test_refresh_rolling_cache_point_moves_marker_forward_across_calls():
    """
    Simulate three iterations of the loop:
      iter 1: place marker on user_1
      iter 2: append assistant_2 + user_2, place marker on user_2 (removes user_1's)
      iter 3: append assistant_3 + user_3, place marker on user_3 (removes user_2's)
    Invariant: at each call, exactly ONE rolling breakpoint exists (on the tail).
    """
    def count_rolling_markers(msgs: list[dict]) -> int:
        n = 0
        for m in msgs:
            if m.get("role") != "user":
                continue
            content = m.get("content") or []
            if not any(isinstance(b, dict) and "toolResult" in b for b in content):
                continue
            if content and isinstance(content[-1], dict) and "cachePoint" in content[-1]:
                n += 1
        return n

    messages = [
        _initial_user_message("hello", b"\x89PNG\r\n\x1a\n"),
        {"role": "assistant", "content": [{"text": "a1"}]},
        _fake_tool_result_user_msg("tu-1", "r1"),
    ]
    _refresh_rolling_cache_point(messages)
    assert count_rolling_markers(messages) == 1

    messages.append({"role": "assistant", "content": [{"text": "a2"}]})
    messages.append(_fake_tool_result_user_msg("tu-2", "r2"))
    _refresh_rolling_cache_point(messages)
    assert count_rolling_markers(messages) == 1
    # Marker is on the NEW tail, not the old one
    assert "cachePoint" in messages[-1]["content"][-1]
    assert not any("cachePoint" in b for b in messages[-3]["content"] if isinstance(b, dict))

    messages.append({"role": "assistant", "content": [{"text": "a3"}]})
    messages.append(_fake_tool_result_user_msg("tu-3", "r3"))
    _refresh_rolling_cache_point(messages)
    assert count_rolling_markers(messages) == 1
    assert "cachePoint" in messages[-1]["content"][-1]


def test_refresh_rolling_cache_point_is_idempotent_within_a_turn():
    """Called twice back-to-back, doesn't double-stack the marker on the tail."""
    messages = [
        _initial_user_message("hello", b"\x89PNG\r\n\x1a\n"),
        {"role": "assistant", "content": [{"text": "a"}]},
        _fake_tool_result_user_msg("tu-1", "r"),
    ]

    _refresh_rolling_cache_point(messages)
    _refresh_rolling_cache_point(messages)

    tail_content = messages[-1]["content"]
    marker_count = sum(1 for b in tail_content if isinstance(b, dict) and "cachePoint" in b)
    assert marker_count == 1


def test_refresh_rolling_cache_point_noop_when_tail_is_assistant():
    """
    Between "response arrived" and "tool_result appended", the tail is an
    assistant message. Refresh must not add a breakpoint there — the next
    Bedrock call would send an assistant-tail request, which is invalid.
    """
    messages = [
        _initial_user_message("hello", b"\x89PNG\r\n\x1a\n"),
        {"role": "assistant", "content": [{"text": "a"}]},
    ]

    _refresh_rolling_cache_point(messages)

    # Assistant tail unchanged
    assert messages[-1] == {"role": "assistant", "content": [{"text": "a"}]}


def _msg_with_image() -> dict:
    """Fake user turn with one image block, for pruning tests."""
    return _fake_tool_result_user_msg("tu-x", "clicked", image_bytes=b"\x89PNG\r\n\x1a\n")


def test_prune_batched_is_noop_below_batch_threshold():
    """
    With prune_batch=6 and keep=4, we should NOT prune until total images > 10.
    Between events the message-token sequence is stable — this is the
    property that makes the rolling cache breakpoint useful.
    """
    # 8 images total = 4 keep + 4 batch → below the 4+6=10 threshold, no-op
    messages = [_msg_with_image() for _ in range(8)]

    n_pruned = _prune_old_screenshots(messages, keep_last_n=4, prune_batch=6)

    assert n_pruned == 0
    # Every message still has its image block
    for m in messages:
        assert any("image" in sub for b in m["content"] for sub in b["toolResult"]["content"] if isinstance(sub, dict))


def test_prune_batched_fires_when_batch_threshold_crossed():
    """
    Once total > keep + batch, prune down to keep_last_n in one shot.
    """
    # 11 images total = crosses 4+6=10 threshold → prune down to 4 in one shot
    messages = [_msg_with_image() for _ in range(11)]

    n_pruned = _prune_old_screenshots(messages, keep_last_n=4, prune_batch=6)

    # Pruned 7 to get from 11 down to 4
    assert n_pruned == 7
    # Tail 4 keep their image blocks; oldest 7 became placeholders
    remaining_images = 0
    placeholders = 0
    for m in messages:
        for b in m["content"]:
            for sub in b["toolResult"]["content"]:
                if isinstance(sub, dict):
                    if "image" in sub:
                        remaining_images += 1
                    elif "text" in sub and "Screenshot pruned" in sub.get("text", ""):
                        placeholders += 1
    assert remaining_images == 4
    assert placeholders == 7


def test_prune_batched_eager_mode_matches_pre_fix_behavior():
    """
    prune_batch=0 is the legacy mode: prune every image over budget on
    every call. Kept for backward compatibility with any caller that
    explicitly disables batching.
    """
    messages = [_msg_with_image() for _ in range(6)]

    n_pruned = _prune_old_screenshots(messages, keep_last_n=4, prune_batch=0)

    # 6 total, keep 4, prune 2 (eager)
    assert n_pruned == 2
