"""
tests/engine/test_hitl_portal_capture.py

Unit tests for Phase 1: HITL portal-aware click capture.

Tests cover:
- Portal detection JS contract (via Python-side record assertions)
- AutorecordSerializer portal branching (primeng_dropdown / scoped click / degraded)
- _on_human_action WARN log for partial captures
- Non-portal regression (AC-VERIFY-5: byte-identical output)

The JS detection helpers (detectPortal, resolveTrigger, extractTargetText,
deriveCaptureConfidence) are tested via the *contract they expose* — records with
portal fields set — rather than by executing JS in a real browser (that is UAT scope).
See: task Test Strategy §"JS tests approach".
"""
from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.engine.autorecord import (
    AutorecordSerializer,
    _maybe_portal_serialize,
    _normalize_portal_class,
)

# ---------------------------------------------------------------------------
# Helpers — build minimal click records as if JS emitted them
# ---------------------------------------------------------------------------

def _make_click_record(
    best_selector: str = "Submit",
    strategy: str = "get_by_text",
    inner_text: str = "Submit",
    css_path: str = "html > body > div > button",
    # portal fields (None = absent from JS record, like non-portal clicks today)
    portal_class: str | None = None,
    trigger_selector: str | None = None,
    target_text: str | None = None,
    trigger_resolution_confidence: str | None = None,
    is_anonymous_portal: bool | None = None,
    capture_confidence: str | None = None,
    aria_label: str = "",
) -> dict:
    """Construct a raw click record as the JS bridge would produce it."""
    rec: dict = {
        "run_id": "run-test-001",
        "event_type": "click",
        "tag": "button",
        "test_id": "",
        "aria_label": aria_label,
        "role": "",
        "inner_text": inner_text,
        "best_selector": best_selector,
        "strategy": strategy,
        "css_path": css_path,
        "value": "",
        "timestamp": "2026-07-29T00:00:00.000Z",
    }
    # Only add portal fields when explicitly provided (mirrors JS behavior)
    if portal_class is not None:
        rec["portal_class"] = portal_class
    if trigger_selector is not None:
        rec["trigger_selector"] = trigger_selector
    if target_text is not None:
        rec["target_text"] = target_text
    if trigger_resolution_confidence is not None:
        rec["trigger_resolution_confidence"] = trigger_resolution_confidence
    if is_anonymous_portal is not None:
        rec["is_anonymous_portal"] = is_anonymous_portal
    if capture_confidence is not None:
        rec["capture_confidence"] = capture_confidence
    return rec


def _make_portal_record(
    portal_class: str = ".p-select-overlay",
    trigger_selector: str = "th.col p-select",
    target_text: str = "Option A",
    capture_confidence: str = "full",
    trigger_resolution_confidence: str = "aria",
    is_anonymous_portal: bool = False,
    inner_text: str = "Option A",
    css_path: str = "html > body > div.p-select-overlay > div > ul > li:nth-child(1)",
) -> dict:
    """Convenience: a fully-populated portal click record."""
    return _make_click_record(
        best_selector=target_text,
        strategy="get_by_role:option",
        inner_text=inner_text,
        css_path=css_path,
        portal_class=portal_class,
        trigger_selector=trigger_selector,
        target_text=target_text,
        trigger_resolution_confidence=trigger_resolution_confidence,
        is_anonymous_portal=is_anonymous_portal,
        capture_confidence=capture_confidence,
    )


# ---------------------------------------------------------------------------
# _normalize_portal_class
# ---------------------------------------------------------------------------

class TestNormalizePortalClass:
    def test_adds_leading_dot_when_missing(self):
        assert _normalize_portal_class("p-select-overlay") == ".p-select-overlay"

    def test_preserves_leading_dot_when_present(self):
        assert _normalize_portal_class(".p-select-overlay") == ".p-select-overlay"

    def test_empty_string_passthrough(self):
        assert _normalize_portal_class("") == ""

    def test_po_prefix_preserved(self):
        assert _normalize_portal_class("po-sorting-dropdown-panel") == ".po-sorting-dropdown-panel"


# ---------------------------------------------------------------------------
# _maybe_portal_serialize
# ---------------------------------------------------------------------------

class TestMaybePortalSerialize:
    # ── Non-portal path (capture_confidence absent or "none") ──

    def test_non_portal_record_returns_none(self):
        """Non-portal click (no portal fields) → None → serializer uses standard path."""
        rec = _make_click_record()
        assert _maybe_portal_serialize(rec) is None

    def test_capture_confidence_none_returns_none(self):
        """Explicit capture_confidence='none' → None (standard click path)."""
        rec = _make_click_record(capture_confidence="none")
        assert _maybe_portal_serialize(rec) is None

    def test_non_click_event_type_returns_none(self):
        """portal fields on a non-click event → None (serializer ignores portal for keyup)."""
        rec = _make_click_record(capture_confidence="full")
        rec["event_type"] = "keyup"
        assert _maybe_portal_serialize(rec) is None

    def test_unrecognized_portal_prefix_falls_through(self):
        """portal_class='.custom-overlay' (not .p- or .po-) → None → standard click."""
        rec = _make_portal_record(portal_class=".custom-overlay")
        result = _maybe_portal_serialize(rec)
        assert result is None

    def test_portal_class_without_known_prefix_falls_through(self):
        """portal_class='.x-widget' → None."""
        rec = _make_portal_record(portal_class=".x-widget")
        assert _maybe_portal_serialize(rec) is None

    # ── Full capture path (primeng_dropdown) ──

    def test_full_capture_emits_primeng_dropdown(self):
        """Full capture → action='primeng_dropdown' with all three required fields."""
        rec = _make_portal_record(
            portal_class=".p-select-overlay",
            trigger_selector="th.col p-select",
            target_text="Due Date A-Z",
            capture_confidence="full",
        )
        result = _maybe_portal_serialize(rec)
        assert result is not None
        assert result["action"] == "primeng_dropdown"
        assert result["trigger_selector"] == "th.col p-select"
        assert result["target_text"] == "Due Date A-Z"
        assert result["portal_class"] == ".p-select-overlay"
        assert result["_capture_confidence"] == "full"

    def test_full_capture_preserves_inner_text(self):
        rec = _make_portal_record(inner_text="Due Date A-Z", capture_confidence="full")
        result = _maybe_portal_serialize(rec)
        assert result["inner_text"] == "Due Date A-Z"

    def test_full_capture_normalizes_portal_class_dot(self):
        """portal_class without dot is normalized in the output."""
        rec = _make_portal_record(
            portal_class="p-select-overlay",  # no leading dot from JS
            capture_confidence="full",
            trigger_selector="some-sel",
            target_text="Val",
        )
        result = _maybe_portal_serialize(rec)
        assert result["portal_class"] == ".p-select-overlay"

    @pytest.mark.parametrize("portal_class", [
        ".p-select-overlay",
        ".p-dropdown-panel",
        ".p-autocomplete-panel",
        ".p-tieredmenu",
        ".p-menu",
        ".p-popover",
        ".po-sorting-dropdown-panel",
        ".sort-panel",
    ])
    def test_all_allowlist_portal_classes_recognized_in_full_path(self, portal_class):
        """AC-VERIFY-1: all 8 known portal classes route through the portal path."""
        rec = _make_portal_record(
            portal_class=portal_class,
            trigger_selector="sel",
            target_text="Opt",
            capture_confidence="full",
        )
        result = _maybe_portal_serialize(rec)
        assert result is not None
        assert result["action"] == "primeng_dropdown"

    # ── Portal-only path (scoped click with container_selector) ──

    def test_portal_only_emits_scoped_click(self):
        """portal_only → action='click' with container_selector."""
        rec = _make_portal_record(
            trigger_selector="",  # trigger unresolved
            capture_confidence="portal_only",
        )
        result = _maybe_portal_serialize(rec)
        assert result is not None
        assert result["action"] == "click"
        assert result["strategy"] == "get_by_text"
        assert result["container_selector"] == ".p-select-overlay"
        assert result["_capture_confidence"] == "portal_only"

    def test_portal_only_uses_target_text_over_inner_text(self):
        rec = _make_portal_record(
            target_text="Option X",
            inner_text="Option X",
            capture_confidence="portal_only",
        )
        result = _maybe_portal_serialize(rec)
        assert result["name"] == "Option X"

    def test_portal_only_falls_back_to_inner_text_when_target_text_empty(self):
        rec = _make_portal_record(
            target_text="",
            inner_text="Fallback Text",
            capture_confidence="portal_only",
        )
        result = _maybe_portal_serialize(rec)
        assert result["name"] == "Fallback Text"
        assert result["strategy"] == "get_by_text"

    def test_portal_only_falls_back_to_aria_label_when_texts_empty(self):
        rec = _make_portal_record(
            target_text="",
            inner_text="",
            capture_confidence="portal_only",
        )
        rec["aria_label"] = "Aria Option"
        result = _maybe_portal_serialize(rec)
        assert result["name"] == "Aria Option"

    # ── Portal-only degraded (no text at all → css_path scoped) ──

    def test_portal_only_degraded_when_all_text_empty(self):
        """No text at all → css_path scoped, strategy=css_selector, confidence=portal_only_degraded."""
        rec = _make_portal_record(
            target_text="",
            inner_text="",
            css_path="html > body > div.p-select-overlay > ul > li",
            capture_confidence="portal_only",
        )
        rec["aria_label"] = ""
        result = _maybe_portal_serialize(rec)
        assert result is not None
        assert result["_capture_confidence"] == "portal_only_degraded"
        assert result["strategy"] == "css_selector"
        assert result["name"] == "html > body > div.p-select-overlay > ul > li"
        assert result["container_selector"] == ".p-select-overlay"


# ---------------------------------------------------------------------------
# AutorecordSerializer with portal records
# ---------------------------------------------------------------------------

class TestAutorecordSerializerPortal:
    serializer = AutorecordSerializer()

    # ── AC-VERIFY-5: non-portal byte-identical ──

    def test_non_portal_click_byte_identical(self):
        """Non-portal click record → exactly same output as before this feature."""
        raw = [_make_click_record(
            best_selector="Submit",
            strategy="get_by_text",
            inner_text="Submit",
        )]
        result = self.serializer.serialize(raw)
        assert len(result) == 1
        act = result[0]
        assert act == {
            "action": "click",
            "strategy": "get_by_text",
            "name": "Submit",
            "inner_text": "Submit",
        }
        # CRITICAL: no _capture_confidence, no portal fields
        assert "_capture_confidence" not in act
        assert "portal_class" not in act

    def test_non_portal_click_with_capture_confidence_none_byte_identical(self):
        """Explicit capture_confidence='none' → byte-identical to non-portal."""
        raw = [_make_click_record(capture_confidence="none", best_selector="Btn", inner_text="Btn")]
        result = self.serializer.serialize(raw)
        assert result[0] == {
            "action": "click",
            "strategy": "get_by_text",
            "name": "Btn",
            "inner_text": "Btn",
        }
        assert "_capture_confidence" not in result[0]

    def test_full_portal_click_emits_primeng_dropdown(self):
        """Full portal capture in a sequence → primeng_dropdown action."""
        raw = [_make_portal_record(
            portal_class=".p-select-overlay",
            trigger_selector="th.col p-select",
            target_text="Due Date A-Z",
            capture_confidence="full",
        )]
        result = self.serializer.serialize(raw)
        assert len(result) == 1
        assert result[0]["action"] == "primeng_dropdown"
        assert result[0]["trigger_selector"] == "th.col p-select"
        assert result[0]["target_text"] == "Due Date A-Z"
        assert result[0]["portal_class"] == ".p-select-overlay"
        assert result[0]["_capture_confidence"] == "full"

    def test_portal_only_click_uses_container_selector(self):
        """portal_only capture → click with container_selector."""
        raw = [_make_portal_record(
            target_text="Option A",
            trigger_selector="",
            capture_confidence="portal_only",
        )]
        result = self.serializer.serialize(raw)
        assert len(result) == 1
        act = result[0]
        assert act["action"] == "click"
        assert act["container_selector"] == ".p-select-overlay"
        assert act["name"] == "Option A"
        assert act["_capture_confidence"] == "portal_only"

    def test_mixed_sequence_portal_and_non_portal(self):
        """Mixed sequence: non-portal clicks stay byte-identical; portal click emits primeng_dropdown."""
        raw = [
            _make_click_record(best_selector="Sort", inner_text="Sort"),
            _make_portal_record(
                portal_class=".p-select-overlay",
                trigger_selector="th.col p-select",
                target_text="Due Date A-Z",
                capture_confidence="full",
            ),
            _make_click_record(best_selector="Submit", inner_text="Submit"),
        ]
        result = self.serializer.serialize(raw)
        assert len(result) == 3
        assert result[0] == {"action": "click", "strategy": "get_by_text", "name": "Sort", "inner_text": "Sort"}
        assert result[1]["action"] == "primeng_dropdown"
        assert result[2] == {"action": "click", "strategy": "get_by_text", "name": "Submit", "inner_text": "Submit"}

    def test_portal_click_not_deduplicated_by_post_process(self):
        """primeng_dropdown before a fill should NOT be deduplicated (different action type)."""
        raw = [
            _make_portal_record(capture_confidence="full"),
            {
                "event_type": "keyup",
                "best_selector": "input#search",
                "strategy": "css",
                "value": "test",
                "inner_text": "",
            },
        ]
        result = self.serializer.serialize(raw)
        assert len(result) == 2
        assert result[0]["action"] == "primeng_dropdown"
        assert result[1]["action"] == "fill"


# ---------------------------------------------------------------------------
# Portal detection contract tests (capture_confidence field derivation)
# ---------------------------------------------------------------------------

class TestCaptureConfidenceContract:
    """
    Tests that verify the deriveCaptureConfidence derivation table from algorithm doc.
    These test the CONTRACT: given a record with portal fields, downstream behavior
    is correct. JS helper functions are not directly invokable here (no browser) —
    we test that the Python serializer correctly branches on the enum values.
    """

    serializer = AutorecordSerializer()

    def test_confidence_full_requires_all_three_fields(self):
        """capture_confidence='full' iff portal_class + trigger_selector + target_text all non-empty."""
        rec = _make_portal_record(
            portal_class=".p-select-overlay",
            trigger_selector="sel",
            target_text="Opt",
            capture_confidence="full",
        )
        result = self.serializer.serialize([rec])
        assert result[0]["action"] == "primeng_dropdown"

    def test_confidence_portal_only_when_trigger_missing(self):
        """capture_confidence='portal_only' when trigger_selector is empty."""
        rec = _make_portal_record(
            trigger_selector="",
            capture_confidence="portal_only",
        )
        result = self.serializer.serialize([rec])
        assert result[0]["action"] == "click"
        assert "container_selector" in result[0]

    def test_confidence_portal_only_for_anonymous_portal(self):
        """Anonymous portal (is_anonymous=True) → capture_confidence='portal_only'."""
        # Anonymous: portal_class="" but capture_confidence="portal_only"
        # The serializer should fall through to standard click (portal_class prefix guard)
        rec = _make_click_record(
            portal_class="",
            trigger_selector="",
            target_text="",
            is_anonymous_portal=True,
            capture_confidence="portal_only",
        )
        result = self.serializer.serialize([rec])
        # No known portal prefix → falls through to standard click (byte-identical)
        assert result[0]["action"] == "click"
        assert "_capture_confidence" not in result[0]

    def test_confidence_none_for_non_portal_click(self):
        """capture_confidence='none' (or absent) → byte-identical non-portal output."""
        rec = _make_click_record()
        result = self.serializer.serialize([rec])
        assert result[0] == {
            "action": "click",
            "strategy": "get_by_text",
            "name": "Submit",
            "inner_text": "Submit",
        }


# ---------------------------------------------------------------------------
# _on_human_action WARN log for partial captures
# ---------------------------------------------------------------------------

class TestOnHumanActionWarnLog:
    """
    Test that _on_human_action emits a WARN log when capture_confidence='portal_only'.
    We import and call the function indirectly via _inject_click_capture_listener
    through a mock page.
    """

    def _make_mock_page(self):
        """Create a minimal mock page that captures the _on_human_action callback."""
        page = AsyncMock()
        page.frames = []
        page.is_closed.return_value = False
        context = MagicMock()
        context._mock_name = "mock_context"
        page.context = context
        # Capture the callback registered via expose_function
        self._captured_callback = None

        async def expose_fn(name, callback):
            if name == "__vqa_record_human_action__":
                self._captured_callback = callback

        page.expose_function.side_effect = expose_fn
        page.evaluate = AsyncMock(return_value=None)
        page.add_init_script = AsyncMock(return_value=None)
        page.on = MagicMock()
        return page

    def test_partial_capture_emits_warn_log(self, caplog):
        """AC-ERROR-1: portal_only record → WARN log with hitl_portal_partial_capture."""
        from backend.engine.human_takeover import _inject_click_capture_listener

        page = self._make_mock_page()

        async def run():
            await _inject_click_capture_listener(page, "run-test-warn")
            assert self._captured_callback is not None
            # Simulate JS emitting a portal_only record
            record = _make_portal_record(
                trigger_selector="",
                capture_confidence="portal_only",
            )
            record["run_id"] = "run-test-warn"
            with caplog.at_level(logging.WARNING, logger="backend.engine.human_takeover"):
                await self._captured_callback(record)

        asyncio.get_event_loop().run_until_complete(run())

        warn_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("hitl_portal_partial_capture" in msg for msg in warn_messages), (
            f"Expected WARN with 'hitl_portal_partial_capture', got: {warn_messages}"
        )

    def test_full_capture_no_warn_log(self, caplog):
        """Full capture → no hitl_portal_partial_capture WARN emitted."""
        from backend.engine.human_takeover import _inject_click_capture_listener

        page = self._make_mock_page()

        async def run():
            await _inject_click_capture_listener(page, "run-test-full")
            assert self._captured_callback is not None
            record = _make_portal_record(
                trigger_selector="sel",
                target_text="Opt",
                capture_confidence="full",
            )
            record["run_id"] = "run-test-full"
            with caplog.at_level(logging.WARNING, logger="backend.engine.human_takeover"):
                await self._captured_callback(record)

        asyncio.get_event_loop().run_until_complete(run())

        warn_messages = [
            r.message for r in caplog.records
            if r.levelno == logging.WARNING and "hitl_portal_partial_capture" in r.message
        ]
        assert len(warn_messages) == 0

    def test_non_portal_click_no_warn_log(self, caplog):
        """Non-portal click (no capture_confidence) → no WARN."""
        from backend.engine.human_takeover import _inject_click_capture_listener

        page = self._make_mock_page()

        async def run():
            await _inject_click_capture_listener(page, "run-test-normal")
            record = _make_click_record()
            record["run_id"] = "run-test-normal"
            with caplog.at_level(logging.WARNING, logger="backend.engine.human_takeover"):
                await self._captured_callback(record)

        asyncio.get_event_loop().run_until_complete(run())

        warn_messages = [
            r.message for r in caplog.records
            if "hitl_portal_partial_capture" in r.message
        ]
        assert len(warn_messages) == 0
